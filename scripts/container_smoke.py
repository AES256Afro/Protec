"""Disposable Compose acceptance check. Never run against an existing fleet volume.

Feed this file to `docker compose exec -T protec python - seed` and, after a
container restart, `... python - verify`. The runner refuses a nonempty fleet.
It prints only check names and counts, never credentials or fleet records.
"""
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from protec.database import copy_database
from protec.jobs import inventory_digest
from protec.server import Store
from protec.version import VERSION

DATA = Path('/data')
EVIDENCE = DATA/'compose-smoke.json'
ORIGIN = 'http://127.0.0.1:8765'
INVENTORY = {'hostname':'disposable-compose-test','os':'Linux','version':'fixture',
             'architecture':'x86_64','agent_version':'smoke-fixture','privilege':'standard'}


def request(path, token=None, body=None, expected=200):
    headers = {'Content-Type':'application/json'}
    if token:
        headers['Authorization']='Bearer '+token
    req = Request(ORIGIN+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urlopen(req, timeout=10) as response:
            code, value = response.status, json.load(response)
    except HTTPError as error:
        with error:
            code, value = error.code, json.load(error)
    if code != expected:
        raise AssertionError(f'{path}: expected HTTP {expected}, got {code}')
    return value


def seed():
    # File-token mode proves the independent install bootstrap path.
    token=(DATA/'admin-token').read_text().strip()
    snapshot=request('/api/dashboard',token)
    if snapshot['fleet']['records'] or snapshot['jobs'] or snapshot['audit'] or EVIDENCE.exists():
        raise RuntimeError('Smoke checks require a fresh disposable volume')
    import os
    assert os.getuid()==10001
    health=request('/api/health',token)
    assert health['schema_version']==8 and health['version']==VERSION
    assert request('/healthz')['status']=='ok'
    request('/api/dashboard',expected=401)
    enrollment=request('/api/enrollments',token,{})
    device=request('/api/enroll',enrollment['token'],{'inventory':INVENTORY})
    request('/api/enroll',enrollment['token'],{'inventory':INVENTORY},expected=401)
    reader=request('/api/credentials',token,{'name':'Disposable reader','role':'viewer','hours':1,'device_ids':[device['id']]})
    request('/api/jobs',reader['token'],{'device':device['id']},expected=403)
    request('/api/dashboard',device['credential'],expected=401)
    another_enrollment=request('/api/enrollments',token,{})
    other=request('/api/enroll',another_enrollment['token'],{'inventory':{**INVENTORY,'hostname':'other-disposable-device'}})
    operator=request('/api/credentials',token,{'name':'Disposable operator','role':'operator','hours':1,'device_ids':[device['id']]})
    request('/api/jobs',operator['token'],{'device':other['id']},expected=403)
    scoped=request('/api/dashboard',reader['token'])
    assert [d['id'] for d in scoped['devices']]==[device['id']]
    assert scoped['fleet']['records']==1
    job=request('/api/jobs',token,{'device':device['id']})['id']
    offered={'inventory':INVENTORY,'job_protocol':1,'job_capabilities':{'version':1,'jobs':[{'kind':'refresh_inventory','versions':[1]}]}}
    delivery=request('/api/heartbeat',device['credential'],offered)['jobs'][0]
    assert delivery['id']==job
    completion={'job':job,'version':1,'attempt':delivery['attempt'],'lease_token':delivery['lease']['token'],
                'result':{'outcome':'succeeded','inventory_sha256':inventory_digest(INVENTORY)}}
    receipt=request('/api/complete',device['credential'],completion)['receipt']
    assert request('/api/complete',device['credential'],completion)['duplicate']
    now=int(time.time())
    window={'start':now+600,'end':now+1200}
    scheduled=request('/api/jobs',token,{'device':device['id'],'window':window})['id']
    assert request('/api/heartbeat',device['credential'],offered)['jobs']==[]
    request('/api/jobs/cancel',token,{'id':scheduled})
    assert request('/api/jobs/cancel',token,{'id':scheduled})['duplicate']
    pending=request('/api/jobs',token,{'device':device['id'],'window':window})['id']
    preview_inventory={**INVENTORY,'apt_preview':1}
    preview_offer={'inventory':preview_inventory,'job_protocol':1,'job_capabilities':{'version':1,'jobs':[{'kind':'preview_packages','versions':[1]}]}}
    request('/api/heartbeat',other['credential'],preview_offer)
    preview_job=request('/api/package-previews',token,{'device':other['id'],'request':{'action':'install','packages':[{'name':'fixture','version':'1.0'}]}})['id']
    leased=request('/api/heartbeat',other['credential'],preview_offer)['jobs'][0]
    assert leased['id']==preview_job and leased['kind']=='preview_packages'
    unavailable={'job':preview_job,'version':1,'attempt':leased['attempt'],'lease_token':leased['lease']['token'],'result':{'outcome':'unavailable','reason':'preview_unavailable'}}
    preview_receipt=request('/api/complete',other['credential'],unavailable)['receipt']
    assert preview_receipt['kind']=='preview_packages' and preview_receipt['outcome']=='unavailable'
    assert request('/api/complete',other['credential'],unavailable)['duplicate']
    assert not any(j['id']==preview_job for j in request('/api/dashboard',reader['token'])['jobs'])
    group=request('/api/groups' ,token,{'name':'Disposable pilot','members':[device['id'],other['id']]})
    policy=request('/api/policies',token,{'name':'Git evidence','group_id':group['id'],'enabled':True,'rule':{'kind':'package_present','manager':'dpkg','package':'git','max_age_seconds':3600}})
    compliance=request('/api/compliance',reader['token'])
    assert compliance['total']==1 and compliance['results'][0]['device_id']==device['id']
    assert compliance['results'][0]['status']=='unknown'
    request('/api/groups',reader['token'],{'name':'Forbidden','members':[]},expected=403)
    snapshot=request('/api/dashboard',token)
    assert snapshot['pending']==1
    assert next(j for j in snapshot['jobs'] if j['id']==pending)['attempt']==0
    assert sum(a['action']=='inventory.cancelled' for a in snapshot['audit'])==1
    safe=json.dumps(snapshot)
    for secret in (token,device['credential'],reader['token'],delivery['lease']['token']):
        assert secret not in safe
    # Online SQLite backup and separately opened restore preserve schema and records.
    checkpoint=copy_database(DATA/'protec.db',DATA/'smoke-backup.db')
    restored=copy_database(checkpoint,DATA/'smoke-restored.db')
    restored_store=Store(restored)
    restored_snapshot=restored_store.snapshot()
    assert restored_snapshot['devices']==snapshot['devices']
    assert restored_snapshot['jobs']==snapshot['jobs']
    assert restored_snapshot['audit']==snapshot['audit']
    from protec.policy_store import workspace
    assert workspace(restored_store,None,'groups')['groups'][0]['id']==group['id']
    assert workspace(restored_store,None,'policies')['policies'][0]==policy
    for path in (DATA/'protec.db',DATA/'admin-token',checkpoint,restored):
        assert path.stat().st_mode & 0o777 == 0o600
    assert DATA.stat().st_mode & 0o777 == 0o700
    with EVIDENCE.open('x') as output:
        json.dump({'device':device,'reader':reader['token'],'completion':completion,
                   'receipt':receipt,'snapshot':snapshot,'group':group,'policy':policy},output)
    EVIDENCE.chmod(0o600)
    print('PASS: bootstrap, role/scope denials, enrollment, receipt replay, window, cancellation, backup/restore, file permissions')


def verify():
    evidence=json.loads(EVIDENCE.read_text())
    token=(DATA/'admin-token').read_text().strip()
    snapshot=request('/api/dashboard',token)
    for key in ('devices','jobs','audit','pending'):
        assert snapshot[key]==evidence['snapshot'][key],key
    assert request('/api/dashboard',evidence['reader'])['fleet']['records']==1
    result=request('/api/complete',evidence['device']['credential'],evidence['completion'])
    assert result['duplicate'] and result['receipt']==evidence['receipt']
    assert request('/api/job-receipt?job='+evidence['completion']['job'],evidence['device']['credential'])['receipt']==evidence['receipt']
    assert request('/api/dashboard',token)['audit']==snapshot['audit']
    assert request('/api/groups',token)['groups'][0]['id']==evidence['group']['id']
    assert request('/api/policies',token)['policies'][0]==evidence['policy']
    print('PASS: container restart preserved bootstrap, device identity, scoped credential, pending window, audit and idempotent receipt')


if __name__=='__main__':
    # Newly written evidence is protected even when Python is invoked via exec.
    import os
    os.umask(0o077)
    if len(sys.argv)!=2 or sys.argv[1] not in ('seed','verify'):
        raise SystemExit('Usage: python - seed|verify (inside a disposable container)')
    {'seed':seed,'verify':verify}[sys.argv[1]]()
