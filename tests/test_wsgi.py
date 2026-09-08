import io
import json
from pathlib import Path
import tempfile
import unittest
from wsgiref.validate import validator
from protec.wsgi import create_app, public_origin


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.token = 'a'*43
        self.app = validator(create_app(self.directory.name,'https://portal.example.com',self.token))

    def request(self,path,method='GET',token=None,origin=None,body=b'{}'):
        env = {'REQUEST_METHOD':method,'PATH_INFO':path,'SCRIPT_NAME':'','QUERY_STRING':'',
               'SERVER_NAME':'localhost','SERVER_PORT':'8765','SERVER_PROTOCOL':'HTTP/1.1',
               'wsgi.version':(1,0),'wsgi.url_scheme':'http','wsgi.input':io.BytesIO(body),
               'wsgi.errors':io.StringIO(),'wsgi.multithread':True,'wsgi.multiprocess':False,
               'wsgi.run_once':False,'HTTP_HOST':'localhost:8765','CONTENT_TYPE':'application/json',
               'CONTENT_LENGTH':str(len(body))}
        if token: env['HTTP_AUTHORIZATION']='Bearer '+token
        if origin: env['HTTP_ORIGIN']=origin
        response={}
        def start(status,headers,exc_info=None): response.update(status=int(status[:3]),headers=dict(headers))
        result=self.app(env,start)
        try: response['body']=b''.join(result)
        finally: result.close()
        return response

    def test_readiness_has_no_inventory_or_credentials(self):
        result=self.request('/healthz')
        self.assertEqual(result['status'],200)
        self.assertEqual(json.loads(result['body']),{'status':'ok'})
        self.assertEqual(self.request('/api/dashboard')['status'],401)

    def test_https_proxy_writes_require_configured_origin(self):
        self.assertEqual(self.request('/api/enrollments','POST',self.token,'https://portal.example.com')['status'],200)
        for origin in ['https://attacker.example','http://localhost:8765']:
            self.assertEqual(self.request('/api/enrollments','POST',self.token,origin)['status'],401)
        self.assertEqual(self.request('/api/enrollments','POST',self.token)['status'],200)

    def test_limits_head_and_methods(self):
        self.assertEqual(self.request('/api/enrollments','POST',self.token,body=b' ' * 262145)['status'],400)
        self.assertEqual(self.request('/','HEAD')['body'],b'')
        self.assertEqual(self.request('/','DELETE')['status'],405)
        self.assertIn('frame-ancestors',self.request('/')['headers']['Content-Security-Policy'])

    def test_storage_survives_app_restart(self):
        self.request('/api/enrollments','POST',self.token)
        self.app=validator(create_app(self.directory.name,'https://portal.example.com',self.token))
        result=self.request('/api/enrollments',token=self.token)
        self.assertEqual(len(json.loads(result['body'])['enrollments']),1)

    def test_generated_token_persists_and_environment_rotation_is_authoritative(self):
        create_app(self.directory.name,'http://localhost:8765')
        path=Path(self.directory.name)/'admin-token'
        token=path.read_text()
        create_app(self.directory.name,'http://localhost:8765')
        self.assertEqual(path.read_text(),token)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.app=validator(create_app(self.directory.name,'https://portal.example.com','b'*43))
        self.assertEqual(self.request('/api/dashboard',token=token)['status'],401)
        self.assertEqual(self.request('/api/dashboard',token='b'*43)['status'],200)

    def test_public_origin_validation(self):
        for value in ['http://example.com','https://user:pw@example.com','https://example.com/path','https://example.com?x=1','https://example.com:99999']:
            with self.assertRaises(ValueError): public_origin(value)
        self.assertEqual(public_origin('https://portal.example.com/'),'https://portal.example.com')
