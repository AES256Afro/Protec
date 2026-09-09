"""Versioned inventory jobs. Lease proofs are not offline job signatures."""
import hashlib
import json
import re
import secrets
import time
from protec.identity import require
from protec.capabilities import SUPPORTED

MAX_ATTEMPTS=3
LEASE_SECONDS=120
PROJECTION='id,device,kind,status,created,result,contract_version,attempt,receipt,completed,issued_by,not_before,not_after,payload,preview'


def inventory_digest(inventory):
    return hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def protocol(value):
    if type(value) is not int or value not in (0,1):
        raise ValueError('Unsupported job protocol')
    return value


def deliver(db,store,device,version,admitted=SUPPORTED):
    protocol(version)
    now=time.time()
    expired=db.execute("SELECT id,kind FROM jobs WHERE device=? AND kind IN ('refresh_inventory','preview_packages') AND status IN ('queued','running') AND not_after<=?",(device,now)).fetchall()
    for row in expired:
        db.execute("UPDATE jobs SET status='failed',result='Maintenance window expired',lease=0,lease_hash=NULL WHERE id=?",(row['id'],))
        store.audit(db,device,'packages.preview_window_expired' if row['kind']=='preview_packages' else 'inventory.window_expired',row['id'])
    exhausted=db.execute("SELECT id,kind FROM jobs WHERE device=? AND kind IN ('refresh_inventory','preview_packages') AND status='running' AND lease<=? AND attempt>=?",(device,now,MAX_ATTEMPTS)).fetchall()
    for row in exhausted:
        db.execute("UPDATE jobs SET status='failed',result='Read-only job delivery retry limit reached' WHERE id=?",(row['id'],))
        store.audit(db,device,'packages.preview_exhausted' if row['kind']=='preview_packages' else 'inventory.delivery_exhausted',row['id'])
    rows=db.execute("SELECT * FROM jobs WHERE device=? AND kind IN ('refresh_inventory','preview_packages') AND (not_before IS NULL OR not_before<=?) AND (not_after IS NULL OR not_after>?) AND attempt<? AND (contract_version=0 OR contract_version=?) AND (status='queued' OR (status='running' AND lease<=?)) ORDER BY created LIMIT 10",(device,now,now,MAX_ATTEMPTS,version,now)).fetchall()
    result=[]
    for row in rows:
        if (row['kind'],version) not in admitted:continue
        token=secrets.token_urlsafe(32) if version else None
        expires=min(now+LEASE_SECONDS,row['not_after']) if row['not_after'] is not None else now+LEASE_SECONDS
        attempt=row['attempt']+1
        db.execute("UPDATE jobs SET status='running',lease=?,contract_version=?,attempt=?,lease_hash=? WHERE id=?",(expires,version,attempt,hashlib.sha256(token.encode()).hexdigest() if token else None,row['id']))
        envelope={'id':row['id'],'kind':row['kind']}
        if version:
            envelope.update(version=1,device=device,payload=json.loads(row['payload']),attempt=attempt,created=row['created'],lease={'token':token,'expires':expires})
        result.append(envelope)
    return result


def complete(store,device,job,body):
    version=protocol(body.get('version',0))
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM jobs WHERE id=? AND device=?',(job,device)).fetchone()
        endpoint=db.execute('SELECT inventory FROM devices WHERE id=? AND revoked=0',(device,)).fetchone()
        if row is None or endpoint is None or row['kind'] not in ('refresh_inventory','preview_packages'):
            raise ValueError('Job or active device not found')
        if row['contract_version']!=version:
            raise ValueError('Completion protocol does not match the leased job')
        now=time.time()
        receipt=None
        if version:
            token=body.get('lease_token')
            if (type(body.get('attempt')) is not int or body['attempt']!=row['attempt'] or
                    not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or
                    not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(),row['lease_hash'] or '')):
                raise ValueError('Completion does not match the current delivery attempt')
            if row['kind']=='preview_packages':
                return complete_preview(db,store,row,device,body,now)
            outcome=body.get('result')
            if (not isinstance(outcome,dict) or set(outcome)!={'outcome','inventory_sha256'} or
                    outcome['outcome']!='succeeded' or not isinstance(outcome['inventory_sha256'],str) or
                    not re.fullmatch(r'[0-9a-f]{64}',outcome['inventory_sha256'])):
                raise ValueError('Invalid inventory completion result')
            if row['status']=='completed':
                saved=json.loads(row['receipt'])
                if saved['inventory_sha256']!=outcome['inventory_sha256']:
                    raise ValueError('Completion conflicts with the stored receipt')
                return {'ok':True,'receipt':saved,'duplicate':True}
            if outcome['inventory_sha256']!=inventory_digest(json.loads(endpoint['inventory'])):
                raise ValueError('Completion does not match the latest received inventory')
            receipt={'version':1,'job':job,'device':device,'kind':row['kind'],'attempt':row['attempt'],
                     'outcome':'succeeded','inventory_sha256':outcome['inventory_sha256'],'recorded_at':now}
        if row['status']!='running' or row['lease']<=now:
            raise ValueError('No current running lease for this device')
        db.execute("UPDATE jobs SET status='completed',result='Inventory received',receipt=?,completed=? WHERE id=?",(json.dumps(receipt) if receipt else None,now,job))
        store.audit(db,device,'inventory.completed',job)
    return {'ok':True,**({'receipt':receipt,'duplicate':False} if receipt else {})}


def validate_envelope(job,device,now=None):
    """Agent allowlist: reject new versions, wrong targets, payloads and expired leases."""
    if not isinstance(job,dict) or job.get('kind') not in ('refresh_inventory','preview_packages') or not isinstance(job.get('id'),str) or not re.fullmatch(r'[0-9a-f]{24}',job['id']):
        raise ValueError('Invalid or unsupported inventory job')
    version=protocol(job.get('version',0))
    if version==0:
        if set(job)!={'id','kind'} or job['kind']!='refresh_inventory':
            raise ValueError('Invalid legacy inventory job')
        return job
    lease=job.get('lease')
    import math
    if (set(job)!={'id','kind','version','device','payload','attempt','created','lease'} or
            type(job.get('created')) not in (int,float) or not math.isfinite(job['created']) or
            job['created']<0 or job.get('device')!=device or type(job.get('attempt')) is not int or
            not 1<=job['attempt']<=MAX_ATTEMPTS or not isinstance(lease,dict) or set(lease)!={'token','expires'} or
            not isinstance(lease.get('token'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',lease['token']) or
            type(lease.get('expires')) not in (int,float) or not math.isfinite(lease['expires']) or
            lease['expires']<=(time.time() if now is None else now)):
        raise ValueError('Invalid or expired inventory job lease')
    if job['kind']=='refresh_inventory':
        if job['payload']!={}:raise ValueError('Invalid inventory payload')
    else:
        from protec.apt_preview import validate_request
        if validate_request(job['payload'])!=job['payload']:raise ValueError('Invalid package preview payload')
    return job


def public_record(row):
    result=dict(row)
    result['receipt']=json.loads(result['receipt']) if result['receipt'] else None
    result['payload']=json.loads(result['payload'])
    result['preview']=json.loads(result['preview']) if result['preview'] else None
    return result


def cancel(store,identifier,principal):
    """Cancel server-side delivery; an in-flight read can still finish on the agent."""
    require(principal,'jobs.write')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT device,kind,status FROM jobs WHERE id=?',(identifier,)).fetchone()
        if row is None:
            raise ValueError('Inventory job not found')
        # Authorize the stored target, never a device id supplied alongside the request.
        require(principal,'jobs.write',row['device'])
        if row['kind'] not in ('refresh_inventory','preview_packages'):
            raise ValueError('Only read-only job cancellation is supported')
        if row['status']=='cancelled':
            return {'ok':True,'id':identifier,'status':'cancelled','duplicate':True}
        if row['status'] not in ('queued','running'):
            raise ValueError('Only queued or running inventory jobs can be cancelled')
        db.execute("UPDATE jobs SET status='cancelled',lease=0,lease_hash=NULL,result='Cancelled by operator' WHERE id=?",(identifier,))
        store.audit(db,principal['id'],'packages.preview_cancelled' if row['kind']=='preview_packages' else 'inventory.cancelled',identifier)
    return {'ok':True,'id':identifier,'status':'cancelled','duplicate':False}


def receipt_for_device(store,device,identifier):
    """Narrow device-only reconciliation; never return delivery secrets or other targets."""
    if not re.fullmatch(r'[0-9a-f]{24}',identifier):
        raise ValueError('Invalid job identifier')
    with store.connect() as db:
        if not db.execute('SELECT 1 FROM devices WHERE id=? AND revoked=0',(device,)).fetchone():
            raise PermissionError('Device revoked')
        row=db.execute('SELECT id,status,attempt,receipt FROM jobs WHERE id=? AND device=?',(identifier,device)).fetchone()
    if row is None:
        return {'id':identifier,'status':'unknown','attempt':0,'receipt':None}
    result=dict(row)
    result['receipt']=json.loads(result['receipt']) if result['receipt'] else None
    return result


def complete_preview(db,store,row,device,body,now):
    """Called only after device, protocol, lease-proof and attempt checks."""
    outcome=body.get('result')
    if not isinstance(outcome,dict):raise ValueError('Invalid package preview result')
    result_digest=inventory_digest(outcome)
    if row['status']=='completed':
        receipt=json.loads(row['receipt'])
        if receipt['result_sha256']!=result_digest:raise ValueError('Conflicting package preview completion')
        return {'ok':True,'receipt':receipt,'duplicate':True}
    if row['status']!='running' or row['lease']<=now:raise ValueError('No current running lease for this device')
    if set(outcome)=={'outcome','plan'} and outcome['outcome']=='succeeded':
        from protec.apt_preview import validate_plan
        plan=validate_plan(outcome['plan'],device,now=now)
        if plan['request']!=json.loads(row['payload']) or plan['created']<int(row['created']):
            raise ValueError('Package preview does not match the queued request')
        message='APT preview available; no packages changed'
    elif outcome=={'outcome':'unavailable','reason':'preview_unavailable'}:
        message='APT preview unavailable; inspect the device package state'
    else:raise ValueError('Invalid package preview result')
    receipt={'version':1,'job':row['id'],'device':device,'kind':'preview_packages','attempt':row['attempt'],
             'outcome':outcome['outcome'],'result_sha256':result_digest,'recorded_at':now}
    db.execute("UPDATE jobs SET status='completed',result=?,preview=?,receipt=?,completed=? WHERE id=?",(message,json.dumps(outcome),json.dumps(receipt),now,row['id']))
    store.audit(db,device,'packages.preview_completed',row['id'])
    return {'ok':True,'receipt':receipt,'duplicate':False}
