from contextlib import contextmanager
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import sys
from protec.package_changes import run_change,validate_payload
from protec.jobs import inventory_digest
from protec.job_signatures import generate,Signer,Trust
from protec.agent_receipts import ReceiptJournal,ReceiptError
from protec import capabilities
from test_package_jobs import plan_for


class ChangeCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.device='a'*24;self.origin='https://fixture.invalid'
        directory=Path(self.tmp.name)/'keys';generate(directory,self.origin)
        self.signer=Signer.load(directory/'signing-key.json');self.trust=Trust.load(directory/'job-trust.json',self.origin)
        plan=plan_for(self.device,{'action':'install','packages':[{'name':'fixture','version':'1.0'}]})
        plan.update(version=2,artifacts=[{'name':'fixture','version':'1.0','sha256':'c'*64,'size':100}]);plan['plan_sha256']=inventory_digest({k:v for k,v in plan.items() if k!='plan_sha256'})
        approval={'id':'b'*24,'approved_by':'fixture-admin','approved_at':int(time.time()),'expires':plan['expires'],'plan_sha256':plan['plan_sha256']}
        self.job={'id':'c'*24,'kind':'apply_packages','version':1,'device':self.device,'payload':{'plan':plan,'approval':approval},'created':time.time(),'attempt':1,'lease':{'token':'k'*43,'expires':time.time()+120}}
        self.proof=self.signer.sign(self.job)
        self.policy={'version':1,'packages':['fixture'],'allow_remove':False}
        self.journal=ReceiptJournal(Path(self.tmp.name)/'journal',self.origin,self.device)
        self.commits=0
        owner=self
        class Cache:
            def commit(self,**kwargs):
                owner.assertEqual(kwargs,{'allow_unauthenticated':False});owner.commits+=1;return True
            def open(self,**kwargs):pass
            def __contains__(self,key):return key=='fixture'
            def __getitem__(self,key):return SimpleNamespace(installed=SimpleNamespace(version='1.0'))
        self.cache=Cache()
        @contextmanager
        def locked(*args):yield self.cache
        base=SimpleNamespace(OpProgress=lambda:None);progress=SimpleNamespace(base=base)
        class Config(dict):
            def value_list(self,key):return []
            def clear(self,key=None):
                if key is None:super().clear()
                else:self.pop(key,None)
        modules={'apt':SimpleNamespace(progress=progress),'apt.progress':progress,'apt.progress.base':base,'apt_pkg':SimpleNamespace(config=Config())}
        for p in (patch('protec.package_changes.geteuid',return_value=0),patch('protec.package_changes.locked_plan',locked),patch.dict(sys.modules,modules)):
            p.start();self.addCleanup(p.stop)

    def execute(self):return run_change(self.job,self.proof,self.device,self.trust,self.policy,self.journal)

    def test_signed_execution_verifies_state_and_refuses_replay(self):
        result=self.execute();self.assertEqual(result['outcome'],'succeeded');self.assertEqual(self.commits,1)
        self.assertEqual(self.journal.status()['counts'],{'completion_pending':1})
        with self.assertRaises(ReceiptError):self.execute()
        self.assertEqual(self.commits,1)

    def test_local_policy_refusal_never_calls_package_manager(self):
        self.policy['packages']=['different-package']
        self.assertEqual(self.execute()['outcome'],'refused');self.assertEqual(self.commits,0)

    def test_wrong_signature_and_approval_never_start_local_attempt(self):
        self.job['payload']['approval']['approved_by']='other-admin'
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.journal.status()['counts'],{})
        self.job['payload']['approval']['plan_sha256']='f'*64
        with self.assertRaises(ValueError):validate_payload(self.job['payload'])

    def test_interruption_leaves_durable_started_record_and_cannot_retry(self):
        with patch.object(self.cache,'commit',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        self.assertEqual(self.journal.status()['counts'],{'started':1})
        with self.assertRaises(ReceiptError):self.execute()

    def test_failure_after_commit_attempt_is_uncertain(self):
        with patch.object(self.cache,'commit',side_effect=SystemError('native failure')):
            self.assertEqual(self.execute()['outcome'],'uncertain')
        self.assertEqual(self.journal.status()['counts'],{'completion_pending':1})

    def test_mutation_is_not_admitted_by_the_remote_agent_or_server(self):
        offer={'version':1,'jobs':[{'kind':'apply_packages','versions':[1]}]}
        self.assertEqual(capabilities.admitted(offer,1),frozenset())
        with self.assertRaises(ValueError):capabilities.validate_delivery([self.job],offer,1)

    def test_nonroot_execution_is_rejected_before_local_attempt(self):
        with patch('protec.package_changes.geteuid',return_value=1000):
            with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.journal.status()['counts'],{})

    def test_native_failure_restores_worker_frontend_environment(self):
        import os
        with patch.dict(os.environ,{'DEBIAN_FRONTEND':'readline'}),patch.object(self.cache,'commit',side_effect=SystemError('failed')):
            self.assertEqual(self.execute()['outcome'],'uncertain')
            self.assertEqual(os.environ['DEBIAN_FRONTEND'],'readline')

    def test_journal_origin_must_match_pinned_signer_origin(self):
        self.journal=ReceiptJournal(Path(self.tmp.name)/'other-journal','https://other.invalid',self.device)
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.journal.status()['counts'],{})

    def next_job(self):
        self.job={**self.job,'id':'d'*24};self.proof=self.signer.sign(self.job)

    def acknowledge(self,result):
        self.journal.acknowledge(self.job,{'version':1,'job':self.job['id'],'device':self.device,'kind':'apply_packages','attempt':1,'outcome':result['outcome'],'result_sha256':inventory_digest(result),'recorded_at':time.time()})

    def test_full_result_survives_reopen_without_lease_secrets(self):
        result=self.execute()
        reopened=ReceiptJournal(self.journal.directory,self.origin,self.device)
        self.assertEqual(reopened.mutation_result(self.job['id']),result)
        self.assertNotIn(self.job['lease']['token'].encode(),reopened.path.read_bytes())
        self.assertIsNone(reopened.mutation_result('f'*24))

    def test_new_change_waits_for_acknowledgement(self):
        result=self.execute();old=self.job
        self.next_job()
        with self.assertRaises(ReceiptError):self.execute()
        new=self.job;self.job=old;self.acknowledge(result);self.job=new
        self.assertEqual(self.execute()['outcome'],'succeeded')
        self.assertEqual(self.commits,2)

    def test_acknowledged_uncertain_result_still_blocks_new_changes(self):
        with patch.object(self.cache,'commit',side_effect=SystemError('failure')):result=self.execute()
        self.acknowledge(result);self.next_job()
        with self.assertRaises(ReceiptError):self.execute()

    def test_server_failure_does_not_erase_unresolved_mutation(self):
        with patch.object(self.cache,'commit',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        self.journal.reconcile({'job':self.job['id'],'attempt':1},{'id':self.job['id'],'attempt':1,'status':'failed','receipt':None})
        self.next_job()
        with self.assertRaises(ReceiptError):self.execute()

    def test_result_write_is_atomic_and_rejects_unexpected_fields(self):
        self.journal.begin(self.job)
        result={'outcome':'refused','plan_sha256':self.job['payload']['plan']['plan_sha256'],'reason':'preflight_refused'}
        with self.assertRaises(ReceiptError):self.journal.mutation_reported(self.job,{**result,'lease':'secret'})
        with self.journal.connect() as db:
            db.execute("CREATE TRIGGER fail_result BEFORE INSERT ON mutation_results BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(ReceiptError):self.journal.mutation_reported(self.job,result)
        self.assertEqual(self.journal.status()['counts'],{'started':1})
        self.assertIsNone(self.journal.mutation_result(self.job['id']))

    def test_schema_two_migration_retains_unresolved_mutation_gate(self):
        self.journal.begin(self.job)
        with self.journal.connect() as db:
            db.execute('DROP TABLE mutation_results');db.execute('PRAGMA user_version=2')
        self.journal=ReceiptJournal(self.journal.directory,self.origin,self.device)
        self.assertEqual(self.journal.status()['counts'],{'started':1})
        self.next_job()
        with self.assertRaises(ReceiptError):self.execute()

    def test_stored_result_corruption_is_detected(self):
        self.execute()
        with self.journal.connect() as db:db.execute("UPDATE attempts SET result_sha256=?",('f'*64,))
        with self.assertRaises(ReceiptError):self.journal.mutation_result(self.job['id'])

    def test_hard_exit_after_result_write_recovers_complete_result(self):
        import json
        import subprocess
        result={'outcome':'refused','plan_sha256':self.job['payload']['plan']['plan_sha256'],'reason':'preflight_refused'}
        code="""import json,os,sys
from protec.agent_receipts import ReceiptJournal
p=json.load(sys.stdin)
journal=ReceiptJournal(p['directory'],p['origin'],p['device'])
journal.begin(p['job']);journal.mutation_reported(p['job'],p['result'])
os._exit(73)
"""
        process=subprocess.run([sys.executable,'-c',code],input=json.dumps({'directory':str(self.journal.directory),'origin':self.origin,'device':self.device,'job':self.job,'result':result}),capture_output=True,text=True,timeout=10)
        self.assertEqual(process.returncode,73,process.stderr)
        reopened=ReceiptJournal(self.journal.directory,self.origin,self.device)
        self.assertEqual(reopened.mutation_result(self.job['id']),result)
        self.assertEqual(reopened.status()['counts'],{'completion_pending':1})
