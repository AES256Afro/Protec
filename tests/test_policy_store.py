import concurrent.futures
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from protec.server import Store
from protec.policy_store import save, workspace
from protec.migrations import SCHEMA_VERSION


class PolicyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db')
        self.ids=['a'*24,'b'*24]
        report={'scope':'Installed Debian packages','message':'Test inventory','manager':'dpkg','status':'complete','collected_at':time.time(),'total':1,'truncated':False,'items':[{'name':'git','version':'1'}]}
        with self.store.connect() as db:
            for i in self.ids:
                db.execute('INSERT INTO devices VALUES (?,?,?,?,0)',(i,i,json.dumps({'hostname':i,'packages':report}),time.time()))
        self.group=save(self.store,'groups',{'name':'Linux','members':self.ids},'admin')
        self.rule={'kind':'package_present','manager':'dpkg','package':'git','max_age_seconds':3600}
        self.policy=save(self.store,'policies',{'name':'Git','group_id':self.group['id'],'rule':self.rule,'enabled':True},'admin')

    def update_body(self,obj):
        return {k:v for k,v in obj.items() if k!='created'}

    def test_scope_filters_before_evaluation_and_does_not_expose_other_ids(self):
        for collection in ('groups','policies','compliance'):
            result=workspace(self.store,[self.ids[0]],collection)
            self.assertNotIn(self.ids[1],json.dumps(result))
        results=workspace(self.store,[self.ids[0]])['results']
        self.assertEqual(len(results),1);self.assertEqual(results[0]['status'],'compliant')
        self.assertEqual(workspace(self.store,[], 'policies'),{'policies':[]})
        self.assertEqual(workspace(self.store,[])['results'],[])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_disabled_policy_and_empty_group_are_valid(self):
        body=self.update_body(self.policy);body['enabled']=False
        save(self.store,'policies',body,'admin')
        self.assertEqual(workspace(self.store)['results'],[])
        body=self.update_body(self.group);body['members']=[]
        save(self.store,'groups',body,'admin')
        self.assertEqual(workspace(self.store,None,'groups')['groups'][0]['members'],[])

    def test_revocation_retains_unknown_assignment(self):
        with self.store.connect() as db:db.execute('UPDATE devices SET revoked=1 WHERE id=?',(self.ids[0],))
        results=workspace(self.store)['results']
        self.assertEqual(results[0]['status'],'unknown')
        self.assertEqual(len(results),2)
        with self.assertRaises(ValueError):save(self.store,'groups',self.update_body(self.group),'admin')

    def test_racing_edits_preserve_immutable_versions(self):
        body=self.update_body(self.policy);body['name']='Updated'
        def attempt(_):
            try:return save(self.store,'policies',body,'admin')
            except ValueError:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(x is not None for x in pool.map(attempt,range(4))),1)
        with self.store.connect() as db:
            rows=db.execute("SELECT payload FROM policy_objects WHERE kind='policies' ORDER BY revision").fetchall()
            self.assertEqual([json.loads(r[0])['name'] for r in rows],['Git','Updated'])
        self.assertEqual(workspace(self.store)['results'][0]['policy_revision'],2)

    def test_audit_failure_rolls_back_revision(self):
        with patch.object(self.store,'audit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):save(self.store,'policies',self.update_body(self.policy),'admin')
        self.assertEqual(workspace(self.store,None,'policies')['policies'][0]['revision'],1)

    def test_rejects_invalid_members_and_rule_fields(self):
        for members in [None,{},[self.ids[0]]*2,['c'*24],[1]]:
            with self.assertRaises(ValueError):save(self.store,'groups',{'name':'X','members':members},'admin')
        for change in [{'enabled':1},{'rule':{}},{'group_id':'absent'},{'unexpected':True},{'name':'\n'}]:
            with self.assertRaises(ValueError):save(self.store,'policies',{**self.update_body(self.policy),**change},'admin')

    def test_schema_six_upgrade_preserves_existing_rows(self):
        with self.store.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM devices')]
            db.execute('ALTER TABLE jobs DROP COLUMN payload');db.execute('ALTER TABLE jobs DROP COLUMN preview')
            db.execute('DROP TABLE policy_objects');db.execute('PRAGMA user_version=6')
        upgraded=Store(self.store.path)
        with upgraded.connect() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM devices')],before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
        self.assertEqual(workspace(upgraded)['results'],[])

    def test_compliance_pages_are_scoped_and_do_not_skip_pairs(self):
        first=workspace(self.store,limit=1)
        second=workspace(self.store,cursor=first['next_cursor'],limit=1)
        self.assertEqual(first['total'],2)
        self.assertIsNone(second['next_cursor'])
        self.assertEqual([first['results'][0]['device_id'],second['results'][0]['device_id']],self.ids)
        self.assertEqual(workspace(self.store,[self.ids[0]],limit=1)['total'],1)
        for args in ({'limit':True},{'limit':101},{'cursor':'bad'}):
            with self.assertRaises(ValueError):workspace(self.store,**args)
