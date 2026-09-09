from contextlib import contextmanager
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from protec.apt_revalidate import locked_plan
from protec.jobs import inventory_digest
from test_package_jobs import plan_for


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.device='a'*24
        self.request={'action':'install','packages':[{'name':'fixture','version':'1.0'}]}
        self.plan=plan_for(self.device,self.request)
        self.plan.update(version=2,artifacts=[{'name':'fixture','version':'1.0','sha256':'a'*64,'size':100}])
        self.resign()
        self.locked=False;self.closed=False;self.committed=False
        self.candidate=SimpleNamespace(version='1.0',record={'SHA256':'a'*64,'Size':'100'})
        self.package=SimpleNamespace(name='fixture',fullname='fixture:all',installed=None,is_installed=False,versions=[self.candidate],candidate=self.candidate,marked_delete=False,marked_reinstall=False,mark_install=lambda **kwargs:None)
        owner=self
        class Cache:
            broken_count=0
            def __contains__(self,key):return key=='fixture'
            def __getitem__(self,key):return owner.package
            def get_changes(self):return [owner.package]
            def close(self):owner.closed=True
            def commit(self):owner.committed=True;raise AssertionError('Read-only revalidation attempted commit')
        self.cache=Cache()
        @contextmanager
        def lock():
            self.locked=True
            try:yield
            finally:self.locked=False
        base=SimpleNamespace(OpProgress=lambda:None)
        progress=SimpleNamespace(base=base)
        self.modules={'apt':SimpleNamespace(Cache=lambda progress:self.cache,progress=progress), 'apt.progress':progress,'apt.progress.base':base,'apt_pkg':SimpleNamespace(init_config=lambda:None,init_system=lambda:None,config={},SystemLock=lock)}
        self.patches=[patch.dict(sys.modules,self.modules),patch('protec.apt_revalidate.os.geteuid',return_value=0),patch('protec.apt_revalidate.platform.system',return_value='Linux'),patch('protec.apt_revalidate.status_digest',return_value='a'*64)]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def resign(self):self.plan['plan_sha256']=inventory_digest({k:v for k,v in self.plan.items() if k!='plan_sha256'})

    def test_holds_lock_until_caller_exits_without_committing(self):
        with locked_plan(self.plan,self.device) as cache:
            self.assertIs(cache,self.cache);self.assertTrue(self.locked);self.assertFalse(self.closed)
        self.assertFalse(self.locked);self.assertTrue(self.closed);self.assertFalse(self.committed)

    def test_changed_artifacts_refuse_and_release_lock(self):
        self.candidate.record['SHA256']='b'*64
        with self.assertRaisesRegex(ValueError,'artifacts differ'):
            with locked_plan(self.plan,self.device):self.fail('Unverified plan escaped')
        self.assertFalse(self.locked);self.assertTrue(self.closed);self.assertFalse(self.committed)

    def test_changed_state_and_solver_changes_refuse(self):
        with patch('protec.apt_revalidate.status_digest',return_value='b'*64):
            with self.assertRaisesRegex(ValueError,'state changed'):
                with locked_plan(self.plan,self.device):self.fail('Drift allowed')
        self.package.installed=SimpleNamespace(version='0.9')
        with self.assertRaisesRegex(ValueError,'changes differ'):
            with locked_plan(self.plan,self.device):self.fail('Changed plan allowed')

    def test_old_preview_and_unprivileged_revalidation_refused(self):
        old=plan_for(self.device,self.request)
        with self.assertRaisesRegex(ValueError,'version 2'):
            with locked_plan(old,self.device):self.fail('Unbound artifacts allowed')
        with patch('protec.apt_revalidate.os.geteuid',return_value=1000):
            with self.assertRaisesRegex(ValueError,'requires root'):
                with locked_plan(self.plan,self.device):self.fail('Unprivileged path allowed')
