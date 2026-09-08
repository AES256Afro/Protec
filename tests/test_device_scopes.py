import json
import unittest
from test_identity import IdentityTests as Harness
from protec.agent import inventory


class DeviceScopeTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    def device(self,name):
        token=self.server.store.enrollment()['token']
        return self.server.store.enroll(token,{**inventory(),'hostname':name})

    def scoped(self,role,devices):
        code,result=self.request('/api/credentials',self.root,{'name':'Selected devices','role':role,'hours':24,'device_ids':devices})
        self.assertEqual(code,200)
        return result

    def test_scope_filters_every_inventory_and_job_surface_before_paging(self):
        allowed=self.device('allowed')
        hidden=self.device('confidential-host')
        for _ in range(4):
            job=self.server.store.queue(hidden['id'])
            self.server.store.heartbeat(hidden['id'],inventory())
            self.server.store.complete(hidden['id'],job['id'])
        self.server.store.queue(allowed['id'])
        token=self.scoped('operator',[allowed['id']])['token']
        code,data=self.request('/api/dashboard',token)
        self.assertEqual(code,200)
        self.assertEqual([d['id'] for d in data['devices']],[allowed['id']])
        self.assertEqual({j['device'] for j in data['jobs']},{allowed['id']})
        self.assertEqual(data['fleet']['records'],1)
        self.assertEqual(data['pending'],1)
        self.assertEqual(data['audit'],[])
        self.assertNotIn(hidden['id'],json.dumps(data))
        for kind in ('devices','jobs'):
            data=self.request('/api/history?kind='+kind+'&limit=1',token)[1]
            self.assertEqual(len(data['items']),1)
            self.assertIsNone(data['next_cursor'])
            self.assertNotIn(hidden['id'],json.dumps(data))
        for path in ('/api/health','/api/enrollments','/api/credentials','/api/history?kind=credentials','/api/history?kind=audit'):
            self.assertEqual(self.request(path,token)[0],403)

    def test_targets_are_enforced_before_job_creation(self):
        allowed=self.device('allowed');hidden=self.device('hidden')
        operator=self.scoped('operator',[allowed['id']])['token']
        viewer=self.scoped('viewer',[allowed['id']])['token']
        for target in (hidden['id'],'f'*24,''):
            self.assertEqual(self.request('/api/jobs',operator,{'device':target})[0],403)
        self.assertEqual(self.request('/api/jobs',viewer,{'device':allowed['id']})[0],403)
        self.assertEqual(self.request('/api/jobs',operator,{'device':allowed['id']})[0],200)
        self.assertEqual(len(self.server.store.snapshot()['jobs']),1)
        self.assertEqual(self.request('/api/credentials',operator,{'name':'escalate','role':'administrator','hours':1})[0],403)

    def test_issue_scope_validation_and_secret_free_metadata(self):
        device=self.device('allowed')
        for scope in ([],[device['id'],device['id']],['f'*24],['invalid'],{},True,[None]):
            self.assertEqual(self.request('/api/credentials',self.root,{'name':'test','role':'viewer','hours':1,'device_ids':scope})[0],400)
        self.assertEqual(self.request('/api/credentials',self.root,{'name':'test','role':'administrator','hours':1,'device_ids':[device['id']]})[0],400)
        issued=self.scoped('viewer',[device['id']])
        rows=self.request('/api/credentials',self.root)[1]['credentials']
        self.assertEqual(rows[0]['device_ids'],[device['id']])
        self.assertNotIn(issued['token'],json.dumps(rows))
        self.server.store.revoke(device['id'])
        self.assertEqual(self.request('/api/credentials',self.root,{'name':'revoked','role':'viewer','hours':1,'device_ids':[device['id']]})[0],400)
        self.assertEqual(self.request('/api/dashboard',issued['token'])[1]['fleet']['active'],0)

    def test_corrupt_scope_fails_closed(self):
        device=self.device('allowed')
        issued=self.scoped('viewer',[device['id']])
        for invalid in ('[]','null','{}','["f"]','bad json'):
            with self.server.store.connect() as db:
                db.execute('UPDATE credentials SET device_ids=? WHERE id=?',(invalid,issued['id']))
            self.assertEqual(self.request('/api/dashboard',issued['token'])[0],401)

del Harness
