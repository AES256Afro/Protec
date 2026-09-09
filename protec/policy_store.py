"""Versioned static assignments and read-only compliance snapshots."""
import json
import re
import secrets
import time
from protec.policies import evaluate, validate_rule


def latest(db, kind):
    return [json.loads(row['payload']) for row in db.execute(
        'SELECT payload FROM policy_objects p WHERE kind=? AND revision=(SELECT max(revision) FROM policy_objects q WHERE q.kind=p.kind AND q.id=p.id) ORDER BY id', (kind,))]


def save(store, kind, body, actor):
    if kind not in ('groups','policies'):
        raise ValueError('Unknown policy collection')
    fields={'name','members'} if kind=='groups' else {'name','group_id','rule','enabled'}
    if not isinstance(body,dict) or set(body) not in (fields,fields|{'id','revision'}):
        raise ValueError('Supply all fields, with id and current revision when updating')
    name=body['name']
    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not name.isprintable():
        raise ValueError('Name must contain 1 to 80 printable characters')
    if 'id' in body and (not isinstance(body['id'],str) or not re.fullmatch('[0-9a-f]{24}',body['id']) or type(body['revision']) is not int):
        raise ValueError('Invalid object identity or revision')
    value={key:body[key] for key in fields}
    value['name']=name.strip()
    if kind=='groups':
        members=body['members']
        if not isinstance(members,list) or len(members)>100 or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{24}',x) for x in members) or len(set(members))!=len(members):
            raise ValueError('Select up to 100 unique enrolled devices')
        value['members']=sorted(members)
    else:
        value['rule']=validate_rule(body['rule'])
        if type(body['enabled']) is not bool or not isinstance(body['group_id'],str):
            raise ValueError('Choose a group and an enabled state')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        objects=latest(db,kind)
        old=next((x for x in objects if x['id']==body.get('id')),None)
        if 'id' in body and (old is None or old['revision']!=body['revision']):
            raise ValueError('This object changed. Reload before saving again')
        if old is None and len(objects)>=100:
            raise ValueError('Maximum of 100 objects in this collection')
        if kind=='groups':
            active={row[0] for row in db.execute('SELECT id FROM devices WHERE revoked=0')}
            if not set(value['members'])<=active:
                raise ValueError('Choose active enrolled devices')
        elif value['group_id'] not in {x['id'] for x in latest(db,'groups')}:
            raise ValueError('Choose an existing group')
        value.update(id=old['id'] if old else secrets.token_hex(12),revision=old['revision']+1 if old else 1,created=time.time())
        db.execute('INSERT INTO policy_objects VALUES (?,?,?,?,?)',(kind,value['id'],value['revision'],json.dumps(value),value['created']))
        store.audit(db,actor,kind+'.saved',value['id']+':'+str(value['revision']))
    return value


def workspace(store, device_ids=None, collection='compliance', *, cursor=None, limit=100):
    """One consistent snapshot; scope filters precede assignments and evaluation.

The workspace is bounded to 100 groups, 100 policies and 100 members per group.
There are at most 10,000 pairs; each page evaluates at most 100. No jobs are queued.
"""
    if type(limit) is not int or not 1<=limit<=100 or (cursor is not None and (not isinstance(cursor,str) or not re.fullmatch('[0-9a-f]{24}:[0-9a-f]{24}',cursor))):
        raise ValueError('Invalid compliance page')
    with store.connect() as db:
        db.execute('BEGIN')
        groups=latest(db,'groups')
        if device_ids is not None:
            groups=[{**g,'members':[x for x in g['members'] if x in device_ids]} for g in groups]
            groups=[g for g in groups if g['members']]
        for group in groups:
            group['scope_limited']=device_ids is not None
        if collection=='groups':return {'groups':groups}
        assignments={g['id']:g for g in groups}
        policies=[p for p in latest(db,'policies') if p['group_id'] in assignments]
        if collection=='policies':return {'policies':policies}
        now=time.time()
        results=[]
        cache={}
        pairs=[(p,assignments[p['group_id']],d) for p in policies if p['enabled'] for d in assignments[p['group_id']]['members']]
        total=len(pairs)
        pairs=[(p,g,d) for p,g,d in pairs if cursor is None or p['id']+':'+d>cursor]
        selected=pairs[:limit]
        for policy,group,identifier in selected:
            if identifier not in cache:
                row=db.execute('SELECT id,inventory,seen,revoked FROM devices WHERE id=?',(identifier,)).fetchone()
                device=dict(row) if row else None
                if device:
                    try:device['inventory']=json.loads(device['inventory'])
                    except (ValueError,TypeError):device['inventory']=None
                cache[identifier]=device
            device=cache[identifier]
            results.append({'policy_id':policy['id'],'policy_revision':policy['revision'],'group_id':group['id'],'group_revision':group['revision'],'device_id':identifier,**evaluate(policy['rule'],device,now=now)})
        return {'results':results,'evaluated_at':now,'scope_limited':device_ids is not None,'total':total,'next_cursor':selected[-1][0]['id']+':'+selected[-1][2] if len(pairs)>limit else None}
