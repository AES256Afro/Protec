"""Local service credentials and role authorization, separate from device identity."""
import hashlib
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
        return {'id':'local-administrator','name':'Local administrator','role':'administrator','permissions':sorted(ROLES['administrator'])}
    with store.connect() as db:
        row=db.execute('SELECT id,name,role FROM credentials WHERE hash=? AND revoked=0 AND expires>?',(token_hash(token),time.time())).fetchone()
    if row is None or row['role'] not in ROLES:
        raise PermissionError('Access token expired, revoked or unknown')
    return {**dict(row),'permissions':sorted(ROLES[row['role']])}

def require(identity,permission):
    if permission not in identity['permissions']:
        raise Forbidden('This credential does not permit '+permission)
    return identity

def issue(store,name,role,hours,actor):
    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):
        raise ValueError('Credential name must contain 1 to 80 printable characters')
    if not isinstance(role,str) or role not in ROLES:
        raise ValueError('Unknown credential role')
    if type(hours) is not int or not 1<=hours<=720:
        raise ValueError('Credential lifetime must be 1 to 720 hours')
    identifier,token=secrets.token_hex(12),secrets.token_urlsafe(32)
    created=time.time()
    with store.connect() as db:
        db.execute('INSERT INTO credentials(id,hash,name,role,created,expires,revoked,issued_by) VALUES (?,?,?,?,?,?,0,?)',(identifier,token_hash(token),name.strip(),role,created,created+hours*3600,actor))
        store.audit(db,actor,'credential.issued',identifier)
    return {'id':identifier,'token':token,'name':name.strip(),'role':role,'expires':created+hours*3600}

def listing(store,cursor=None):
    from protec.history import page
    result=page(store,'credentials',50,cursor)
    return {'credentials':result['items'],'next_cursor':result['next_cursor']}

def revoke(store,identifier,actor):
    with store.connect() as db:
        if not db.execute('UPDATE credentials SET revoked=1 WHERE id=? AND revoked=0',(identifier,)).rowcount:
            raise ValueError('Unrevoked service credential not found')
        store.audit(db,actor,'credential.revoked',identifier)
    return {'ok':True}
