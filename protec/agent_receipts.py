"""Owner-only local inventory attempt journal. Contains no bearer or lease tokens."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
from urllib.parse import urlsplit
from protec.jobs import validate_envelope

MAX_RECORDS=10000

class ReceiptError(ValueError):
    pass


def validate_receipt(receipt,device,job):
    keys={'version','job','device','kind','attempt','outcome','inventory_sha256','recorded_at'}
    if (not isinstance(receipt,dict) or set(receipt)!=keys or type(receipt['version']) is not int or receipt['version']!=1 or
            receipt['job']!=job or receipt['device']!=device or receipt['kind']!='refresh_inventory' or
            type(receipt['attempt']) is not int or not 1<=receipt['attempt']<=3 or receipt['outcome']!='succeeded' or
            not isinstance(receipt['inventory_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',receipt['inventory_sha256']) or
            type(receipt['recorded_at']) not in (int,float) or not math.isfinite(receipt['recorded_at']) or receipt['recorded_at']<0):
        raise ReceiptError('Invalid server completion receipt')
    return receipt


class ReceiptJournal:
    def __init__(self,directory,server,device,clock=None):
        self.directory=Path(directory)
        self.path=self.directory/'journal.db'
        self.clock=clock or time.time
        self.device=device
        if not isinstance(server,str) or not isinstance(device,str):
            raise ReceiptError('Invalid journal identity binding')
        url=urlsplit(server)
        if (not re.fullmatch(r'[0-9a-f]{24}',device) or url.scheme not in ('http','https') or not url.hostname or
                url.username or url.password or url.path not in ('','/') or url.query or url.fragment):
            raise ReceiptError('Invalid journal identity binding')
        if os.name!='posix':
            raise ReceiptError('Local receipts require POSIX file protection in this release')
        try:
            self.directory.mkdir(mode=0o700,exist_ok=True)
            self._check_directory()
            try:
                descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version==0:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                        raise ReceiptError('Unrecognized receipt database')
                    db.execute('CREATE TABLE binding (server TEXT NOT NULL, device TEXT NOT NULL)')
                    db.execute('INSERT INTO binding VALUES (?,?)',(server.rstrip('/'),device))
                    db.execute('CREATE TABLE attempts (job TEXT, attempt INTEGER, state TEXT NOT NULL, inventory_sha256 TEXT, receipt TEXT, created REAL NOT NULL, updated REAL NOT NULL, PRIMARY KEY(job,attempt))')
                    db.execute('PRAGMA user_version=1')
                elif version!=1:
                    raise ReceiptError('Unsupported receipt database version')
                if [tuple(row) for row in db.execute('SELECT server,device FROM binding')]!=[(server.rstrip('/'),device)]:
                    raise ReceiptError('Receipt journal belongs to a different server or device')
        except OSError as error:
            raise ReceiptError('Cannot securely open local receipt journal') from error

    def _check_directory(self):
        info=self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise ReceiptError('Receipt directory must be owned by this user with mode 0700')

    @contextmanager
    def connect(self):
        self._check_directory()
        info=self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise ReceiptError('Receipt database must be a regular owner-only file with mode 0600')
        db=None
        try:
            db=sqlite3.connect(self.path.absolute().as_uri()+'?mode=rw',uri=True,timeout=10)
            db.row_factory=sqlite3.Row
            if db.execute('PRAGMA journal_mode').fetchone()[0]!='delete':
                raise ReceiptError('Receipt journal must use DELETE journal mode')
            db.execute('PRAGMA synchronous=EXTRA')
            if db.execute('PRAGMA synchronous').fetchone()[0]!=3:
                raise ReceiptError('Required receipt durability setting is unavailable')
            if sys.platform=='darwin':
                db.execute('PRAGMA fullfsync=ON')
            with db:
                yield db
        except sqlite3.Error as error:
            raise ReceiptError('Receipt journal database unavailable') from error
        finally:
            if db is not None:db.close()

    def begin(self,job):
        validate_envelope(job,self.device,now=self.clock())
        if job.get('version')!=1:raise ReceiptError('Only protocol-1 attempts have local receipts')
        now=self.clock()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM attempts WHERE job=? AND (attempt>=? OR state='acknowledged')",(job['id'],job['attempt'])).fetchone():
                return False
            # Keep unresolved evidence; prune only old terminal records at the capacity boundary.
            count=db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            if count>=MAX_RECORDS:
                db.execute("DELETE FROM attempts WHERE updated<? AND state IN ('acknowledged','server_cancelled','server_failed','superseded')",(now-30*86400,))
                if db.execute('SELECT count(*) FROM attempts').fetchone()[0]>=MAX_RECORDS:
                    raise ReceiptError('Receipt journal is full; inspect or archive it before accepting more jobs')
            db.execute("INSERT INTO attempts VALUES (?,?,'started',NULL,NULL,?,?)",(job['id'],job['attempt'],now,now))
        return True

    def reported(self,job,digest):
        if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise ReceiptError('Invalid local inventory digest')
        with self.connect() as db:
            if not db.execute("UPDATE attempts SET state='completion_pending',inventory_sha256=?,updated=? WHERE job=? AND attempt=? AND state='started'",(digest,self.clock(),job['id'],job['attempt'])).rowcount:
                raise ReceiptError('Local attempt was not started')

    def acknowledge(self,job,receipt):
        validate_receipt(receipt,self.device,job['id'])
        if receipt['attempt']!=job['attempt']:raise ReceiptError('Receipt belongs to a different attempt')
        with self.connect() as db:
            row=db.execute('SELECT inventory_sha256,state FROM attempts WHERE job=? AND attempt=?',(job['id'],job['attempt'])).fetchone()
            if row is None or row['state'] not in ('completion_pending','unknown','acknowledged') or row['inventory_sha256']!=receipt['inventory_sha256']:
                raise ReceiptError('Receipt does not match locally reported inventory')
            db.execute("UPDATE attempts SET state='acknowledged',receipt=?,updated=? WHERE job=? AND attempt=?",(json.dumps(receipt,sort_keys=True),self.clock(),job['id'],job['attempt']))

    def pending(self,limit=10):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT job,attempt FROM attempts WHERE state IN ('started','completion_pending','unknown') ORDER BY updated,job,attempt LIMIT ?",(limit,))]

    def reconcile(self,record,result):
        status=result.get('status') if isinstance(result,dict) else None
        attempt=result.get('attempt') if isinstance(result,dict) else None
        if (not isinstance(result,dict) or result.get('id')!=record['job'] or
                status not in ('unknown','queued','running','completed','cancelled','failed') or
                type(attempt) is not int or not 0<=attempt<=3):
            raise ReceiptError('Invalid receipt lookup response')
        receipt=result.get('receipt')
        if receipt is not None:
            validate_receipt(receipt,self.device,record['job'])
            if status!='completed' or receipt['attempt']!=attempt:raise ReceiptError('Conflicting receipt lookup response')
            if attempt==record['attempt']:
                return self.acknowledge({'id':record['job'],'attempt':record['attempt']},receipt)
        outcome='server_cancelled' if status=='cancelled' else 'server_failed' if status=='failed' else 'superseded' if attempt>record['attempt'] else 'unknown'
        with self.connect() as db:
            db.execute("UPDATE attempts SET state=?,updated=? WHERE job=? AND attempt=? AND state IN ('started','completion_pending','unknown')",(outcome,self.clock(),record['job'],record['attempt']))

    def status(self):
        with self.connect() as db:
            counts={row['state']:row['count'] for row in db.execute('SELECT state,count(*) AS count FROM attempts GROUP BY state')}
            recent=[dict(row) for row in db.execute('SELECT job,attempt,state,inventory_sha256,created,updated FROM attempts ORDER BY updated DESC LIMIT 50')]
        return {'counts':counts,'recent':recent}
