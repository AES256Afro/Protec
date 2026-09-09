"""Delivery admission is bounded, request-specific and never grants operator authority."""
from pathlib import Path
import tempfile
import time
import json
import unittest
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor
from protec import capabilities
from protec.agent import cycle, inventory
from protec.jobs import inventory_digest
from protec.server import Store
from test_control_plane import HTTPTests as Harness


def offer(kind='refresh_inventory',versions=None):
    return {'version':1,'jobs':[{'kind':kind,'versions':[1] if versions is None else versions}]}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.db')
        self.device=self.store.enroll(self.store.enrollment()['token'],inventory())
        self.job=self.store.queue(self.device['id'])['id']
    def heartbeat(self,value,version=1):
        return self.store.heartbeat(self.device['id'],inventory(),version,value)
    def row(self):
        with self.store.connect() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone())

    def test_empty_unknown_and_mismatched_reports_preserve_queued_job_and_attempt_budget(self):
        before=self.row()
        for value in ({'version':1,'jobs':[]},offer('shell'),offer(versions=[2]),offer(versions=[0])):
            with self.subTest(value=value):
                response=self.heartbeat(value)
                self.assertEqual(response['jobs'],[])
                self.assertEqual(response['capability_admission'],1)
                self.assertEqual(self.row(),before)
        self.assertEqual(self.heartbeat(offer())['jobs'][0]['attempt'],1)

    def test_invalid_report_is_atomic_and_cannot_update_device_or_job(self):
        before=self.store.snapshot();before_row=self.row()
        invalid=[None,[],{},True,{'version':True,'jobs':[]},{'version':2,'jobs':[]},
                 {'version':1,'jobs':[],'shell':'extra'},{'version':1,'jobs':[{}]},
                 offer('../shell'),offer(versions=[]),offer(versions=[True]),offer(versions=['1']),
                 offer(versions=[1,1]),offer(versions=[-1]),offer(versions=[65536]),
                 offer(versions=list(range(9))),{'version':1,'jobs':[offer()['jobs'][0]]*2},
                 {'version':1,'jobs':[{'kind':f'kind_{n}','versions':[1]} for n in range(33)]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.store.heartbeat(self.device['id'],{**inventory(),'hostname':'changed'},1,value)
            self.assertEqual(self.store.snapshot()['devices'],before['devices'])
            self.assertEqual(self.row(),before_row)

    def test_future_contracts_do_not_expand_server_handlers(self):
        value={'version':1,'jobs':[offer()['jobs'][0],offer('shell')['jobs'][0],offer('install_package',[42])['jobs'][0]]}
        self.assertEqual(capabilities.admitted(value,1),frozenset({('refresh_inventory',1)}))
        with self.store.connect() as db:db.execute("UPDATE jobs SET kind='shell' WHERE id=?",(self.job,))
        self.assertEqual(self.heartbeat(value)['jobs'],[])
        self.assertEqual(self.row()['status'],'queued')

    def test_future_handler_registration_does_not_expand_omitted_capabilities(self):
        with patch('protec.capabilities.SUPPORTED',capabilities.SUPPORTED | {('shell',1)}):
            self.assertEqual(capabilities.admitted(capabilities.UNREPORTED,1),frozenset({('refresh_inventory',1)}))

    def test_omitted_report_retains_read_only_legacy_path(self):
        job=self.store.heartbeat(self.device['id'],inventory())['jobs'][0]
        self.assertEqual(set(job),{'id','kind'})
        with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0')
        typed=self.store.heartbeat(self.device['id'],inventory(),1)['jobs'][0]
        self.assertEqual(typed['version'],1)
        with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0')
        self.assertEqual(self.heartbeat(offer(versions=[0]),0)['jobs'],[])
        self.assertEqual(self.row()['contract_version'],1)

    def test_withdrawal_does_not_revoke_an_active_lease_or_burn_a_retry(self):
        job=self.heartbeat(offer())['jobs'][0]
        before=self.row()
        self.assertEqual(self.heartbeat({'version':1,'jobs':[]})['jobs'],[])
        self.assertEqual(self.row(),before)
        completion={'version':1,'attempt':1,'lease_token':job['lease']['token'],
                    'result':{'outcome':'succeeded','inventory_sha256':inventory_digest(inventory())}}
        self.assertEqual(self.store.complete(self.device['id'],self.job,completion)['receipt']['outcome'],'succeeded')

    def test_report_is_not_cached_across_polls_or_restart(self):
        self.heartbeat(offer())
        with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0')
        self.store=Store(self.store.path)
        self.assertEqual(self.heartbeat({'version':1,'jobs':[]})['jobs'],[])
        self.assertEqual(self.row()['attempt'],1)
        self.assertEqual(self.heartbeat(offer())['jobs'][0]['attempt'],2)

    def test_concurrent_offers_cannot_consume_two_attempts(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(self.heartbeat,[offer(),{'version':1,'jobs':[]},offer()]))
        self.assertEqual(sum(len(result['jobs']) for result in results),1)
        self.assertEqual(self.row()['attempt'],1)

    def test_exhausted_reads_are_finalized_without_new_admission(self):
        for _ in range(3):
            self.heartbeat(offer())
            with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0')
        self.heartbeat({'version':1,'jobs':[]})
        self.assertEqual(self.row()['status'],'failed')
        self.assertEqual(self.row()['attempt'],3)
        self.heartbeat({'version':1,'jobs':[]})
        self.assertEqual(sum(row['action']=='inventory.delivery_exhausted' for row in self.store.snapshot()['audit']),1)

    def test_agent_rejects_unadvertised_deliveries_before_journal_and_forced_collection(self):
        job=self.heartbeat(offer())['jobs'][0]
        state={**self.device,'server':'http://127.0.0.1','_package_scan':time.monotonic(),'_packages':{}}
        journal=Mock()
        with patch('protec.agent.capabilities.inventory_offer',return_value={'version':1,'jobs':[]}), \
                patch('protec.agent.request',return_value={'job_protocol':1,'jobs':[job],'capability_admission':1}) as request, \
                patch('protec.agent.collect_packages') as collect:
            with self.assertRaises(ValueError):cycle(state,journal)
        self.assertEqual(request.call_count,1);collect.assert_not_called();self.assertEqual(journal.mock_calls,[])

    def test_agent_accepts_old_server_but_rejects_unknown_admission_or_reported_downgrade(self):
        legacy={'id':self.job,'kind':'refresh_inventory'}
        capabilities.validate_delivery([legacy],offer(),capabilities.UNREPORTED)
        for admission in (1,True,2,None,'1'):
            with self.subTest(admission=admission),self.assertRaises(ValueError):
                capabilities.validate_delivery([legacy],offer(),admission)
        for admission in (True,2,None,'1'):
            with self.assertRaises(ValueError):capabilities.validate_delivery([],offer(),admission)


class AdmissionHTTPTests(unittest.TestCase):
    setUp=Harness.setUp
    tearDown=Harness.tearDown
    request=Harness.request
    def test_http_agent_advertises_both_polls_and_completes_with_local_receipt(self):
        from protec.agent import request as real_request
        from protec.agent_receipts import ReceiptJournal
        device=self.server.store.enroll(self.server.store.enrollment()['token'],inventory())
        self.server.store.queue(device['id'])
        cached={'status':'complete','manager':'dpkg','collected_at':time.time(),'total':0,'truncated':False,'items':[],'scope':'Test packages','message':'Disposable fixture'}
        refreshed={**cached,'total':1,'items':[{'name':'fixture','version':'1'}]}
        state={**device,'server':self.url,'_package_scan':time.monotonic(),'_packages':cached}
        journal=ReceiptJournal(Path(self.temp.name)/'agent.receipts',self.url,device['id'])
        polls=[]
        def transport(server,path,token,body):
            if path=='/api/heartbeat':polls.append(json.loads(json.dumps(body)))
            return real_request(server,path,token,body)
        with patch('protec.agent.request',side_effect=transport) as requests, patch('protec.agent.collect_packages',return_value=refreshed):
            self.assertEqual(cycle(state,journal),1)
        self.assertEqual(len(polls),2)
        self.assertTrue(all(poll['job_capabilities']==offer() for poll in polls))
        self.assertEqual(polls[0]['inventory']['packages'],cached)
        self.assertEqual(polls[1]['inventory']['packages'],refreshed)
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})
        self.assertNotIn('job_capabilities',self.server.store.snapshot()['devices'][0]['inventory'])

    def test_http_null_is_invalid_empty_defers_and_report_cannot_grant_operator_access(self):
        device=self.server.store.enroll(self.server.store.enrollment()['token'],inventory())
        self.server.store.queue(device['id'])
        body={'inventory':inventory(),'job_protocol':1,'job_capabilities':None}
        self.assertEqual(self.request('/api/heartbeat',device['credential'],body)[0],400)
        body['job_capabilities']={'version':1,'jobs':[]}
        code,result=self.request('/api/heartbeat',device['credential'],body)
        self.assertEqual(code,200);self.assertEqual(result['jobs'],[])
        self.assertEqual(self.request('/api/heartbeat','a'*40,body)[0],401)
        self.assertEqual(self.request('/api/jobs',device['credential'],{'device':device['id'],'job_capabilities':offer()})[0],401)
        self.server.store.revoke(device['id'])
        self.assertEqual(self.request('/api/heartbeat',device['credential'],body)[0],401)


del Harness
