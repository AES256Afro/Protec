import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from protec.package_worker import execute
from protec.job_signatures import generate


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)/'worker';self.directory.mkdir(mode=0o700)
        self.server='https://fixture.invalid';generate(self.directory/'keys',self.server)
        (self.directory/'job-trust.json').write_bytes((self.directory/'keys/job-trust.json').read_bytes())
        (self.directory/'job-trust.json').chmod(0o600)
        self.config={'version':1,'server':self.server,'device':'a'*24}
        self.write('worker.json',self.config)
        self.write('package-policy.json',{'version':1,'packages':['fixture'],'allow_remove':False})
        self.write('request.json',{'job':{'fixture':True},'proof':{'fixture':True}})
        # Tests retain actual file ownership checks; only the explicit root gate
        # is patched. No native package operation runs on the development host.

    def write(self,name,value):
        file=self.directory/name;file.write_text(json.dumps(value));file.chmod(0o600)

    def run_local(self):
        # Patch loaders independently so file security still checks the real UID.
        from protec import package_worker
        class Identity:
            @staticmethod
            def geteuid():return 0
            open=staticmethod(os.open)
            close=staticmethod(os.close)
            O_RDONLY=os.O_RDONLY
            O_NOFOLLOW=os.O_NOFOLLOW
        with patch.object(package_worker,'os',Identity),patch('protec.package_changes.geteuid',return_value=0):
            return execute(self.directory)

    def test_worker_uses_only_local_identity_policy_and_journal(self):
        with patch('protec.package_worker.run_change',return_value={'outcome':'succeeded'}) as run:
            self.assertEqual(self.run_local(),{'outcome':'succeeded'})
        args=run.call_args.args
        self.assertEqual(args[2],self.config['device'])
        self.assertEqual(args[4]['packages'],['fixture'])
        self.assertEqual(args[5].directory,self.directory/'receipts')

    def test_request_cannot_override_local_policy(self):
        self.write('request.json',{'job':{},'proof':{},'policy':{'allow_remove':True}})
        with patch('protec.package_worker.run_change') as run,self.assertRaises(ValueError):self.run_local()
        run.assert_not_called()

    def test_insecure_or_symlink_request_is_refused(self):
        request=self.directory/'request.json';request.chmod(0o644)
        with self.assertRaises(ValueError):self.run_local()
        request.unlink();request.symlink_to(self.directory/'worker.json')
        with self.assertRaises(OSError):self.run_local()

    def test_config_rejects_arbitrary_command_paths(self):
        self.write('worker.json',{**self.config,'command':'/bin/sh'})
        with self.assertRaises(ValueError):self.run_local()

    def test_existing_worker_lock_prevents_execution(self):
        import fcntl
        with (self.directory/'worker.json').open() as file:
            fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch('protec.package_worker.run_change') as run,self.assertRaises(BlockingIOError):self.run_local()
        run.assert_not_called()

    def test_nonroot_is_rejected_before_loading_any_input(self):
        with patch('protec.package_worker.os.geteuid',return_value=1000),patch('protec.package_worker.protected_document') as read,self.assertRaises(ValueError):execute(self.directory)
        read.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def test_recovery_reads_durable_result_without_execution_inputs(self):
        from test_package_changes import ChangeCoreTests
        from protec.package_worker import recover
        case=ChangeCoreTests();case.setUp();self.addCleanup(case.doCleanups)
        result=case.execute()
        directory=case.journal.directory.parent
        config=directory/'worker.json'
        config.write_text(json.dumps({'version':1,'server':case.origin,'device':case.device}));config.chmod(0o600)
        case.journal.directory.rename(directory/'receipts')
        with patch('protec.package_worker.identity',return_value=(directory,case.origin,case.device)),patch('protec.package_worker.run_change') as run,patch('protec.package_worker.load_policy') as policy:
            record=recover(case.job['id'],directory)
        self.assertEqual(record['result'],result)
        self.assertEqual(record['state'],'completion_pending')
        self.assertFalse(record['requires_inspection'])
        run.assert_not_called();policy.assert_not_called()

    def test_started_attempt_is_reported_for_inspection_without_retry(self):
        from test_package_changes import ChangeCoreTests
        from protec.package_worker import recover
        case=ChangeCoreTests();case.setUp();self.addCleanup(case.doCleanups)
        case.journal.begin(case.job)
        directory=case.journal.directory.parent
        case.journal.directory.rename(directory/'receipts')
        with patch('protec.package_worker.identity',return_value=(directory,case.origin,case.device)):
            record=recover(case.job['id'],directory)
        self.assertEqual(record['state'],'started');self.assertIsNone(record['result']);self.assertTrue(record['requires_inspection'])
        self.assertEqual(case.commits,0)

    def test_missing_journal_does_not_create_one(self):
        from protec.package_worker import recover
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            with patch('protec.package_worker.identity',return_value=(directory,'https://fixture.invalid','a'*24)),self.assertRaises(ValueError):recover('b'*24,directory)
            self.assertFalse((directory/'receipts').exists())

    def test_invalid_identifier_refused_before_reading_identity(self):
        from protec.package_worker import recover
        with patch('protec.package_worker.identity') as identity,self.assertRaises(ValueError):recover('../request.json')
        identity.assert_not_called()
