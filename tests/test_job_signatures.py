"""Pinned trust, signature binding, file protection and real signed inventory delivery."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch
from cryptography.exceptions import InvalidSignature
from protec.agent import inventory, cycle
from protec.agent_receipts import ReceiptJournal
from protec.job_signatures import Signer,Trust,generate,protected_document,decode,encode,DOMAIN
from protec.server import Store
from protec.wsgi import create_app
from test_control_plane import HTTPTests as Harness
from test_wsgi import DeploymentTests as WSGIHarness
from wsgiref.validate import validator


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'keys';self.server='https://portal.example.com'
        generate(self.directory,self.server)
        self.signer=Signer.load(self.directory/'signing-key.json')
        self.trust=Trust.load(self.directory/'job-trust.json',self.server)
        self.job={'id':'a'*24,'kind':'refresh_inventory','version':1,'device':'d'*24,'payload':{},'attempt':1,
                  'created':time.time(),'lease':{'token':'k'*43,'expires':time.time()+120}}
    def proof(self):return self.signer.sign(self.job)

    def test_signed_contract_verifies_after_serialization_and_key_reload(self):
        proof=self.proof();job=json.loads(json.dumps(self.job))
        trust=Trust.load(self.directory/'job-trust.json',self.server)
        trust.verify(job,json.loads(json.dumps(proof)),job['device'])
        self.assertEqual(Signer.load(self.directory/'signing-key.json').sign(job),proof)
        expected=DOMAIN+json.dumps({'server':self.server,'job':job},sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
        public=self.signer.private.public_key()
        public.verify(decode(proof['signature'],64),expected)
        with self.assertRaises(InvalidSignature):public.verify(decode(proof['signature'],64),expected[len(DOMAIN):])

    def test_every_execution_field_is_bound_to_signature(self):
        proof=self.proof()
        changes=[{'id':'b'*24},{'device':'e'*24},{'kind':'shell'},{'version':0},{'version':True},
                 {'payload':{'command':'id'}},{'attempt':2},{'created':self.job['created']-1},
                 {'lease':{**self.job['lease'],'expires':self.job['lease']['expires']+1}},
                 {'lease':{**self.job['lease'],'token':'x'*43}},{'extra':True}]
        for change in changes:
            modified={**self.job,**change}
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.trust.verify(modified,proof,self.job['device'])
        with self.assertRaises(ValueError):self.trust.verify(self.job,proof,'e'*24)

    def test_signature_metadata_unknown_key_and_noncanonical_encodings_rejected(self):
        proof=self.proof()
        for change in ({'version':True},{'version':2},{'algorithm':'none'},{'key_id':'0'*64},
                       {'signature':proof['signature']+'='},{'signature':encode(bytes(64))},
                       {'signature':encode(bytes(63))},{'extra':'ignored'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.trust.verify(self.job,{**proof,**change},self.job['device'])

    def test_origin_pin_prevents_cross_server_reuse_even_with_same_key(self):
        document=protected_document(self.directory/'job-trust.json')
        with self.assertRaises(ValueError):Trust(document,'https://other.example.com')
        changed=Trust({**document,'server':'https://other.example.com'},'https://other.example.com')
        with self.assertRaises(ValueError):changed.verify(self.job,self.proof(),self.job['device'])
        with self.assertRaises(ValueError):self.trust.verify_delivery([self.job],{self.job['id']:self.proof()},self.job['device'],'https://other.example.com')

    def test_stale_and_superseded_attempt_signatures_cannot_authorize_delivery(self):
        proof=self.proof()
        with patch('protec.jobs.time.time',return_value=self.job['lease']['expires']):
            with self.assertRaises(ValueError):self.trust.verify(self.job,proof,self.job['device'])
        next_attempt={**self.job,'attempt':2,'lease':{**self.job['lease'],'token':'n'*43}}
        with self.assertRaises(ValueError):self.trust.verify(next_attempt,proof,self.job['device'])
        self.trust.verify(next_attempt,self.signer.sign(next_attempt),self.job['device'])

    def test_missing_duplicate_extra_or_legacy_deliveries_fail_closed(self):
        proof=self.proof();job=self.job
        for jobs,proofs in (([job],None),([job],{}),([job],{job['id']:proof,'b'*24:proof}),([job,job],{job['id']:proof}),
                           ([{'id':job['id'],'kind':job['kind']}],{job['id']:proof})):
            with self.assertRaises(ValueError):self.trust.verify_delivery(jobs,proofs,job['device'],self.server)
        self.trust.verify_delivery([],{},job['device'],self.server)

    def test_operator_rotation_accepts_overlap_and_rejects_removed_key_after_reload(self):
        other=Path(self.temp.name)/'new';generate(other,self.server)
        old_doc=protected_document(self.directory/'job-trust.json');new_doc=protected_document(other/'job-trust.json')
        overlap=Trust({**old_doc,'keys':old_doc['keys']+new_doc['keys']},self.server)
        overlap.verify(self.job,self.proof(),self.job['device'])
        overlap.verify(self.job,Signer.load(other/'signing-key.json').sign(self.job),self.job['device'])
        with self.assertRaises(ValueError):Trust(new_doc,self.server).verify(self.job,self.proof(),self.job['device'])
        with self.assertRaises(ValueError):Trust({**old_doc,'keys':old_doc['keys']*2},self.server)
        with self.assertRaises(ValueError):Trust({**old_doc,'keys':[]},self.server)

    def test_generation_never_overwrites_and_files_are_owner_only(self):
        before=(self.directory/'signing-key.json').read_bytes()
        with self.assertRaises(FileExistsError):generate(self.directory,self.server)
        self.assertEqual((self.directory/'signing-key.json').read_bytes(),before)
        self.assertEqual(self.directory.stat().st_mode&0o777,0o700)
        for name in ('signing-key.json','job-trust.json'):
            self.assertEqual((self.directory/name).stat().st_mode&0o777,0o600)
        public=(self.directory/'job-trust.json').read_text()
        self.assertNotIn('private_key',public)
        self.assertNotIn(protected_document(self.directory/'signing-key.json')['private_key'],public)

    def test_unsafe_files_links_duplicate_fields_and_invalid_key_documents_rejected(self):
        path=self.directory/'signing-key.json'
        path.chmod(0o644)
        with self.assertRaises(ValueError):Signer.load(path)
        path.chmod(0o600)
        link=self.directory/'link';link.symlink_to(path)
        with self.assertRaises(OSError):Signer.load(link)
        hard=self.directory/'hard';os.link(path,hard)
        with self.assertRaises(ValueError):Signer.load(path)
        hard.unlink()
        self.directory.chmod(0o755)
        with self.assertRaises(ValueError):Signer.load(path)
        self.directory.chmod(0o700)
        original=protected_document(path)
        for change in ({'version':True},{'private_key':'invalid'},{'key_id':'x'},{'server':'http://remote.example'},{'extra':True}):
            with self.assertRaises(ValueError):Signer({**original,**change})
        path.write_text('{"version":1,"version":1}')
        with self.assertRaises(ValueError):Signer.load(path)
        path.write_bytes(b' ' * 16385)
        with self.assertRaises(ValueError):Signer.load(path)

    def test_signing_failure_rolls_back_inventory_and_lease_transaction(self):
        store=Store(Path(self.temp.name)/'control.db',self.signer)
        device=store.enroll(store.enrollment()['token'],inventory());store.queue(device['id'])
        before=store.snapshot()
        with patch.object(self.signer,'sign',side_effect=ValueError('Injected signing failure')):
            with self.assertRaises(ValueError):store.heartbeat(device['id'],{**inventory(),'hostname':'changed'},1)
        after=store.snapshot()
        for field in ('devices','jobs','audit'):self.assertEqual(before[field],after[field])

    def test_agent_refuses_untrusted_job_before_journal_or_forced_collection(self):
        state={'id':self.job['device'],'server':self.server,'credential':'test','_package_scan':time.monotonic(),'_packages':{}}
        journal=Mock()
        response={'jobs':[self.job],'job_protocol':1,'job_signatures':{}}
        with patch('protec.agent.request',return_value=response) as request,patch('protec.agent.collect_packages') as collect:
            with self.assertRaises(ValueError):cycle(state,journal,self.trust)
        self.assertEqual(request.call_count,1);collect.assert_not_called();self.assertEqual(journal.mock_calls,[])

    def test_wsgi_configuration_refuses_wrong_origin_and_unsafe_key(self):
        path=self.directory/'signing-key.json'
        create_app(Path(self.temp.name)/'app',self.server,'a'*43,path)
        with self.assertRaises(ValueError):create_app(Path(self.temp.name)/'wrong','https://other.example.com','a'*43,path)
        path.chmod(0o644)
        with self.assertRaises(ValueError):create_app(Path(self.temp.name)/'unsafe',self.server,'a'*43,path)


class SignedHTTPTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    def test_cli_requires_pinned_trust_and_records_a_real_local_receipt(self):
        directory=Path(self.temp.name)/'keys'
        generated=subprocess.run([sys.executable,'-m','protec.job_signatures','--directory',str(directory),'--server',self.url],capture_output=True,text=True,timeout=15)
        self.assertEqual(generated.returncode,0,generated.stderr)
        self.assertNotIn('private_key',generated.stdout)
        self.server.store.job_signer=Signer.load(directory/'signing-key.json')
        device=self.server.store.enroll(self.server.store.enrollment()['token'],inventory());self.server.store.queue(device['id'])
        state=Path(self.temp.name)/'agent.json'
        state.write_text(json.dumps({**device,'server':self.url}));state.chmod(0o600)
        command=[sys.executable,'-m','protec.agent','--state',str(state),'--job-trust',str(directory/'job-trust.json'),'--once']
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn(device['credential'],result.stdout+result.stderr)
        journal=ReceiptJournal(state.with_name('agent.json.receipts'),self.url,device['id'])
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})
        self.server.store.job_signer=None;self.server.store.queue(device['id'])
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,1)
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})

    def test_signed_http_round_trip_and_signatures_are_not_persisted_or_in_dashboard(self):
        directory=Path(self.temp.name)/'keys';generate(directory,self.url)
        self.server.store.job_signer=Signer.load(directory/'signing-key.json')
        trust=Trust.load(directory/'job-trust.json',self.url)
        device=self.server.store.enroll(self.server.store.enrollment()['token'],inventory());self.server.store.queue(device['id'])
        journal=ReceiptJournal(Path(self.temp.name)/'receipts',self.url,device['id'])
        self.assertEqual(cycle({**device,'server':self.url},journal,trust),1)
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})
        dashboard=json.dumps(self.server.store.snapshot())
        for forbidden in ('private_key','job_signatures','lease_token'):
            self.assertNotIn(forbidden,dashboard)
        self.assertEqual(cycle({**device,'server':self.url},journal,trust),0)
        self.server.store.job_signer=None
        self.server.store.queue(device['id'])
        with self.assertRaises(ValueError):cycle({**device,'server':self.url},journal,trust)
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})


class SignedWSGITests(unittest.TestCase):
    setUp=WSGIHarness.setUp
    request=WSGIHarness.request
    def test_configured_wsgi_key_signs_delivery_and_reloads_without_changing_identity(self):
        root=Path(self.directory.name);keys=root/'keys';server='https://portal.example.com'
        generate(keys,server)
        self.app=validator(create_app(root,server,self.token,keys/'signing-key.json'))
        def post(path,token,body):
            response=self.request(path,'POST',token,body=json.dumps(body).encode())
            self.assertEqual(response['status'],200)
            return json.loads(response['body'])
        token=post('/api/enrollments',self.token,{})['token']
        device=post('/api/enroll',token,{'inventory':inventory()})
        post('/api/jobs',self.token,{'device':device['id']})
        result=post('/api/heartbeat',device['credential'],{'inventory':inventory(),'job_protocol':1})
        trust=Trust.load(keys/'job-trust.json',server)
        trust.verify_delivery(result['jobs'],result['job_signatures'],device['id'],server)
        self.app=validator(create_app(root,server,self.token,keys/'signing-key.json'))
        again=post('/api/heartbeat',device['credential'],{'inventory':inventory(),'job_protocol':1})
        self.assertEqual(again['jobs'],[])
        trust.verify_delivery(again['jobs'],again['job_signatures'],device['id'],server)


del Harness,WSGIHarness
