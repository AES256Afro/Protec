import concurrent.futures
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from protec.server import Store, make_server
from protec.agent import inventory, cycle, validate_server

class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'test.db')
    def tearDown(self):
        self.temp.cleanup()
    def device(self):
        return self.store.enroll(self.store.enrollment()['token'],inventory())
    def test_enrollment_is_atomic_and_single_use(self):
        token = self.store.enrollment()['token']
        def attempt(_):
            try:
                return self.store.enroll(token,inventory())
            except PermissionError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(attempt,range(8)))
        self.assertEqual(sum(bool(r) for r in results),1)
    def test_expired_token_rejected(self):
        token = self.store.enrollment()['token']
        with self.store.connect() as db:
            db.execute('UPDATE enrollments SET expires=0')
        with self.assertRaises(PermissionError):
            self.store.enroll(token,inventory())
    def test_credentials_hashed_and_excluded_from_dashboard(self):
        device = self.device()
        self.assertEqual(self.store.identify(device['credential']),device['id'])
        self.assertNotIn(device['credential'],json.dumps(self.store.snapshot()))
        self.assertNotIn(device['credential'],Path(self.store.path).read_bytes().decode(errors='ignore'))
    def test_job_ownership_leases_and_revocation(self):
        one,two = self.device(),self.device()
        job = self.store.queue(one['id'])['id']
        self.assertEqual(self.store.heartbeat(two['id'],inventory())['jobs'],[])
        self.assertEqual(self.store.heartbeat(one['id'],inventory())['jobs'][0]['id'],job)
        self.assertEqual(self.store.heartbeat(one['id'],inventory())['jobs'],[])
        with self.assertRaises(ValueError):
            self.store.complete(two['id'],job)
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET lease=0')
        self.assertEqual(len(self.store.heartbeat(one['id'],inventory())['jobs']),1)
        self.store.revoke(one['id'])
        with self.assertRaises(PermissionError):
            self.store.identify(one['credential'])
        with self.assertRaises(PermissionError):
            self.store.heartbeat(one['id'],inventory())
        with self.assertRaises(ValueError):
            self.store.complete(one['id'],job)
        self.assertEqual(self.store.snapshot()['jobs'][0]['status'],'cancelled')
    def test_duplicate_jobs_rejected(self):
        device = self.device()
        self.store.queue(device['id'])
        with self.assertRaises(ValueError):
            self.store.queue(device['id'])
    def test_remote_http_rejected(self):
        with self.assertRaises(ValueError):
            validate_server('http://example.com')
        with self.assertRaises(ValueError):
            validate_server('https://example.com/path')
        self.assertEqual(validate_server('https://example.com/'),'https://example.com')

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.temp.name)/'http.db','a'*40,0)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()
    def request(self,path,token=None,body=None,origin=None):
        headers = {'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        if origin: headers['Origin']=origin
        req = Request(self.url+path,None if body is None else json.dumps(body).encode(),headers)
        try:
            with urlopen(req) as response:
                return response.status,json.load(response)
        except HTTPError as error:
            with error:
                return error.code,json.load(error)
    def test_real_agent_cycle_and_role_separation(self):
        self.assertEqual(self.request('/api/dashboard')[0],401)
        code,data = self.request('/api/enrollments','a'*40,{})
        self.assertEqual(code,200)
        code,device = self.request('/api/enroll',data['token'],{'inventory':inventory()})
        self.assertEqual(code,200)
        self.assertEqual(self.request('/api/dashboard',device['credential'])[0],401)
        self.assertEqual(self.request('/api/jobs',device['credential'],{'device':device['id']})[0],401)
        self.assertEqual(self.request('/api/heartbeat','a'*40,{'inventory':inventory()})[0],401)
        self.request('/api/jobs','a'*40,{'device':device['id']})
        self.assertEqual(cycle({**device,'server':self.url}),1)
        dashboard = self.request('/api/dashboard','a'*40)[1]
        self.assertEqual(dashboard['jobs'][0]['status'],'completed')
        self.assertEqual(len(dashboard['devices']),1)
    def test_cross_origin_and_invalid_inventory_rejected(self):
        self.assertEqual(self.request('/api/enrollments','a'*40,{},'https://evil.example')[0],401)
        token = self.request('/api/enrollments','a'*40,{})[1]['token']
        self.assertEqual(self.request('/api/enroll',token,{'inventory':{}})[0],400)
        self.assertEqual(self.request('/api/enroll',token,{'inventory':inventory()})[0],200)

if __name__=='__main__':
    unittest.main()
