"""Credential handover failure, isolation, expiry and transaction regression tests."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from test_identity import IdentityTests as Harness
from protec import identity


class RotationTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    issue=Harness.issue

    def test_handover_preserves_authority_and_finishes(self):
        source=self.issue('operator')
        code,new=self.request('/api/credentials/rotate',self.root,{'id':source['id'],'role':'administrator','hours':720})
        self.assertEqual(code,200)
        self.assertEqual(new['role'],'operator')
        self.assertEqual(new['expires'],source['expires'])
        for token in (source['token'],new['token']):
            self.assertEqual(self.request('/api/dashboard',token)[0],200)
            self.assertEqual(self.request('/api/enrollments',token,{})[0],403)
        self.assertEqual(self.request('/api/credentials/rotation/finish',self.root,{'id':source['id']})[0],200)
        self.assertEqual(self.request('/api/dashboard',source['token'])[0],401)
        self.assertEqual(self.request('/api/dashboard',new['token'])[0],200)
        self.assertEqual(self.request('/api/credentials/rotate',self.root,{'id':new['id']})[0],200)


    def test_lost_response_cancel_then_retry(self):
        source=self.issue('administrator')
        new=self.request('/api/credentials/rotate',source['token'],{'id':source['id']})[1]
        records=self.request('/api/credentials',source['token'])[1]['credentials']
        old=next(row for row in records if row['id']==source['id'])
        self.assertEqual(old['replacement_id'],new['id'])
        self.assertEqual(old['status'],'rotating')
        self.assertEqual(self.request('/api/credentials/rotate',source['token'],{'id':source['id']})[0],400)
        self.assertEqual(self.request('/api/credentials/rotation/cancel',source['token'],{'id':source['id']})[0],200)
        self.assertEqual(self.request('/api/dashboard',new['token'])[0],401)
        self.assertEqual(self.request('/api/dashboard',source['token'])[0],200)
        retry=self.request('/api/credentials/rotate',source['token'],{'id':source['id']})[1]
        self.assertNotEqual(retry['id'],new['id'])
        self.assertEqual(retry['expires'],source['expires'])
        self.assertEqual(self.request('/api/credentials/rotation/finish',retry['token'],{'id':source['id']})[0],200)
        listing=self.request('/api/credentials',self.root)[1]
        audit=self.request('/api/history?kind=audit',self.root)[1]
        for secret in (new['token'],retry['token']):
            self.assertNotIn(secret,json.dumps([listing,audit]))
            self.assertNotIn(secret,Path(self.server.store.path).read_bytes().decode(errors='ignore'))
        self.assertTrue(any(row['action']=='credential.rotation_cancelled' for row in audit['items']))


    def test_deadline_cannot_restore_old_access(self):
        source=identity.issue(self.server.store,'Reader','viewer',1,'owner')
        with patch('protec.identity.time.time',return_value=source['expires']-100):
            new=identity.rotate(self.server.store,source['id'],'owner')
        self.assertEqual(new['rotation_deadline'],source['expires'])
        with patch('protec.identity.time.time',return_value=new['rotation_deadline']):
            for token in (source['token'],new['token']):
                with self.assertRaises(PermissionError):
                    identity.authenticate(self.server.store,self.root,token)
            with self.assertRaises(ValueError):
                identity.resolve_rotation(self.server.store,source['id'],'owner',cancel=True)
        other=self.issue('viewer')
        new=identity.rotate(self.server.store,other['id'],'owner')
        with patch('protec.identity.time.time',return_value=new['rotation_deadline']):
            with self.assertRaises(PermissionError):
                identity.authenticate(self.server.store,self.root,other['token'])
            self.assertEqual(identity.authenticate(self.server.store,self.root,new['token'])['id'],new['id'])
            with self.assertRaises(ValueError):
                identity.resolve_rotation(self.server.store,other['id'],'owner',cancel=True)
            identity.resolve_rotation(self.server.store,other['id'],'owner')


    def test_revoke_pending_pair_and_no_nested_rotation(self):
        source=self.issue('viewer')
        new=self.request('/api/credentials/rotate',self.root,{'id':source['id']})[1]
        self.assertEqual(self.request('/api/credentials/rotate',self.root,{'id':new['id']})[0],400)
        self.assertEqual(self.request('/api/credentials/revoke',self.root,{'id':source['id']})[0],200)
        for token in (source['token'],new['token']):
            self.assertEqual(self.request('/api/dashboard',token)[0],401)
        self.assertEqual(self.request('/api/credentials/rotation/cancel',self.root,{'id':source['id']})[0],400)


    def test_unauthorized_and_inactive_sources(self):
        source=self.issue('administrator')
        for role in ('viewer','operator'):
            token=self.issue(role)['token']
            for route in ('rotate','rotation/finish','rotation/cancel'):
                self.assertEqual(self.request('/api/credentials/'+route,token,{'id':source['id']})[0],403)
        for identifier in ('missing','local-administrator'):
            self.assertEqual(self.request('/api/credentials/rotate',self.root,{'id':identifier})[0],400)
        identity.revoke(self.server.store,source['id'],'owner')
        self.assertEqual(self.request('/api/credentials/rotate',self.root,{'id':source['id']})[0],400)
        expired=self.issue('viewer')
        with self.server.store.connect() as db:
            db.execute('UPDATE credentials SET expires=0 WHERE id=?',(expired['id'],))
        self.assertEqual(self.request('/api/credentials/rotate',self.root,{'id':expired['id']})[0],400)


    def test_concurrent_start_and_transaction_failure(self):
        source=self.issue('viewer')
        with patch.object(self.server.store,'audit',side_effect=RuntimeError('write failure')):
            with self.assertRaises(RuntimeError):
                identity.rotate(self.server.store,source['id'],'owner')
        with self.server.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM credentials').fetchone()[0],1)
            self.assertIsNone(db.execute('SELECT replacement_id FROM credentials').fetchone()[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.request('/api/credentials/rotate',self.root,{'id':source['id']}),range(2)))
        self.assertEqual(sorted(code for code,_ in responses),[200,400])
        with self.server.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM credentials').fetchone()[0],2)


    def test_resolution_failure_rolls_back_and_concurrent_finish_cancel_has_one_winner(self):
        source=self.issue('administrator')
        new=identity.rotate(self.server.store,source['id'],'owner')
        with patch.object(self.server.store,'audit',side_effect=RuntimeError('audit write failed')):
            with self.assertRaises(RuntimeError):
                identity.resolve_rotation(self.server.store,source['id'],'owner',cancel=True)
        for token in (source['token'],new['token']):
            self.assertEqual(self.request('/api/dashboard',token)[0],200)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda action:self.request('/api/credentials/rotation/'+action,self.root,{'id':source['id']}),('finish','cancel')))
        self.assertEqual(sorted(code for code,_ in responses),[200,400])
        statuses=[self.request('/api/dashboard',token)[0] for token in (source['token'],new['token'])]
        self.assertEqual(sorted(statuses),[200,401])

    def test_scope_is_preserved_without_new_device_authority(self):
        enrollment=self.server.store.enrollment()['token']
        from protec.agent import inventory
        device=self.server.store.enroll(enrollment,inventory())
        source=identity.issue(self.server.store,'Scoped','operator',1,'owner',[device['id']])
        new=identity.rotate(self.server.store,source['id'],'owner')
        principal=identity.authenticate(self.server.store,self.root,new['token'])
        self.assertEqual(principal['device_ids'],[device['id']])
        self.assertNotIn('health.read',principal['permissions'])
        with self.assertRaises(identity.Forbidden):
            identity.require(principal,'jobs.write','f'*24)


del Harness
