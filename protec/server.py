"""Local control plane. Run with python3 -m protec.server."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from protec.migrations import migrate
from protec.history import page, health

ROOT = Path(__file__).resolve().parent.parent

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            migrate(db)
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    def audit(self, db, actor, action, target):
        db.execute('INSERT INTO audit(time,actor,action,target) VALUES (?,?,?,?)', (time.time(),actor,action,target))
    def enrollment(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO enrollments(hash,expires) VALUES (?,?)', (digest(token),time.time()+900))
            self.audit(db,'administrator','enrollment.created','Expires in 15 minutes')
        return {'token':token,'expires_in':900}
    def enrollment_list(self):
        with self.connect() as db:
            rows = db.execute('SELECT hash,expires,used FROM enrollments ORDER BY expires DESC LIMIT 100').fetchall()
        now = time.time()
        return [{'id':r['hash'],'expires':r['expires'],
                 'status':'revoked' if r['used']==-1 else 'used' if r['used']==1 else 'expired' if r['expires']<=now else 'active'} for r in rows]
    def revoke_enrollment(self, identifier):
        with self.connect() as db:
            changed = db.execute('UPDATE enrollments SET used=-1 WHERE hash=? AND used=0 AND expires>?',(identifier,time.time())).rowcount
            if not changed:
                raise ValueError('Active enrollment token not found')
            self.audit(db,'administrator','enrollment.revoked',identifier)
        return {'ok':True}
    def enroll(self, token, inventory):
        device, credential = secrets.token_hex(12), secrets.token_urlsafe(32)
        with self.connect() as db:
            changed = db.execute('UPDATE enrollments SET used=1 WHERE hash=? AND used=0 AND expires>?', (digest(token),time.time())).rowcount
            if not changed:
                raise PermissionError('Enrollment token expired or already used')
            db.execute('INSERT INTO devices VALUES (?,?,?,?,0)', (device,digest(credential),json.dumps(inventory),time.time()))
            self.audit(db,device,'device.enrolled',device)
        return {'id':device,'credential':credential}
    def identify(self, token):
        with self.connect() as db:
            row = db.execute('SELECT id FROM devices WHERE hash=? AND revoked=0', (digest(token),)).fetchone()
        if not row:
            raise PermissionError('Device credential rejected')
        return row['id']
    def heartbeat(self, device, inventory):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM devices WHERE id=? AND revoked=0',(device,)).fetchone():
                raise PermissionError('Device revoked')
            db.execute('UPDATE devices SET inventory=?,seen=? WHERE id=?', (json.dumps(inventory),time.time(),device))
            # Only idempotent inventory jobs can be redelivered after a lease expires.
            rows = db.execute("SELECT id,kind FROM jobs WHERE device=? AND (status='queued' OR (status='running' AND lease<?)) ORDER BY created LIMIT 10",(device,time.time())).fetchall()
            for row in rows:
                db.execute("UPDATE jobs SET status='running',lease=? WHERE id=?",(time.time()+120,row['id']))
        return {'jobs':[dict(r) for r in rows]}
    def queue(self, device):
        job = secrets.token_hex(12)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM devices WHERE id=? AND revoked=0',(device,)).fetchone():
                raise ValueError('Active device not found')
            if db.execute("SELECT id FROM jobs WHERE device=? AND status IN ('queued','running')",(device,)).fetchone():
                raise ValueError('An inventory refresh is already pending')
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',(job,device,'refresh_inventory','queued',time.time(),0,None))
            self.audit(db,'administrator','inventory.requested',device)
        return {'id':job}
    def complete(self, device, job):
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET status='completed',result='Inventory received' WHERE id=? AND device=? AND status='running' AND EXISTS (SELECT 1 FROM devices WHERE id=? AND revoked=0)",(job,device,device)).rowcount
            if not changed:
                raise ValueError('No running job for this device')
            self.audit(db,device,'inventory.completed',job)
        return {'ok':True}
    def revoke(self, device):
        with self.connect() as db:
            if not db.execute('UPDATE devices SET revoked=1 WHERE id=? AND revoked=0',(device,)).rowcount:
                raise ValueError('Active device not found')
            db.execute("UPDATE jobs SET status='cancelled' WHERE device=? AND status IN ('queued','running')",(device,))
            self.audit(db,'administrator','device.revoked',device)
        return {'ok':True}
    def snapshot(self):
        with self.connect() as db:
            devices = [dict(r) for r in db.execute('SELECT id,inventory,seen,revoked FROM devices ORDER BY rowid DESC LIMIT 100')]
            for device in devices:
                device['inventory'] = json.loads(device['inventory'])
            jobs = [dict(r) for r in db.execute('SELECT id,device,kind,status,created,result FROM jobs ORDER BY created DESC LIMIT 100')]
            fleet = dict(db.execute('SELECT count(*) AS records,coalesce(sum(revoked=0),0) AS active,coalesce(sum(revoked=0 AND seen>?),0) AS online FROM devices',(time.time()-90,)).fetchone())
            pending = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            audit = [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
        return {'devices':devices,'jobs':jobs,'audit':audit,'time':time.time(),'pending':pending,'fleet':fleet}

def inventory_input(body):
    inv = body.get('inventory')
    if not isinstance(inv, dict):
        raise ValueError('Inventory must be an object')
    result = {}
    for key in ('hostname','os','version','architecture','agent_version','privilege'):
        value = inv.get(key)
        if not isinstance(value,str) or not value or len(value)>256:
            raise ValueError('Invalid inventory field: '+key)
        result[key] = value
    if result['privilege'] not in ('administrator','standard'):
        raise ValueError('Invalid privilege')
    return result

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never write credentials or request payloads into HTTP logs.
    def reply(self, status, value, content_type='application/json'):
        data = json.dumps(value).encode() if content_type=='application/json' else value
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)
    def bearer(self):
        value = self.headers.get('Authorization','')
        if not value.startswith('Bearer ') or len(value)>512:
            raise PermissionError('Authentication required')
        return value[7:]
    def admin(self):
        if not secrets.compare_digest(self.bearer(),self.server.admin_token):
            raise PermissionError('Administrator authentication required')
    def do_GET(self):
        try:
            url = urlsplit(self.path)
            path = url.path
            if path=='/api/history':
                self.admin()
                query = parse_qs(url.query)
                cursor = query.get('cursor',[None])[0]
                return self.reply(200,page(self.server.store,query.get('kind',['audit'])[0],int(query.get('limit',['50'])[0]),int(cursor) if cursor is not None else None))
            if path=='/api/health':
                self.admin()
                return self.reply(200,health(self.server.store,self.server.started))
            if path=='/api/enrollments':
                self.admin()
                return self.reply(200,{'enrollments':self.server.store.enrollment_list()})
            if path=='/api/dashboard':
                self.admin()
                return self.reply(200,self.server.store.snapshot())
            assets = {'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
            if path in assets:
                name, mime = assets[path]
                return self.reply(200,(ROOT/'static'/name).read_bytes(),mime)
            self.reply(404,{'error':'Not found'})
        except PermissionError as e:
            self.reply(401,{'error':str(e)})
        except ValueError as e:
            self.reply(400,{'error':str(e)})
        except (sqlite3.Error, OSError):
            self.reply(503,{'error':'Control plane data is unavailable'})
    def do_POST(self):
        try:
            # Bearer-only requests, JSON, and no CORS permission protect browser writes.
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+self.headers.get('Host',''):
                raise PermissionError('Cross-origin requests are rejected')
            if self.headers.get_content_type()!='application/json':
                raise ValueError('Use application/json')
            size = int(self.headers.get('Content-Length','0'))
            if size<2 or size>16384:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body,dict):
                raise ValueError('Expected a JSON object')
            path = urlsplit(self.path).path
            store = self.server.store
            if path=='/api/enroll':
                result = store.enroll(self.bearer(),inventory_input(body))
            elif path=='/api/heartbeat':
                result = store.heartbeat(store.identify(self.bearer()),inventory_input(body))
            elif path=='/api/complete':
                result = store.complete(store.identify(self.bearer()),str(body.get('job','')))
            else:
                self.admin()
                if path=='/api/enrollments':
                    result = store.enrollment()
                elif path=='/api/enrollments/revoke':
                    result = store.revoke_enrollment(str(body.get('id','')))
                elif path=='/api/jobs':
                    result = store.queue(str(body.get('device','')))
                elif path=='/api/revoke':
                    result = store.revoke(str(body.get('device','')))
                else:
                    return self.reply(404,{'error':'Not found'})
            self.reply(200,result)
        except PermissionError as e:
            self.reply(401,{'error':str(e)})
        except (ValueError,UnicodeDecodeError) as e:
            self.reply(400,{'error':str(e)})
        except Exception:
            self.reply(500,{'error':'Internal server error'})

def make_server(path, token, port=8765):
    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.started = time.monotonic()
    server.store = Store(path)
    server.admin_token = token
    return server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',type=Path,default=Path('.protec'))
    args = parser.parse_args()
    os.umask(0o077)
    args.data.mkdir(mode=0o700,parents=True,exist_ok=True)
    token_path = args.data/'admin-token'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32))
    token = token_path.read_text().strip()
    if len(token)<32:
        raise SystemExit('Administrator token must contain at least 32 characters')
    server = make_server(args.data/'protec.db',token,args.port)
    print(f'Protec: http://127.0.0.1:{args.port}\nAdministrator token file: {token_path.resolve()}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=='__main__':
    main()
