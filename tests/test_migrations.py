import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from protec.agent import inventory
from protec.database import copy_database
from protec.migrations import TABLES, migrate, validate_schema
from protec.server import Store

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'legacy.db'
    def tearDown(self):
        self.temp.cleanup()
    def legacy(self):
        connection = sqlite3.connect(self.path)
        for table, definition in TABLES.items():
            connection.execute(f'CREATE TABLE {table} ({definition})')
        connection.commit()
        return connection
    def test_legacy_upgrade_preserves_enrollment_and_is_repeatable(self):
        connection = self.legacy()
        connection.close()
        # Write legacy records without running the new startup migration.
        with patch('protec.server.migrate'):
            old = Store(self.path)
        device = old.enroll(old.enrollment()['token'],inventory())
        old.queue(device['id'])
        copy_database(self.path,Path(self.temp.name)/'before.db')
        for _ in range(2):
            upgraded = Store(self.path)
            self.assertEqual(upgraded.identify(device['credential']),device['id'])
            self.assertEqual(upgraded.snapshot()['pending'],1)
            with upgraded.connect() as db:
                self.assertEqual(validate_schema(db),2)
    def test_future_database_refused_without_creating_tables(self):
        connection = sqlite3.connect(self.path)
        connection.execute('PRAGMA user_version=3')
        connection.close()
        with self.assertRaises(ValueError):
            Store(self.path)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(),[])
        finally:
            connection.close()
    def test_incomplete_schema_refused_without_repair_or_version_bump(self):
        connection = sqlite3.connect(self.path)
        connection.execute('CREATE TABLE devices(id TEXT)')
        connection.close()
        with self.assertRaises(ValueError):
            Store(self.path)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('devices',)])
        finally:
            connection.close()
    def test_failed_upgrade_rolls_back_indexes_and_version(self):
        connection = self.legacy()
        connection.execute('CREATE TABLE jobs_created(id TEXT)')
        connection.commit()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                with connection:
                    migrate(connection)
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],0)
            indexes = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")]
            self.assertNotIn('jobs_device_status',indexes)
        finally:
            connection.close()

if __name__=='__main__':
    unittest.main()
