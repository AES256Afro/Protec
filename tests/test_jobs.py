"""Inventory delivery contracts, replay handling and agent validation."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from protec.agent import cycle, inventory
from protec.jobs import inventory_digest, validate_envelope
from protec.server import Store

class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'jobs.db')
        self.device=self.store.enroll(self.store.enrollment()['token'],inventory())
        self.job=self.store.queue(self.device['id'])['id']
    def tearDown(self):
        self.temp.cleanup()
    def delivery(self,version=1):
        return self.store.heartbeat(self.device['id'],inventory(),version)['jobs']
    def completion(self,job):
        return {'version':1,'attempt':job['attempt'],'lease_token':job['lease']['token'],
                'result':{'outcome':'succeeded','inventory_sha256':inventory_digest(inventory())}}
    def expire(self):
        with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0 WHERE id=?',(self.job,))

    def test_current_attempt_receipt_is_idempotent_and_secret_safe(self):
        job=self.delivery()[0]
        result=self.store.complete(self.device['id'],self.job,self.completion(job))
        again=self.store.complete(self.device['id'],self.job,self.completion(job))
        self.assertFalse(result['duplicate']);self.assertTrue(again['duplicate'])
        self.assertEqual(again['receipt'],result['receipt'])
        snapshot=self.store.snapshot()
        self.assertEqual(snapshot['jobs'][0]['receipt'],result['receipt'])
        self.assertEqual(sum(row['action']=='inventory.completed' for row in snapshot['audit']),1)
        self.assertNotIn(job['lease']['token'],json.dumps(snapshot))
        self.assertNotIn(job['lease']['token'],Path(self.store.path).read_bytes().decode(errors='ignore'))
        self.assertNotIn('lease_hash',snapshot['jobs'][0])
        changed=self.completion(job);changed['result']['inventory_sha256']='0'*64
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job,changed)

    def test_expired_and_superseded_attempts_cannot_complete(self):
        first=self.delivery()[0];self.expire()
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job,self.completion(first))
        second=self.delivery()[0]
        self.assertEqual(second['attempt'],2)
        self.assertNotEqual(first['lease']['token'],second['lease']['token'])
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job,self.completion(first))
        self.store.complete(self.device['id'],self.job,self.completion(second))

    def test_wrong_target_token_inventory_and_protocol_are_rejected(self):
        job=self.delivery()[0]
        other=self.store.enroll(self.store.enrollment()['token'],inventory())
        with self.assertRaises(ValueError):self.store.complete(other['id'],self.job,self.completion(job))
        for change in ({'lease_token':'b'*43},{'attempt':True},{'attempt':2},{'version':0},{'version':True},{'version':2},{'result':{'outcome':'succeeded','inventory_sha256':'0'*64}},{'result':{'outcome':'succeeded','inventory_sha256':inventory_digest(inventory()),'command':'extra'}}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job,{**self.completion(job),**change})
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job)
        self.store.revoke(self.device['id'])
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job,self.completion(job))

    def test_retry_limit_is_bounded_and_new_job_can_be_queued(self):
        for attempt in range(1,4):
            self.assertEqual(self.delivery()[0]['attempt'],attempt);self.expire()
        self.assertEqual(self.delivery(),[])
        self.assertEqual(self.delivery(),[])
        snapshot=self.store.snapshot()
        self.assertEqual(snapshot['jobs'][0]['status'],'failed')
        self.assertEqual(snapshot['pending'],0)
        self.assertEqual(sum(row['action']=='inventory.delivery_exhausted' for row in snapshot['audit']),1)
        self.assertNotEqual(self.store.queue(self.device['id'])['id'],self.job)

    def test_concurrent_polling_has_one_lease_and_restart_preserves_it(self):
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.delivery(),range(2)))
        self.assertEqual(sorted(len(result) for result in results),[0,1])
        job=next(result[0] for result in results if result)
        self.store=Store(self.store.path)
        self.assertEqual(self.delivery(),[])
        self.store.complete(self.device['id'],self.job,self.completion(job))
        self.store=Store(self.store.path)
        self.assertTrue(self.store.complete(self.device['id'],self.job,self.completion(job))['duplicate'])

    def test_audit_failure_rolls_back_completion(self):
        job=self.delivery()[0]
        with patch.object(self.store,'audit',side_effect=RuntimeError('test write failure')):
            with self.assertRaises(RuntimeError):self.store.complete(self.device['id'],self.job,self.completion(job))
        row=self.store.snapshot()['jobs'][0]
        self.assertEqual(row['status'],'running');self.assertIsNone(row['receipt'])
        self.store.complete(self.device['id'],self.job,self.completion(job))

    def test_legacy_upgrade_and_no_typed_job_downgrade(self):
        legacy=self.delivery(0)[0]
        self.assertEqual(set(legacy),{'id','kind'})
        self.expire()
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job)
        typed=self.delivery(1)[0]
        self.expire()
        self.assertEqual(self.delivery(0),[])
        with self.assertRaises(ValueError):self.store.complete(self.device['id'],self.job)
        self.assertEqual(self.delivery(1)[0]['attempt'],3)
        self.assertEqual(typed['version'],1)

    def test_agent_rejects_unknown_contracts_before_completion(self):
        job=self.delivery()[0]
        for change in ({'version':True},{'version':2},{'device':'e'*24},{'payload':{'shell':'whoami'}},{'kind':'shell'},{'lease':{'token':'a'*43,'expires':0}},{'attempt':4},{'extra':'unsupported'}):
            invalid={**job,**change}
            with self.subTest(change=change),self.assertRaises(ValueError):validate_envelope(invalid,self.device['id'])
        state={**self.device,'server':'http://127.0.0.1','_package_scan':float('inf'),'_packages':{}}
        with patch('protec.agent.request',return_value={'job_protocol':1,'jobs':[{**job,'device':'e'*24}]}) as request:
            with self.assertRaises(ValueError):cycle(state)
            self.assertEqual(request.call_count,1)

    def test_unknown_protocol_does_not_change_inventory(self):
        before=self.store.snapshot()['devices'][0]
        for version in (True,2,'1',None):
            with self.assertRaises(ValueError):self.delivery(version)
        self.assertEqual(self.store.snapshot()['devices'][0],before)
