import sqlite3
import tempfile
import unittest
from pathlib import Path
from protec.database import copy_database
from protec.server import Store
from protec.agent import inventory

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'live.db'
        self.store = Store(self.source)
    def tearDown(self):
        self.temp.cleanup()
    def test_backup_and_restore_preserve_device_auth_and_jobs(self):
        device = self.store.enroll(self.store.enrollment()['token'],inventory())
        self.store.queue(device['id'])
        backup = copy_database(self.source,self.root/'backup.db')
        restore = copy_database(backup,self.root/'restored.db')
        recovered = Store(restore)
        self.assertEqual(recovered.identify(device['credential']),device['id'])
        self.assertEqual(recovered.snapshot()['pending'],1)
        self.assertEqual(len(recovered.snapshot()['audit']),3)
        self.assertEqual(restore.stat().st_mode & 0o777,0o600)
    def test_existing_file_and_symlink_are_never_replaced(self):
        destination = self.root/'existing'
        destination.write_text('keep')
        for target in (destination,self.source):
            with self.assertRaises(ValueError):
                copy_database(self.source,target)
        link = self.root/'link'
        link.symlink_to(self.root/'missing')
        with self.assertRaises(ValueError):
            copy_database(self.source,link)
        self.assertEqual(destination.read_text(),'keep')
    def test_invalid_and_newer_sources_do_not_leave_backup(self):
        invalid = self.root/'invalid.db'
        invalid.write_text('not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            copy_database(invalid,self.root/'output.db')
        self.assertFalse((self.root/'output.db').exists())
        with self.store.connect() as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaises(ValueError):
            copy_database(self.source,self.root/'output.db')
        self.assertFalse((self.root/'output.db').exists())
        self.assertEqual(list(self.root.glob('.protec-backup-*')),[])
    def test_backup_includes_committed_wal_content(self):
        connection = sqlite3.connect(self.source)
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute("INSERT INTO audit(time,actor,action,target) VALUES (1,'test','wal.commit','device')")
            connection.commit()
            backup = copy_database(self.source,self.root/'wal-backup.db')
            self.assertEqual(Store(backup).snapshot()['audit'][0]['action'],'wal.commit')
        finally:
            connection.close()

if __name__=='__main__':
    unittest.main()
