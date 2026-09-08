"""Cancellation authorization, delivery races and receipt preservation."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from test_control_plane import HTTPTests as Harness
from protec.agent import inventory
from protec import identity, jobs

class CancellationTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    root='a'*40

    def device(self):
        store=self.server.store
        return store.enroll(store.enrollment()['token'],inventory())
    def credential(self,role,scope=None):
        token=identity.issue(self.server.store,'Cancellation test',role,1,'owner',scope)
        principal=identity.authenticate(self.server.store,self.root,token['token'])
        return token,principal
    def completion(self,job):
        return {'version':1,'attempt':job['attempt'],'lease_token':job['lease']['token'],
                'result':{'outcome':'succeeded','inventory_sha256':jobs.inventory_digest(inventory())}}

    def test_queued_cancellation_is_idempotent_audited_and_allows_another_refresh(self):
        device=self.device();token,_=self.credential('operator',[device['id']])
        job=self.server.store.queue(device['id'])['id']
        for duplicate in (False,True):
            status,result=self.request('/api/jobs/cancel',token['token'],{'id':job})
            self.assertEqual(status,200);self.assertEqual(result['duplicate'],duplicate)
        self.assertEqual(self.server.store.heartbeat(device['id'],inventory(),1)['jobs'],[])
        audit=[row for row in self.server.store.snapshot()['audit'] if row['action']=='inventory.cancelled']
        self.assertEqual(len(audit),1);self.assertEqual(audit[0]['actor'],token['id']);self.assertEqual(audit[0]['target'],job)
        self.assertEqual(self.server.store.snapshot()['pending'],0)
        self.assertNotEqual(self.server.store.queue(device['id'])['id'],job)

    def test_real_job_target_controls_scope_even_when_request_spoofs_device(self):
        one,two=self.device(),self.device()
        scoped,_=self.credential('operator',[one['id']])
        viewer,_=self.credential('viewer')
        job=self.server.store.queue(two['id'])['id']
        self.assertEqual(self.request('/api/jobs/cancel',scoped['token'],{'id':job,'device':one['id']})[0],403)
        self.assertEqual(self.request('/api/jobs/cancel',viewer['token'],{'id':job})[0],403)
        self.assertEqual(self.request('/api/jobs/cancel',two['credential'],{'id':job})[0],401)
        self.assertEqual(self.request('/api/jobs/cancel',None,{'id':job})[0],401)
        self.assertEqual(self.request('/api/jobs/cancel',self.root,{'id':'f'*24})[0],400)
        self.assertEqual(self.server.store.snapshot()['jobs'][0]['status'],'queued')
        self.assertEqual(self.request('/api/jobs/cancel',self.root,{'id':job})[0],200)

    def test_running_cancellation_invalidates_both_protocols_and_regular_checkins_continue(self):
        for protocol in (0,1):
            device=self.device();job=self.server.store.queue(device['id'])['id']
            envelope=self.server.store.heartbeat(device['id'],inventory(),protocol)['jobs'][0]
            self.assertEqual(self.request('/api/jobs/cancel',self.root,{'id':job})[0],200)
            body={'job':job,**(self.completion(envelope) if protocol else {})}
            self.assertEqual(self.request('/api/complete',device['credential'],body)[0],400)
            status,result=self.request('/api/heartbeat',device['credential'],{'inventory':inventory(),'job_protocol':protocol})
            self.assertEqual(status,200);self.assertEqual(result['jobs'],[])
            with self.server.store.connect() as db:
                row=db.execute('SELECT lease,lease_hash,receipt FROM jobs WHERE id=?',(job,)).fetchone()
                self.assertEqual(tuple(row),(0,None,None))

    def test_completed_receipts_and_failed_jobs_are_not_rewritten(self):
        device=self.device();job=self.server.store.queue(device['id'])['id']
        envelope=self.server.store.heartbeat(device['id'],inventory(),1)['jobs'][0]
        receipt=self.server.store.complete(device['id'],job,self.completion(envelope))['receipt']
        self.assertEqual(self.request('/api/jobs/cancel',self.root,{'id':job})[0],400)
        self.assertEqual(self.server.store.snapshot()['jobs'][0]['receipt'],receipt)
        another=self.server.store.queue(device['id'])['id']
        with self.server.store.connect() as db:db.execute("UPDATE jobs SET status='failed',result='Existing failure' WHERE id=?",(another,))
        self.assertEqual(self.request('/api/jobs/cancel',self.root,{'id':another})[0],400)
        self.assertEqual(self.server.store.snapshot()['jobs'][0]['result'],'Existing failure')

    def test_audit_failure_rolls_back_cancellation(self):
        device=self.device();job=self.server.store.queue(device['id'])['id']
        envelope=self.server.store.heartbeat(device['id'],inventory(),1)['jobs'][0]
        _,principal=self.credential('operator')
        with patch.object(self.server.store,'audit',side_effect=RuntimeError('test audit failure')):
            with self.assertRaises(RuntimeError):jobs.cancel(self.server.store,job,principal)
        self.assertEqual(self.server.store.snapshot()['jobs'][0]['status'],'running')
        self.server.store.complete(device['id'],job,self.completion(envelope))

    def test_completion_and_cancellation_race_has_one_winner(self):
        device=self.device();job=self.server.store.queue(device['id'])['id']
        envelope=self.server.store.heartbeat(device['id'],inventory(),1)['jobs'][0]
        tasks=[('/api/complete',device['credential'],{'job':job,**self.completion(envelope)}),('/api/jobs/cancel',self.root,{'id':job})]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda args:self.request(*args),tasks))
        self.assertEqual(sorted(code for code,_ in responses),[200,400])
        record=self.server.store.snapshot()['jobs'][0]
        self.assertIn(record['status'],('completed','cancelled'))
        self.assertEqual(record['receipt'] is None,record['status']=='cancelled')
        audit=[row for row in self.server.store.snapshot()['audit'] if row['action'] in ('inventory.completed','inventory.cancelled')]
        self.assertEqual(len(audit),1)

    def test_cancelled_job_cannot_be_leased_after_restart(self):
        device=self.device();job=self.server.store.queue(device['id'])['id']
        _,principal=self.credential('operator')
        jobs.cancel(self.server.store,job,principal)
        from protec.server import Store
        restarted=Store(self.server.store.path)
        self.assertEqual(restarted.heartbeat(device['id'],inventory(),1)['jobs'],[])
        self.assertEqual(restarted.snapshot()['jobs'][0]['status'],'cancelled')


del Harness
