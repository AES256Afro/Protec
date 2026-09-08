"""Local service credentials and role authorization, separate from device identity."""
import hashlib
import json
import re
import secrets
import time

ROLES = {
    'viewer':frozenset({'inventory.read','jobs.read','health.read'}),
    'operator':frozenset({'inventory.read','jobs.read','health.read','jobs.write'}),
    'administrator':frozenset({'inventory.read','jobs.read','health.read','jobs.write','devices.revoke','enrollments.read','enrollments.write','audit.read','credentials.read','credentials.write'}),
}

class Forbidden(PermissionError):
    pass

def token_hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()

def authenticate(store,bootstrap_token,token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):
        raise PermissionError('Valid access token required')
    if secrets.compare_digest(token.encode('ascii'),bootstrap_token.encode('utf-8')):
        return {'id':'local-administrator','name':'Local administrator','role':'administrator','permissions':sorted(ROLES['administrator']),'device_ids':None}
    now=time.time()
    with store.connect() as db:
        row=db.execute('SELECT id,name,role,device_ids FROM credentials WHERE hash=? AND revoked=0 AND expires>? AND (rotation_deadline IS NULL OR rotation_deadline>?)',(token_hash(token),now,now)).fetchone()
    if row is None or row['role'] not in ROLES:
        raise PermissionError('Access token expired, revoked or unknown')
    scope = decode_scope(row['device_ids'])
    if scope is not None and row['role']=='administrator':
        raise PermissionError('Invalid credential scope')
    permissions=ROLES[row['role']] - ({'health.read'} if scope is not None else set())
    return {**dict(row),'device_ids':scope,'permissions':sorted(permissions)}

def require(identity,permission,device=None):
    if permission not in identity['permissions']:
        raise Forbidden('This credential does not permit '+permission)
    if device is not None and identity.get('device_ids') is not None and device not in identity['device_ids']:
        raise Forbidden('This credential does not permit access to that device')
    return identity

def decode_scope(value):
    if value is None:
        return None
    try:
        scope=json.loads(value)
    except (ValueError,TypeError):
        raise PermissionError('Invalid credential scope') from None
    if (not isinstance(scope,list) or not 1<=len(scope)<=100 or
            any(not isinstance(item,str) or not re.fullmatch(r'[0-9a-f]{24}',item) for item in scope) or
            len(set(scope))!=len(scope)):
        raise PermissionError('Invalid credential scope')
    return scope


def device_filter(column,device_ids):
    """Parameterized filters for trusted device columns, including empty scopes."""
    if column not in ('id','device'):
        raise ValueError('Invalid device filter column')
    if device_ids is None:
        return '1=1',[]
    if not device_ids:
        return '0=1',[]
    return column+' IN ('+','.join('?' for _ in device_ids)+')',list(device_ids)


def issue(store,name,role,hours,actor,device_ids=None):
    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):
        raise ValueError('Credential name must contain 1 to 80 printable characters')
    if not isinstance(role,str) or role not in ROLES:
        raise ValueError('Unknown credential role')
    if type(hours) is not int or not 1<=hours<=720:
        raise ValueError('Credential lifetime must be 1 to 720 hours')
    if device_ids is not None:
        try:
            device_ids=decode_scope(json.dumps(device_ids))
        except PermissionError:
            raise ValueError('Select 1 to 100 unique enrolled devices') from None
        if role=='administrator':
            raise ValueError('Device scopes are available for viewer and operator credentials')
    identifier,token=secrets.token_hex(12),secrets.token_urlsafe(32)
    created=time.time()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if device_ids is not None:
            condition,params=device_filter('id',device_ids)
            if db.execute('SELECT count(*) FROM devices WHERE revoked=0 AND '+condition,params).fetchone()[0]!=len(device_ids):
                raise ValueError('Select active enrolled devices')
        db.execute('INSERT INTO credentials(id,hash,name,role,created,expires,revoked,issued_by,device_ids) VALUES (?,?,?,?,?,?,0,?,?)',(identifier,token_hash(token),name.strip(),role,created,created+hours*3600,actor,json.dumps(device_ids) if device_ids is not None else None))
        store.audit(db,actor,'credential.issued',identifier)
    return {'id':identifier,'token':token,'name':name.strip(),'role':role,'expires':created+hours*3600,'device_ids':device_ids}

def listing(store,cursor=None):
    from protec.history import page
    result=page(store,'credentials',50,cursor)
    return {'credentials':result['items'],'next_cursor':result['next_cursor']}

def revoke(store,identifier,actor):
    invalidated=[identifier]
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT replacement_id FROM credentials WHERE id=? AND revoked=0',(identifier,)).fetchone()
        if row is None:
            raise ValueError('Unrevoked service credential not found')
        db.execute('UPDATE credentials SET revoked=1 WHERE id=?',(identifier,))
        store.audit(db,actor,'credential.revoked',identifier)
        # Revoking an unfinished handover invalidates both copies, even after its deadline.
        if row['replacement_id'] is not None:
            if db.execute('UPDATE credentials SET revoked=1 WHERE id=? AND revoked=0',(row['replacement_id'],)).rowcount:
                store.audit(db,actor,'credential.revoked',row['replacement_id'])
                invalidated.append(row['replacement_id'])
    return {'ok':True,'invalidated_ids':invalidated}


def rotate(store,identifier,actor):
    """Issue once, preserving authority and expiry, with at most 15 minutes of overlap."""
    replacement,token=secrets.token_hex(12),secrets.token_urlsafe(32)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        now=time.time()
        row=db.execute('SELECT * FROM credentials WHERE id=? AND revoked=0 AND expires>?',(identifier,now)).fetchone()
        if row is None or row['replacement_id'] is not None:
            raise ValueError('Active credential without a pending rotation required')
        if db.execute('SELECT 1 FROM credentials WHERE replacement_id=? AND revoked=0',(identifier,)).fetchone():
            raise ValueError('Finish the previous handover before rotating its replacement')
        scope=decode_scope(row['device_ids'])
        if row['role'] not in ROLES or (row['role']=='administrator' and scope is not None):
            raise ValueError('Invalid credential role or scope')
        deadline=min(now+900,row['expires'])
        db.execute('INSERT INTO credentials(id,hash,name,role,created,expires,revoked,issued_by,device_ids) VALUES (?,?,?,?,?,?,0,?,?)',
                   (replacement,token_hash(token),row['name'],row['role'],now,row['expires'],actor,row['device_ids']))
        db.execute('UPDATE credentials SET replacement_id=?,rotation_deadline=? WHERE id=?',(replacement,deadline,identifier))
        store.audit(db,actor,'credential.rotation_started',identifier+':'+replacement)
    return {'id':replacement,'token':token,'name':row['name'],'role':row['role'],'device_ids':scope,
            'expires':row['expires'],'replaces':identifier,'rotation_deadline':deadline}


def resolve_rotation(store,identifier,actor,*,cancel=False):
    """Cancel before cutoff, or retire the old credential once the replacement is saved."""
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        now=time.time()
        row=db.execute('SELECT * FROM credentials WHERE id=? AND revoked=0 AND replacement_id IS NOT NULL',(identifier,)).fetchone()
        if row is None:
            raise ValueError('Pending credential rotation not found')
        replacement=row['replacement_id']
        if cancel:
            if row['rotation_deadline'] is None or now>=min(row['rotation_deadline'],row['expires']):
                raise ValueError('Handover deadline passed; use another administrator credential to issue a replacement')
            db.execute('UPDATE credentials SET revoked=1 WHERE id=?',(replacement,))
            db.execute('UPDATE credentials SET replacement_id=NULL,rotation_deadline=NULL WHERE id=?',(identifier,))
        else:
            if not db.execute('SELECT 1 FROM credentials WHERE id=? AND revoked=0 AND expires>?',(replacement,now)).fetchone():
                raise ValueError('Replacement credential is no longer active')
            db.execute('UPDATE credentials SET revoked=1 WHERE id=?',(identifier,))
        store.audit(db,actor,'credential.rotation_cancelled' if cancel else 'credential.rotation_finished',identifier+':'+replacement)
    return {'ok':True,'invalidated_ids':[replacement if cancel else identifier]}
