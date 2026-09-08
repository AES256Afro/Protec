"""Bounded, authenticated history projections. Credentials are never selected."""
from protec.migrations import validate_schema
import time

PROJECTIONS = {
    'credentials':'id,name,role,created,expires,revoked,issued_by',
    'audit':'id,time,actor,action,target',
    'jobs':'id,device,kind,status,created,result',
    'enrollments':'hash AS id,expires,used',
    'devices':'id,inventory,seen,revoked',
}

def page(store,kind,limit=50,cursor=None):
    if kind not in PROJECTIONS:
        raise ValueError('Unknown history collection')
    if not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError('Page size must be between 1 and 100')
    if cursor is not None and (not isinstance(cursor,int) or not 0<cursor<2**63):
        raise ValueError('Invalid history cursor')
    query=f'SELECT rowid AS position,{PROJECTIONS[kind]} FROM {kind}'
    params=[]
    if cursor is not None:
        query+=' WHERE rowid<?'
        params.append(cursor)
    query+=' ORDER BY rowid DESC LIMIT ?'
    params.append(limit+1)
    with store.connect() as db:
        rows=[dict(row) for row in db.execute(query,params)]
    more=len(rows)>limit
    rows=rows[:limit]
    next_cursor=rows[-1]['position'] if more else None
    import json
    now=time.time()
    for row in rows:
        row.pop('position')
        if kind=='devices':
            row['inventory']=json.loads(row['inventory'])
        elif kind=='credentials':
            row['status']='revoked' if row.pop('revoked') else 'expired' if row['expires']<=now else 'active'
        elif kind=='enrollments':
            used=row.pop('used')
            row['status']='revoked' if used==-1 else 'used' if used==1 else 'expired' if row['expires']<=now else 'active'
    return {'items':rows,'next_cursor':next_cursor,'kind':kind}

def health(store,started):
    with store.connect() as db:
        schema=validate_schema(db)
        counts={kind:db.execute(f'SELECT count(*) FROM {kind}').fetchone()[0] for kind in PROJECTIONS}
    return {'status':'ready','database':'readable','schema_version':schema,'uptime_seconds':int(time.monotonic()-started),'counts':counts}
