"""Foreground inventory agent. No shell execution or privilege escalation."""
import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import socket
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from protec.packages import collect as collect_packages

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
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use a server origin without credentials, path, query, or fragment')
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','::1','localhost')):
        raise ValueError('Remote connections require HTTPS')
    return url.rstrip('/')

def request(server,path,token,body):
    req = Request(server+path,json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    # Do not follow redirects with an endpoint credential.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            return None
    with build_opener(NoRedirect).open(req,timeout=15) as response:
        return json.load(response)

def cycle(state):
    fresh = time.monotonic()-state.get('_package_scan',float('-inf'))>=300
    if fresh:
        state['_packages']=collect_packages()
        state['_package_scan']=time.monotonic()
    current=inventory()
    current['packages']=state['_packages']
    response = request(state['server'],'/api/heartbeat',state['credential'],{'inventory':current})
    jobs=[job for job in response['jobs'] if job['kind']=='refresh_inventory']
    if jobs and not fresh:
        state['_packages']=collect_packages()
        state['_package_scan']=time.monotonic()
        current['packages']=state['_packages']
        request(state['server'],'/api/heartbeat',state['credential'],{'inventory':current})
    for job in jobs:
        request(state['server'],'/api/complete',state['credential'],{'job':job['id']})
    return len(response['jobs'])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server',default='http://127.0.0.1:8765')
    parser.add_argument('--state',type=Path,default=Path('.protec/agent.json'))
    parser.add_argument('--enroll',action='store_true')
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
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
    while True:
        try:
            count = cycle(state)
            print(f'Inventory sent; {count} job(s) received',flush=True)
        except URLError as error:
            print(f'Check-in failed: {error.reason}',flush=True)
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(30)

if __name__=='__main__':
    main()
