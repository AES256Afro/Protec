import tempfile
import time
import unittest
from pathlib import Path
from protec.server import Store
from protec.history import page, health
from protec.maintenance import retention
from protec.agent import inventory

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'test.db')
    def tearDown(self):
        self.temp.cleanup()
    def test_pages_do_not_repeat_when_new_events_arrive(self):
        with self.store.connect() as db:
            for i in range(125):
                self.store.audit(db,'test','event',str(i))
        first=page(self.store,'audit',50)
        with self.store.connect() as db:
            self.store.audit(db,'test','new','new')
        second=page(self.store,'audit',50,first['next_cursor'])
        third=page(self.store,'audit',50,second['next_cursor'])
        ids=[r['id'] for r in first['items']+second['items']+third['items']]
        self.assertEqual(len(ids),125)
        self.assertEqual(len(set(ids)),125)
        self.assertIsNone(third['next_cursor'])
    def test_history_projections_exclude_secrets(self):
        token=self.store.enrollment()['token']
        device=self.store.enroll(token,inventory())
        import json
        for kind in ('devices','enrollments'):
            output=json.dumps(page(self.store,kind))
            self.assertNotIn(token,output)
            self.assertNotIn(device['credential'],output)
        for size in (0,101,-1):
            with self.assertRaises(ValueError):
                page(self.store,'audit',size)
        with self.assertRaises(ValueError):
            page(self.store,'audit',50,-2)
        with self.assertRaises(ValueError):
            page(self.store,'sqlite_master')
    def test_counts_cover_more_than_dashboard_page(self):
        with self.store.connect() as db:
            for i in range(125):
                db.execute('INSERT INTO devices VALUES (?,?,?,?,0)',(str(i),'hash'+str(i),'{}',time.time()))
        snapshot=self.store.snapshot()
        self.assertEqual(len(snapshot['devices']),100)
        self.assertEqual(snapshot['fleet'],{'records':125,'active':125,'online':125})
        self.assertEqual(health(self.store,time.monotonic())['counts']['devices'],125)
    def test_retention_preserves_active_work_devices_and_audit(self):
        device=self.store.enroll(self.store.enrollment()['token'],inventory())
        now=time.time()
        old=now-100*86400
        with self.store.connect() as db:
            db.execute('UPDATE enrollments SET expires=?',(old,))
            for identifier,status in [('old','completed'),('pending','queued'),('running','running'),('recent-result','completed')]:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',(identifier,device['id'],'refresh_inventory',status,old,0,'test'))
            self.store.audit(db,device['id'],'inventory.completed','recent-result')
        before=self.store.snapshot()
        preview=retention(self.store,30,now=now)
        self.assertEqual(preview['eligible'],{'jobs':1,'enrollments':1})
        self.assertEqual(len(self.store.snapshot()['jobs']),4)
        backup=self.root/'backup.db'
        applied=retention(self.store,30,backup,now)
        self.assertEqual(applied['eligible'],preview['eligible'])
        self.assertEqual({j['id'] for j in self.store.snapshot()['jobs']},{'pending','running','recent-result'})
        self.assertEqual(len(self.store.snapshot()['audit']),len(before['audit'])+1)
        self.assertEqual(self.store.identify(device['credential']),device['id'])
        self.assertEqual(len(Store(backup).snapshot()['jobs']),4)
    def test_retention_failed_backup_deletes_nothing(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO jobs VALUES ('old','device','refresh_inventory','completed',0,0,'done')")
        existing=self.root/'keep'
        existing.write_text('keep')
        with self.assertRaises(ValueError):
            retention(self.store,30,existing)
        self.assertEqual(len(self.store.snapshot()['jobs']),1)
        with self.assertRaises(ValueError):
            retention(self.store,1)

if __name__=='__main__':
    unittest.main()
