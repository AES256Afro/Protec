"""Preview or apply conservative retention with a mandatory pre-change backup."""
import argparse
from pathlib import Path
import json
import time
from protec.database import copy_database
from protec.server import Store

JOB_FILTER="""created<? AND status IN ('completed','cancelled')
AND NOT EXISTS (SELECT 1 FROM audit WHERE target=jobs.id AND time>=?)"""
TOKEN_FILTER='expires<?'

def retention(store,days=90,backup=None,now=None):
    if not isinstance(days,int) or not 30<=days<=3650:
        raise ValueError('Retention must be between 30 and 3650 days')
    cutoff=(time.time() if now is None else now)-days*86400
    with store.connect() as db:
        # Reserve the write transaction so the backup and selection cannot race writers.
        if backup is not None:
            db.execute('BEGIN IMMEDIATE')
        counts={
            'jobs':db.execute(f'SELECT count(*) FROM jobs WHERE {JOB_FILTER}',(cutoff,cutoff)).fetchone()[0],
            'enrollments':db.execute(f'SELECT count(*) FROM enrollments WHERE {TOKEN_FILTER}',(cutoff,)).fetchone()[0],
        }
        if backup is not None:
            copy_database(store.path,backup)
            db.execute(f'DELETE FROM jobs WHERE {JOB_FILTER}',(cutoff,cutoff))
            db.execute(f'DELETE FROM enrollments WHERE {TOKEN_FILTER}',(cutoff,))
            store.audit(db,'local administrator','retention.applied',json.dumps({'days':days,**counts},sort_keys=True))
    return {'mode':'applied' if backup is not None else 'preview','days':days,'cutoff':cutoff,'eligible':counts,'audit_history':'preserved','devices':'preserved'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=Path('.protec/protec.db'))
    parser.add_argument('--days',type=int,default=90)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if not args.database.is_file():
        parser.error('Database does not exist')
    if args.apply != (args.backup is not None):
        parser.error('--apply and --backup must be supplied together')
    print(json.dumps(retention(Store(args.database),args.days,args.backup),indent=2))

if __name__=='__main__':
    main()
