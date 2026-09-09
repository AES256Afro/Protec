"""One-shot inventory windows bound delivery and completion without spending early retries."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from protec.agent import inventory
from protec.jobs import inventory_digest,cancel
from protec.server import Store
from protec.identity import ROLES
from test_control_plane import HTTPTests as Harness

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.db');self.now=1000000
        self.clock=patch('time.time',side_effect=lambda:self.now);self.clock.start();self.addCleanup(self.clock.stop)
        self.device=self.store.enroll(self.store.enrollment()['token'],inventory())
    def queue(self,start=10,end=40):
        return self.store.queue(self.device['id'],window={'start':self.now+start,'end':self.now+end})['id']
    def delivery(self,version=1):return self.store.heartbeat(self.device['id'],inventory(),version)['jobs']
    def job(self):return self.store.snapshot()['jobs'][0]
    def complete(self,job):
        return self.store.complete(self.device['id'],job['id'],{'version':1,'attempt':job['attempt'],'lease_token':job['lease']['token'],'result':{'outcome':'succeeded','inventory_sha256':inventory_digest(inventory())}})
    def test_start_inclusive_end_exclusive_and_lease_is_clipped(self):
        self.queue();self.assertEqual(self.delivery(),[]);self.assertEqual(self.job()['attempt'],0)
        self.now+=10;job=self.delivery()[0];self.assertEqual(job['lease']['expires'],1000040)
        self.now=1000040
        with self.assertRaises(ValueError):self.complete(job)
        self.assertEqual(self.delivery(),[]);self.assertEqual(self.job()['status'],'failed')
        self.assertEqual(self.job()['attempt'],1)
    def test_missed_window_has_no_delivery_and_one_expiration_audit(self):
        self.queue();self.now+=41
        for _ in range(2):self.assertEqual(self.delivery(),[])
        self.assertEqual(self.job()['attempt'],0)
        self.assertEqual(sum(row['action']=='inventory.window_expired' for row in self.store.snapshot()['audit']),1)
        self.assertIsNotNone(self.store.queue(self.device['id'])['id'])
    def test_valid_completion_survives_window_end(self):
        self.queue();self.now+=10;job=self.delivery()[0];self.complete(job);self.now+=100
        self.assertEqual(self.delivery(),[]);self.assertEqual(self.job()['status'],'completed')
        self.assertTrue(self.complete(job)['duplicate'])
    def test_legacy_completion_is_also_bounded_by_window(self):
        self.queue();self.now+=10;job=self.delivery(0)[0];self.now+=30
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],job['id'])
    def test_window_persists_through_restart_and_concurrent_polls_have_one_lease(self):
        self.queue();self.store=Store(self.store.path);self.assertEqual(self.delivery(),[]);self.now+=10
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.delivery(),range(2)))
        self.assertEqual(sum(len(result) for result in results),1)
        self.assertEqual(self.job()['not_after'],1000040)
    def test_window_does_not_override_capabilities_and_expires_with_empty_offer(self):
        self.queue();self.now+=10
        empty={'version':1,'jobs':[]}
        self.assertEqual(self.store.heartbeat(self.device['id'],inventory(),1,empty)['jobs'],[])
        self.assertEqual(self.job()['attempt'],0);self.now+=31
        self.store.heartbeat(self.device['id'],inventory(),1,empty)
        self.assertEqual(self.job()['status'],'failed')
    def test_invalid_windows_do_not_create_job_or_audit(self):
        before=self.store.snapshot()['audit']
        for value in ([],{},True,{'start':True,'end':1000040},{'start':1000001.5,'end':1000040},
                      {'start':999999,'end':1000040},{'start':1000040,'end':1000040},
                      {'start':1000001,'end':1000001+86401},{'start':1000001,'end':1000000+30*86400+1},
                      {'start':1000001,'end':1000040,'extra':1}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.queue(self.device['id'],window=value)
        self.assertEqual(self.store.snapshot()['audit'],before);self.assertEqual(self.store.snapshot()['jobs'],[])
    def test_expiration_audit_failure_rolls_back_job_and_inventory(self):
        self.queue();self.now+=50;before=self.store.snapshot()
        with patch.object(self.store,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.delivery()
        after=self.store.snapshot()
        self.assertEqual(after['jobs'],before['jobs']);self.assertEqual(after['devices'],before['devices'])
    def test_window_clipped_lease_is_covered_by_pinned_signature(self):
        from protec.job_signatures import generate,Signer,Trust
        keys=Path(self.temp.name)/'keys';origin='https://portal.example.com';generate(keys,origin)
        self.store.job_signer=Signer.load(keys/'signing-key.json')
        self.queue();self.now+=10
        response=self.store.heartbeat(self.device['id'],inventory(),1)
        job=response['jobs'][0];self.assertEqual(job['lease']['expires'],1000040)
        trust=Trust.load(keys/'job-trust.json',origin)
        trust.verify_delivery(response['jobs'],response['job_signatures'],self.device['id'],origin)
        job['lease']['expires']+=100
        with self.assertRaises(ValueError):trust.verify_delivery(response['jobs'],response['job_signatures'],self.device['id'],origin)

    def test_cancellation_and_revocation_remain_terminal(self):
        job=self.queue();principal={'id':'owner','permissions':ROLES['administrator']}
        cancel(self.store,job,principal);self.now+=100
        self.assertEqual(self.delivery(),[]);self.assertEqual(self.job()['status'],'cancelled')
        self.queue();self.store.revoke(self.device['id']);self.assertEqual(self.job()['status'],'cancelled')

class WindowHTTPTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    def test_http_window_projection_and_operator_scope(self):
        import time
        from protec.identity import issue
        first=self.server.store.enroll(self.server.store.enrollment()['token'],inventory())
        other=self.server.store.enroll(self.server.store.enrollment()['token'],inventory())
        operator=issue(self.server.store,'Operator','operator',1,'owner',[first['id']])['token']
        window={'start':int(time.time())+60,'end':int(time.time())+120}
        self.assertEqual(self.request('/api/jobs',operator,{'device':other['id'],'window':window})[0],403)
        self.assertEqual(self.request('/api/jobs',operator,{'device':first['id'],'window':window})[0],200)
        job=self.request('/api/history?kind=jobs',operator)[1]['items'][0]
        self.assertEqual((job['not_before'],job['not_after']),(window['start'],window['end']))
        self.assertEqual(self.request('/api/heartbeat',first['credential'],{'inventory':inventory(),'job_protocol':1})[1]['jobs'],[])
        self.assertEqual(self.request('/api/jobs',first['credential'],{'device':first['id'],'window':window})[0],401)


del Harness
