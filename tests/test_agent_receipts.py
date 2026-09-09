"""Durable local metadata, secure file handling and interrupted acknowledgement recovery."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError
from protec.agent import cycle, inventory
from protec.agent_receipts import ReceiptJournal,ReceiptError
from protec.jobs import inventory_digest
from test_control_plane import HTTPTests as Harness

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'agent.receipts';self.now=1000
        self.device='d'*24;self.server='https://portal.example.com'
        self.journal=ReceiptJournal(self.directory,self.server,self.device,clock=lambda:self.now)
    def job(self,number=1,attempt=1):
        return {'id':f'{number:024x}','kind':'refresh_inventory','version':1,'device':self.device,'payload':{},'attempt':attempt,'created':self.now,'lease':{'token':'k'*43,'expires':self.now+120}}
    def receipt(self,job):
        return {'version':1,'job':job['id'],'device':self.device,'kind':'refresh_inventory','attempt':job['attempt'],'outcome':'succeeded','inventory_sha256':'c'*64,'recorded_at':self.now}
    def test_persistence_and_secret_free_owner_only_metadata(self):
        job=self.job();self.assertTrue(self.journal.begin(job));self.journal.reported(job,'c'*64);self.journal.acknowledge(job,self.receipt(job))
        reopened=ReceiptJournal(self.directory,self.server,self.device,clock=lambda:self.now)
        self.assertEqual(reopened.status()['counts'],{'acknowledged':1});self.assertEqual(reopened.pending(),[])
        self.assertFalse(reopened.begin(job));self.assertFalse(reopened.begin(self.job(attempt=2)))
        self.assertEqual(self.directory.stat().st_mode&0o777,0o700);self.assertEqual(reopened.path.stat().st_mode&0o777,0o600)
        self.assertNotIn(job['lease']['token'],reopened.path.read_bytes().decode(errors='ignore'))
        self.assertNotIn('lease_token',json.dumps(reopened.status()))
    def test_started_attempt_is_not_reexecuted_and_new_attempt_can_retry_read_only_work(self):
        job=self.job();self.journal.begin(job)
        reopened=ReceiptJournal(self.directory,self.server,self.device,clock=lambda:self.now)
        self.assertFalse(reopened.begin(job))
        reopened.reconcile({'job':job['id'],'attempt':1},{'id':job['id'],'attempt':2,'status':'running','receipt':None})
        self.assertEqual(reopened.status()['counts'],{'superseded':1})
        self.assertTrue(reopened.begin(self.job(attempt=2)))
    def test_lost_response_reconciles_without_saving_or_resending_a_lease_token(self):
        job=self.job();self.journal.begin(job);self.journal.reported(job,'c'*64)
        reopened=ReceiptJournal(self.directory,self.server,self.device,clock=lambda:self.now)
        record=reopened.pending()[0]
        reopened.reconcile(record,{'id':job['id'],'attempt':1,'status':'completed','receipt':self.receipt(job)})
        self.assertEqual(reopened.status()['counts'],{'acknowledged':1})
    def test_conflicting_or_secret_bearing_receipts_are_not_persisted(self):
        job=self.job();self.journal.begin(job);self.journal.reported(job,'c'*64)
        for change in ({'device':'e'*24},{'attempt':2},{'inventory_sha256':'f'*64},{'lease_token':'secret'},{'recorded_at':float('nan')},{'version':True}):
            with self.subTest(change=change),self.assertRaises(ReceiptError):self.journal.acknowledge(job,{**self.receipt(job),**change})
        self.assertEqual(self.journal.status()['counts'],{'completion_pending':1})
        self.assertNotIn('secret',self.journal.path.read_bytes().decode(errors='ignore'))
    def test_server_cancellation_and_missing_history_are_explicit(self):
        for number,status,expected in ((1,'cancelled','server_cancelled'),(2,'failed','server_failed'),(3,'unknown','unknown')):
            job=self.job(number);self.journal.begin(job)
            self.journal.reconcile({'job':job['id'],'attempt':1},{'id':job['id'],'attempt':0 if status=='unknown' else 1,'status':status,'receipt':None})
            self.assertIn(expected,self.journal.status()['counts'])
    def test_binding_permissions_symlinks_and_unknown_database_versions_fail_closed(self):
        for server,device in ((self.server,'e'*24),('https://other.example.com',self.device)):
            with self.assertRaises(ReceiptError):ReceiptJournal(self.directory,server,device)
        self.journal.path.chmod(0o644)
        with self.assertRaises(ReceiptError):self.journal.status()
        self.journal.path.chmod(0o600)
        link=Path(self.temp.name)/'link';link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(ReceiptError):ReceiptJournal(link,self.server,self.device)
        other=Path(self.temp.name)/'other';other.mkdir(mode=0o700)
        (other/'journal.db').symlink_to(self.journal.path)
        with self.assertRaises(ReceiptError):ReceiptJournal(other,self.server,self.device)
        with self.journal.connect() as db:db.execute('PRAGMA user_version=99')
        with self.assertRaises(ReceiptError):ReceiptJournal(self.directory,self.server,self.device)
    def test_capacity_preserves_unresolved_records_and_prunes_only_old_terminal_evidence(self):
        with patch('protec.agent_receipts.MAX_RECORDS',1):
            job=self.job();self.journal.begin(job)
            with self.assertRaises(ReceiptError):self.journal.begin(self.job(2))
            self.journal.reported(job,'c'*64);self.journal.acknowledge(job,self.receipt(job))
            with self.assertRaises(ReceiptError):self.journal.begin(self.job(2))
            self.now+=31*86400
            self.assertTrue(self.journal.begin(self.job(2)))
            self.assertEqual(self.journal.status()['counts'],{'started':1})
    def test_abrupt_process_exit_preserves_reported_attempt(self):
        code="""import json,os,sys
from protec.agent_receipts import ReceiptJournal
args=json.load(sys.stdin)
journal=ReceiptJournal(args['directory'],args['server'],args['device'],clock=lambda:1000)
journal.begin(args['job']);journal.reported(args['job'],'c'*64)
os._exit(9)
"""
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps({'directory':str(self.directory),'server':self.server,'device':self.device,'job':self.job()}),text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,9,result.stderr)
        reopened=ReceiptJournal(self.directory,self.server,self.device,clock=lambda:self.now)
        self.assertEqual(reopened.status()['counts'],{'completion_pending':1})
        with reopened.connect() as db:self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],3)

    def test_cli_status_outputs_metadata_without_contacting_the_control_plane(self):
        state=Path(self.temp.name)/'state.json'
        state.write_text(json.dumps({'id':self.device,'server':'http://127.0.0.1:1','credential':'t'*43}))
        state.chmod(0o600)
        result=subprocess.run([sys.executable,'-m','protec.agent','--state',str(state),'--receipt-status'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'counts':{},'recent':[]})
        self.assertNotIn('t'*43,result.stdout+result.stderr)

    def test_local_write_failure_prevents_forced_collection_and_completion(self):
        job=self.job();state={'id':self.device,'server':self.server,'credential':'device-secret','_package_scan':float('inf'),'_packages':{}}
        with patch('protec.agent.request',return_value={'job_protocol':1,'jobs':[job]} ) as request,patch('protec.agent_receipts.validate_envelope'),patch('protec.agent.validate_envelope',side_effect=lambda job,device:job),patch.object(self.journal,'begin',side_effect=ReceiptError('disk failure')),patch('protec.agent.collect_packages') as collector:
            with self.assertRaises(ReceiptError):cycle(state,self.journal)
            self.assertEqual(request.call_count,1);collector.assert_not_called()


class ReceiptHTTPTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    def device(self):
        return self.server.store.enroll(self.server.store.enrollment()['token'],inventory())
    def test_lookup_is_device_scoped_and_service_credentials_are_rejected(self):
        one,two=self.device(),self.device();job=self.server.store.queue(one['id'])['id']
        self.assertEqual(self.request('/api/job-receipt?job='+job,one['credential'])[1]['status'],'queued')
        self.assertEqual(self.request('/api/job-receipt?job='+job,two['credential'])[1]['status'],'unknown')
        self.assertEqual(self.request('/api/job-receipt?job='+job,'a'*40)[0],401)
        self.assertEqual(self.request('/api/job-receipt?job=invalid',one['credential'])[0],400)
        self.server.store.revoke(one['id'])
        self.assertEqual(self.request('/api/job-receipt?job='+job,one['credential'])[0],401)
    def test_agent_recovers_a_committed_completion_after_the_response_is_lost_and_agent_restarts(self):
        device=self.device();self.server.store.queue(device['id'])
        directory=Path(self.temp.name)/'agent.receipts'
        journal=ReceiptJournal(directory,self.url,device['id'])
        from protec.agent import request as real_request
        def lose_response(server,path,token,body):
            result=real_request(server,path,token,body)
            if path=='/api/complete':raise URLError('simulated lost response')
            return result
        with patch('protec.agent.request',side_effect=lose_response):
            with self.assertRaises(URLError):cycle({**device,'server':self.url},journal)
        self.assertEqual(journal.status()['counts'],{'completion_pending':1})
        self.assertEqual(self.server.store.snapshot()['jobs'][0]['status'],'completed')
        reopened=ReceiptJournal(directory,self.url,device['id'])
        with patch('protec.agent.request',wraps=real_request) as calls:
            cycle({**device,'server':self.url},reopened)
            self.assertFalse(any(call.args[1]=='/api/complete' for call in calls.call_args_list))
        self.assertEqual(reopened.status()['counts'],{'acknowledged':1})
        self.assertEqual(sum(row['action']=='inventory.completed' for row in self.server.store.snapshot()['audit']),1)


del Harness
