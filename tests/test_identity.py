import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from protec.server import make_server
from protec.agent import inventory

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=make_server(Path(self.temp.name)/'test.db','a'*43,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.root='a'*43
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()
    def request(self,path,token,body=None):
        req=Request(self.url+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urlopen(req) as response:
                return response.status,json.load(response)
        except HTTPError as error:
            with error:
                return error.code,json.load(error)
    def issue(self,role):
        code,result=self.request('/api/credentials',self.root,{'name':role+' service','role':role,'hours':24})
        self.assertEqual(code,200)
        return result
    def test_roles_and_audit_attribution(self):
        admin=self.issue('administrator')
        operator=self.issue('operator')
        viewer=self.issue('viewer')
        token=self.request('/api/enrollments',admin['token'],{})[1]['token']
        device=self.request('/api/enroll',token,{'inventory':inventory()})[1]
        for principal in (viewer,operator):
            status,data=self.request('/api/dashboard',principal['token'])
            self.assertEqual(status,200)
            self.assertEqual(data['identity']['id'],principal['id'])
            self.assertEqual(data['audit'],[])
            for path in ('/api/enrollments','/api/credentials','/api/history?kind=audit','/api/history?kind=enrollments','/api/history?kind=credentials'):
                self.assertEqual(self.request(path,principal['token'])[0],403)
            for path,body in (('/api/enrollments',{}),('/api/revoke',{'device':device['id']}),('/api/credentials',{'name':'escalate','role':'administrator','hours':1}),('/api/credentials/revoke',{'id':admin['id']})):
                self.assertEqual(self.request(path,principal['token'],body)[0],403)
            for kind in ('devices','jobs'):
                self.assertEqual(self.request('/api/history?kind='+kind,principal['token'])[0],200)
        self.assertEqual(self.request('/api/jobs',viewer['token'],{'device':device['id']})[0],403)
        self.assertEqual(self.request('/api/jobs',operator['token'],{'device':device['id']})[0],200)
        audit=self.request('/api/dashboard',admin['token'])[1]['audit']
        self.assertEqual(next(e for e in audit if e['action']=='inventory.requested')['actor'],operator['id'])
        self.assertEqual(self.request('/api/heartbeat',operator['token'],{'inventory':inventory()})[0],401)
        self.assertEqual(self.request('/api/credentials',device['credential'])[0],401)
    def test_revocation_expiry_and_no_secret_redisclosure(self):
        issued=self.issue('operator')
        listing=self.request('/api/credentials',self.root)[1]
        self.assertNotIn(issued['token'],json.dumps(listing))
        self.assertNotIn('hash',listing['credentials'][0])
        self.assertNotIn(issued['token'],Path(self.server.store.path).read_bytes().decode(errors='ignore'))
        self.assertEqual(self.request('/api/credentials/revoke',self.root,{'id':issued['id']})[0],200)
        self.assertEqual(self.request('/api/dashboard',issued['token'])[0],401)
        self.assertEqual(self.request('/api/credentials/revoke',self.root,{'id':'local-administrator'})[0],400)
        expired=self.issue('viewer')
        with self.server.store.connect() as db:
            db.execute('UPDATE credentials SET expires=0 WHERE id=?',(expired['id'],))
        self.assertEqual(self.request('/api/dashboard',expired['token'])[0],401)
        self.assertEqual(self.request('/api/dashboard',self.root)[0],200)
    def test_invalid_creation_and_non_ascii_auth_are_rejected(self):
        for change in ({'role':{}},{'role':'root'},{'hours':True},{'hours':0},{'hours':721},{'name':'\nsecret'}):
            self.assertEqual(self.request('/api/credentials',self.root,{'name':'test','role':'viewer','hours':1,**change})[0],400)
        for token in ('é'*43,'x'*43):
            self.assertEqual(self.request('/api/dashboard',token)[0],401)
    def test_metadata_paging_covers_all_credentials(self):
        from protec.identity import issue
        for i in range(55):
            issue(self.server.store,'reader'+str(i),'viewer',1,'test')
        first=self.request('/api/credentials',self.root)[1]
        second=self.request('/api/credentials?cursor='+str(first['next_cursor']),self.root)[1]
        self.assertEqual(len(first['credentials']),50)
        self.assertEqual(len(second['credentials']),5)
        self.assertIsNone(second['next_cursor'])

if __name__=='__main__':
    unittest.main()
