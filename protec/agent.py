"""Foreground inventory agent. No shell execution or privilege escalation."""
import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import socket
import ssl
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from protec.packages import collect as collect_packages
from protec.jobs import inventory_digest, validate_envelope, protocol
from protec.agent_receipts import ReceiptJournal, ReceiptError
from protec import capabilities

def inventory():
    privileged = os.geteuid()==0 if hasattr(os,'geteuid') else False
    if os.name=='nt':
        import ctypes
        privileged = bool(ctypes.windll.shell32.IsUserAnAdmin())
    system = platform.system()
    os_name = 'macOS' if system=='Darwin' else system
    version = platform.mac_ver()[0] if system=='Darwin' else platform.release()
    return {'hostname':socket.gethostname(),'os':os_name,'version':version,
            'architecture':platform.machine(),'agent_version':'0.1.0',
            'privilege':'administrator' if privileged else 'standard'}

def validate_server(url):
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use a server origin without credentials, path, query, or fragment')
    parsed.port
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','::1','localhost')):
        raise ValueError('Remote connections require HTTPS')
    return url.rstrip('/')

def tls_context():
    context = ssl.create_default_context()
    # Some python.org Mac installs have no OpenSSL CA bundle until their setup
    # script runs. Use the OS CA bundle only when no custom trust was configured.
    if (platform.system()=='Darwin' and not context.cert_store_stats()['x509_ca']
            and not os.environ.get('SSL_CERT_FILE') and not os.environ.get('SSL_CERT_DIR')
            and Path('/etc/ssl/cert.pem').is_file()):
        context.load_verify_locations(cafile='/etc/ssl/cert.pem')
    return context

def request(server,path,token,body):
    req = Request(server+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    # Do not follow redirects with an endpoint credential.
    from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            return None
    with build_opener(NoRedirect,HTTPSHandler(context=tls_context())).open(req,timeout=15) as response:
        return json.load(response)

def cycle(state,journal=None):
    offer=capabilities.inventory_offer()
    fresh = time.monotonic()-state.get('_package_scan',float('-inf'))>=300
    if fresh:
        state['_packages']=collect_packages()
        state['_package_scan']=time.monotonic()
    current=inventory()
    current['packages']=state['_packages']
    response = request(state['server'],'/api/heartbeat',state['credential'],{'inventory':current,'job_protocol':1,'job_capabilities':offer})
    if not isinstance(response,dict) or not isinstance(response.get('jobs'),list) or len(response['jobs'])>10:
        raise ValueError('Invalid job delivery response')
    negotiated=protocol(response.get('job_protocol',0))
    jobs=[validate_envelope(job,state.get('id')) for job in response['jobs']]
    if any(job.get('version',0)!=negotiated for job in jobs):
        raise ValueError('Delivered job does not match the negotiated protocol')
    capabilities.validate_delivery(jobs,offer,response.get('capability_admission',capabilities.UNREPORTED))
    if journal is not None:
        if type(response.get('receipt_lookup')) is int and response['receipt_lookup']==1:
            for record in journal.pending():
                result=request(state['server'],'/api/job-receipt?job='+record['job'],state['credential'],None)
                journal.reconcile(record,result)
        jobs=[job for job in jobs if job.get('version')!=1 or journal.begin(job)]
    if jobs and not fresh:
        state['_packages']=collect_packages()
        state['_package_scan']=time.monotonic()
        current['packages']=state['_packages']
        request(state['server'],'/api/heartbeat',state['credential'],{'inventory':current,'job_protocol':1,'job_capabilities':offer})
    for job in jobs:
        completion={'job':job['id']}
        if job.get('version')==1:
            validate_envelope(job,state.get('id'))
            completion.update(version=1,attempt=job['attempt'],lease_token=job['lease']['token'],result={'outcome':'succeeded','inventory_sha256':inventory_digest(current)})
        if journal is not None and job.get('version')==1:
            journal.reported(job,completion['result']['inventory_sha256'])
        result=request(state['server'],'/api/complete',state['credential'],completion)
        if journal is not None and job.get('version')==1:
            journal.acknowledge(job,result.get('receipt') if isinstance(result,dict) else None)
    return len(response['jobs'])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server',default='http://127.0.0.1:8765')
    parser.add_argument('--state',type=Path,default=Path('.protec/agent.json'))
    parser.add_argument('--enroll',action='store_true')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--receipt-status',action='store_true',help='Print local receipt metadata without contacting the control plane')
    args = parser.parse_args()
    os.umask(0o077)
    if args.receipt_status and args.enroll:
        parser.error('--receipt-status cannot be combined with --enroll')
    if args.enroll:
        if args.state.exists():
            raise SystemExit('State already exists; use another state path for a separate enrollment')
        if os.name=='nt':
            raise SystemExit('Windows enrollment requires a credential store/ACL implementation; this prototype enrolls POSIX hosts only')
        server = validate_server(args.server)
        args.state.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        token = getpass.getpass('Single-use enrollment token: ').strip()
        state = request(server,'/api/enroll',token,{'inventory':inventory()})
        state['server'] = server
        with args.state.open('x') as file:
            json.dump(state,file)
        print('Enrolled device '+state['id'])
    state = json.loads(args.state.read_text())
    state['server'] = validate_server(state['server'])
    try:
        journal=ReceiptJournal(args.state.with_name(args.state.name+'.receipts'),state['server'],state['id'])
    except (ReceiptError,OSError) as error:
        raise SystemExit('Cannot open local receipt journal: '+str(error)) from None
    if args.receipt_status:
        print(json.dumps(journal.status(),indent=2))
        return
    while True:
        try:
            count = cycle(state,journal)
            print(f'Inventory sent; {count} job(s) received',flush=True)
        except URLError as error:
            print(f'Check-in failed: {error.reason}',flush=True)
            if args.once:
                raise SystemExit(1)
        except (ReceiptError,OSError):
            print('Local receipt processing failed; job acknowledgement withheld',flush=True)
            if args.once:
                raise SystemExit(1)
        except ValueError:
            print('Check-in rejected: invalid inventory job protocol',flush=True)
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(30)

if __name__=='__main__':
    main()
