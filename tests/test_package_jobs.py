import json
from pathlib import Path
import tempfile
import time
import unittest
from protec.server import Store
from protec.jobs import inventory_digest,validate_envelope
from protec.capabilities import inventory_offer
from protec.agent_receipts import ReceiptJournal,ReceiptError
from protec.identity import ROLES


def plan_for(device,request):
    now=int(time.time())
    plan={'version':1,'kind':'apt_preview','device':device,'request':request,'created':now,'expires':now+900,'apt_version':'2.8.3','dpkg_status_sha256':'a'*64,'simulation_sha256':'b'*64,'changes':[{'name':'fixture','before':None,'after':'1.0','action':'install'}],'root_simulation':False,'requires_revalidation':True}
    return {**plan,'plan_sha256':inventory_digest(plan)}


class PackageJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db')
        self.inventory={'os':'Linux','apt_preview':1,'hostname':'fixture'}
        self.device=self.store.enroll(self.store.enrollment()['token'],self.inventory)['id']
        self.request={'action':'install','packages':[{'name':'fixture','version':'1.0'}]}
        self.identifier=self.store.queue(self.device,package_request=self.request)['id']

    def deliver(self):return self.store.heartbeat(self.device,self.inventory,1,inventory_offer(True))['jobs'][0]

    def completion(self,job):
        return {'version':1,'attempt':job['attempt'],'lease_token':job['lease']['token'],'result':{'outcome':'succeeded','plan':plan_for(self.device,self.request)}}

    def test_explicit_capability_and_typed_payload_required(self):
        self.assertEqual(self.store.heartbeat(self.device,self.inventory,0)['jobs'],[])
        self.assertEqual(self.store.heartbeat(self.device,self.inventory,1)['jobs'],[])
        self.assertEqual(self.store.snapshot()['jobs'][0]['attempt'],0)
        job=self.deliver();self.assertEqual(job['payload'],self.request)
        validate_envelope(job,self.device)
        with self.assertRaises(ValueError):validate_envelope({**job,'payload':{}},self.device)
        with self.assertRaises(ValueError):validate_envelope({'kind':'preview_packages','id':job['id']},self.device)

    def test_preview_completion_receipt_and_local_reconciliation(self):
        job=self.deliver();completion=self.completion(job)
        journal=ReceiptJournal(Path(self.tmp.name)/'receipts','http://localhost',self.device)
        self.assertTrue(journal.begin(job));journal.reported(job,inventory_digest(completion['result']))
        receipt=self.store.complete(self.device,job['id'],completion)['receipt']
        journal.acknowledge(job,receipt)
        self.assertEqual(journal.status()['counts'],{'acknowledged':1})
        self.assertEqual(self.store.snapshot()['jobs'][0]['preview'],completion['result'])
        self.assertTrue(self.store.complete(self.device,job['id'],completion)['duplicate'])
        changed={**receipt,'kind':'refresh_inventory','inventory_sha256':receipt['result_sha256']};changed.pop('result_sha256')
        with self.assertRaises(ReceiptError):journal.acknowledge(job,changed)

    def test_wrong_target_request_and_attempt_cannot_complete(self):
        job=self.deliver();body=self.completion(job)
        with self.assertRaises(ValueError):self.store.complete('f'*24,job['id'],body)
        with self.assertRaises(ValueError):self.store.complete(self.device,job['id'],{**body,'attempt':2})
        wrong=plan_for(self.device,{'action':'remove','packages':[{'name':'fixture'}]})
        with self.assertRaises(ValueError):self.store.complete(self.device,job['id'],{**body,'result':{'outcome':'succeeded','plan':wrong}})
        self.assertEqual(self.store.snapshot()['jobs'][0]['status'],'running')

    def test_unavailable_is_bounded_and_cancelled_work_cannot_complete(self):
        job=self.deliver();body={**self.completion(job),'result':{'outcome':'unavailable','reason':'preview_unavailable'}}
        receipt=self.store.complete(self.device,job['id'],body)['receipt']
        self.assertEqual(receipt['outcome'],'unavailable')
        identifier=self.store.queue(self.device,package_request=self.request)['id'];job=self.deliver()
        from protec.jobs import cancel
        cancel(self.store,identifier,{'id':'admin','permissions':ROLES['administrator'],'device_ids':None})
        with self.assertRaises(ValueError):self.store.complete(self.device,identifier,self.completion(job))

    def test_lease_redelivery_and_old_proof_rejection(self):
        old=self.deliver()
        with self.store.connect() as db:db.execute('UPDATE jobs SET lease=0')
        new=self.deliver();self.assertEqual(new['attempt'],2)
        with self.assertRaises(ValueError):self.store.complete(self.device,old['id'],self.completion(old))
        self.store.complete(self.device,new['id'],self.completion(new))

    def test_journal_schema_one_upgrade_preserves_old_receipts(self):
        directory=Path(self.tmp.name)/'legacy'
        journal=ReceiptJournal(directory,'http://localhost',self.device)
        with journal.connect() as db:
            db.execute('ALTER TABLE attempts DROP COLUMN kind');db.execute('ALTER TABLE attempts DROP COLUMN result_sha256')
            db.execute("INSERT INTO attempts VALUES ('legacy',1,'completion_pending',?,NULL,1,1)",('c'*64,));db.execute('PRAGMA user_version=1')
        upgraded=ReceiptJournal(directory,'http://localhost',self.device)
        row=upgraded.status()['recent'][0]
        self.assertEqual(row['inventory_sha256'],row['result_sha256']);self.assertEqual(row['kind'],'refresh_inventory')

    def test_schema_seven_upgrade_preserves_policy_and_job_rows(self):
        from protec.policy_store import save,workspace
        from protec.migrations import validate_schema,SCHEMA_VERSION
        group=save(self.store,'groups',{'name':'Pilot','members':[self.device]},'admin')
        with self.store.connect() as db:
            db.execute('ALTER TABLE jobs DROP COLUMN payload');db.execute('ALTER TABLE jobs DROP COLUMN preview')
            db.execute('PRAGMA user_version=7')
            before=[tuple(row) for row in db.execute('SELECT * FROM jobs')]
        upgraded=Store(self.store.path)
        with upgraded.connect() as db:
            rows=db.execute('SELECT * FROM jobs').fetchall()
            self.assertEqual([tuple(row)[:-2] for row in rows],before)
            self.assertEqual(tuple(rows[0])[-2:],('{}',None))
            self.assertEqual(validate_schema(db),SCHEMA_VERSION)
        self.assertEqual(workspace(upgraded,None,'groups')['groups'][0]['id'],group['id'])

    def test_failed_schema_eight_upgrade_rolls_back_payload_column(self):
        import sqlite3
        with self.store.connect() as db:
            db.execute('ALTER TABLE jobs DROP COLUMN payload');db.execute('PRAGMA user_version=7')
        with self.assertRaises(sqlite3.OperationalError):Store(self.store.path)
        with self.store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],7)
            self.assertNotIn('payload',{r[1] for r in db.execute('PRAGMA table_info(jobs)')})

    def test_preview_signature_binds_exact_package_selection(self):
        from protec.job_signatures import generate,Signer,Trust
        directory=Path(self.tmp.name)/'keys';origin='https://example.invalid'
        generate(directory,origin)
        signer=Signer.load(directory/'signing-key.json');trust=Trust.load(directory/'job-trust.json',origin)
        self.store.job_signer=signer
        response=self.store.heartbeat(self.device,self.inventory,1,inventory_offer(True))
        job=response['jobs'][0];proof=response['job_signatures'][job['id']]
        trust.verify(job,proof,self.device)
        changed={**job,'payload':{'action':'install','packages':[{'name':'fixture','version':'2.0'}]}}
        with self.assertRaises(ValueError):trust.verify(changed,proof,self.device)

    def test_restart_recovers_a_preview_receipt_after_lost_response(self):
        job=self.deliver();body=self.completion(job)
        directory=Path(self.tmp.name)/'lost-response'
        journal=ReceiptJournal(directory,'http://localhost',self.device)
        journal.begin(job);journal.reported(job,inventory_digest(body['result']))
        self.store.complete(self.device,job['id'],body)
        from protec.jobs import receipt_for_device
        restarted=ReceiptJournal(directory,'http://localhost',self.device)
        pending=restarted.pending()[0]
        restarted.reconcile(pending,receipt_for_device(self.store,self.device,job['id']))
        self.assertEqual(restarted.status()['counts'],{'acknowledged':1})
