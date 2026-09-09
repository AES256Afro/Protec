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
