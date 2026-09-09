import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from protec.agent import inventory
from protec.database import copy_database
from protec.migrations import TABLES, SCHEMA_VERSION, CREDENTIAL_SCHEMA, migrate, validate_schema
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
        with old.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',('legacy-job',device['id'],'refresh_inventory','queued',1,0,None))
        copy_database(self.path,Path(self.temp.name)/'before.db')
        for _ in range(2):
            upgraded = Store(self.path)
            self.assertEqual(upgraded.identify(device['credential']),device['id'])
            self.assertEqual(upgraded.snapshot()['pending'],1)
            with upgraded.connect() as db:
                self.assertEqual(validate_schema(db),SCHEMA_VERSION)
    def test_schema_two_upgrade_preserves_existing_fleet_credentials(self):
        from protec.identity import authenticate, token_hash
        connection=self.legacy()
        connection.execute(f'CREATE TABLE credentials ({CREDENTIAL_SCHEMA})')
        connection.execute("INSERT INTO credentials VALUES (?,?,?,?,?,?,?,?)",('reader',token_hash('b'*43),'Reader','viewer',1,9999999999,0,'owner'))
        connection.execute('PRAGMA user_version=2')
        connection.commit()
        connection.close()
        copy_database(self.path,Path(self.temp.name)/'before-v3.db')
        upgraded=Store(self.path)
        principal=authenticate(upgraded,'a'*43,'b'*43)
        self.assertIsNone(principal['device_ids'])
        self.assertEqual(principal['role'],'viewer')
        with upgraded.connect() as db:
            self.assertEqual(validate_schema(db),SCHEMA_VERSION)

    def test_schema_three_upgrade_preserves_scoped_credentials_and_is_repeatable(self):
        from protec.identity import authenticate, token_hash
        connection=self.legacy()
        connection.execute(f'CREATE TABLE credentials ({CREDENTIAL_SCHEMA}, device_ids TEXT)')
        connection.execute('INSERT INTO credentials VALUES (?,?,?,?,?,?,?,?,?)',('reader',token_hash('c'*43),'Scoped','operator',1,9999999999,0,'owner','["'+'d'*24+'"]'))
        connection.execute('PRAGMA user_version=3')
        connection.commit()
        connection.close()
        copy_database(self.path,Path(self.temp.name)/'before-v4.db')
        for _ in range(2):
            upgraded=Store(self.path)
            principal=authenticate(upgraded,'a'*43,'c'*43)
            self.assertEqual(principal['device_ids'],['d'*24])
            with upgraded.connect() as db:
                row=db.execute('SELECT replacement_id,rotation_deadline FROM credentials').fetchone()
                self.assertEqual(tuple(row),(None,None))
                self.assertEqual(validate_schema(db),SCHEMA_VERSION)

    def test_schema_four_upgrade_preserves_legacy_running_jobs(self):
        import protec.migrations as migrations
        connection=self.legacy()
        connection.execute(f'CREATE TABLE credentials ({CREDENTIAL_SCHEMA}, device_ids TEXT, replacement_id TEXT, rotation_deadline REAL)')
        connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',('j','d','refresh_inventory','running',1,9999999999,None))
        connection.execute('PRAGMA user_version=4')
        connection.commit();connection.close()
        upgraded=Store(self.path)
        with upgraded.connect() as db:
            row=db.execute('SELECT status,lease,contract_version,attempt,receipt,lease_hash FROM jobs').fetchone()
            self.assertEqual(tuple(row),('running',9999999999,0,0,None,None))
            self.assertEqual(migrations.validate_schema(db),SCHEMA_VERSION)

    def test_schema_five_upgrade_preserves_jobs_and_defaults_to_immediate_delivery(self):
        store=Store(self.path)
        device=store.enroll(store.enrollment()['token'],inventory());store.queue(device['id'])
        with store.connect() as db:
            db.execute('ALTER TABLE jobs DROP COLUMN not_before');db.execute('ALTER TABLE jobs DROP COLUMN not_after')
            db.execute('PRAGMA user_version=5')
            before=[tuple(row) for row in db.execute('SELECT * FROM jobs')]
        for _ in range(2):
            store=Store(self.path)
            with store.connect() as db:
                rows=list(db.execute('SELECT * FROM jobs'))
                self.assertEqual([tuple(row)[:-2] for row in rows],before)
                self.assertEqual(tuple(rows[0])[-2:],(None,None))
                self.assertEqual(validate_schema(db),SCHEMA_VERSION)
        self.assertEqual(len(store.heartbeat(device['id'],inventory(),1)['jobs']),1)

    def test_failed_schema_six_upgrade_rolls_back_new_column(self):
        store=Store(self.path)
        with store.connect() as db:
            db.execute('ALTER TABLE jobs DROP COLUMN not_before')
            db.execute('PRAGMA user_version=5')
        with self.assertRaises(sqlite3.OperationalError):Store(self.path)
        with store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
            self.assertNotIn('not_before',{row[1] for row in db.execute('PRAGMA table_info(jobs)')})

    def test_future_database_refused_without_creating_tables(self):
        connection = sqlite3.connect(self.path)
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION+1}')
        connection.close()
        with self.assertRaises(ValueError):
            Store(self.path)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION+1)
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
