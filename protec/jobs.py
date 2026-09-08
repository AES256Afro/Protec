"""Versioned inventory jobs. Lease proofs are not offline job signatures."""
import hashlib
import json
import re
import secrets
import time

MAX_ATTEMPTS=3
LEASE_SECONDS=120
PROJECTION='id,device,kind,status,created,result,contract_version,attempt,receipt,completed,issued_by'


def inventory_digest(inventory):
    return hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def protocol(value):
    if type(value) is not int or value not in (0,1):
        raise ValueError('Unsupported job protocol')
    return value


def deliver(db,store,device,version):
    protocol(version)
    now=time.time()
    exhausted=db.execute("SELECT id FROM jobs WHERE device=? AND status='running' AND lease<=? AND attempt>=?",(device,now,MAX_ATTEMPTS)).fetchall()
    for row in exhausted:
        db.execute("UPDATE jobs SET status='failed',result='Inventory delivery retry limit reached' WHERE id=?",(row['id'],))
        store.audit(db,device,'inventory.delivery_exhausted',row['id'])
    rows=db.execute("SELECT * FROM jobs WHERE device=? AND kind='refresh_inventory' AND attempt<? AND (contract_version=0 OR contract_version=?) AND (status='queued' OR (status='running' AND lease<=?)) ORDER BY created LIMIT 10",(device,MAX_ATTEMPTS,version,now)).fetchall()
    result=[]
    for row in rows:
        token=secrets.token_urlsafe(32) if version else None
        expires=now+LEASE_SECONDS
        attempt=row['attempt']+1
        db.execute("UPDATE jobs SET status='running',lease=?,contract_version=?,attempt=?,lease_hash=? WHERE id=?",(expires,version,attempt,hashlib.sha256(token.encode()).hexdigest() if token else None,row['id']))
        envelope={'id':row['id'],'kind':row['kind']}
        if version:
            envelope.update(version=1,device=device,payload={},attempt=attempt,created=row['created'],lease={'token':token,'expires':expires})
        result.append(envelope)
    return result


def complete(store,device,job,body):
    version=protocol(body.get('version',0))
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM jobs WHERE id=? AND device=?',(job,device)).fetchone()
        endpoint=db.execute('SELECT inventory FROM devices WHERE id=? AND revoked=0',(device,)).fetchone()
        if row is None or endpoint is None or row['kind']!='refresh_inventory':
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
    if not isinstance(job,dict) or job.get('kind')!='refresh_inventory' or not isinstance(job.get('id'),str) or not re.fullmatch(r'[0-9a-f]{24}',job['id']):
        raise ValueError('Invalid or unsupported inventory job')
    version=protocol(job.get('version',0))
    if version==0:
        if set(job)!={'id','kind'}:
            raise ValueError('Invalid legacy inventory job')
        return job
    lease=job.get('lease')
    import math
    if (set(job)!={'id','kind','version','device','payload','attempt','created','lease'} or
            type(job.get('created')) not in (int,float) or not math.isfinite(job['created']) or
            job['created']<0 or job.get('device')!=device or job.get('payload')!={} or type(job.get('attempt')) is not int or
            not 1<=job['attempt']<=MAX_ATTEMPTS or not isinstance(lease,dict) or set(lease)!={'token','expires'} or
            not isinstance(lease.get('token'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',lease['token']) or
            type(lease.get('expires')) not in (int,float) or not math.isfinite(lease['expires']) or
            lease['expires']<=(time.time() if now is None else now)):
        raise ValueError('Invalid or expired inventory job lease')
    return job


def public_record(row):
    result=dict(row)
    result['receipt']=json.loads(result['receipt']) if result['receipt'] else None
    return result
