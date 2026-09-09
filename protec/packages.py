"""Read-only native package inventory with bounded execution and output."""
import json
import math
import os
from pathlib import Path
import platform
import selectors
import signal
import subprocess
import time

MAX_ITEMS=500
MAX_OUTPUT=512*1024
TIMEOUT=20

def run_query(command, *, env=None):
    env=dict(os.environ,HOMEBREW_NO_AUTO_UPDATE='1',HOMEBREW_NO_ANALYTICS='1',LC_ALL='C') if env is None else dict(env)
    chunks=[]
    size=0
    deadline=time.monotonic()+TIMEOUT
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,start_new_session=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                while selector.get_map():
                    remaining=deadline-time.monotonic()
                    if remaining<=0:
                        raise ValueError('Package query timed out')
                    for key,_ in selector.select(min(remaining,0.2)):
                        chunk=os.read(key.fileobj.fileno(),65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        size+=len(chunk)
                        if size>MAX_OUTPUT:
                            raise ValueError('Package query exceeded output limit')
                        chunks.append(chunk)
            code=process.wait(timeout=max(0.01,deadline-time.monotonic()))
            if code:
                raise ValueError('Package query failed')
        except BaseException:
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
    return b''.join(chunks).decode('utf-8',errors='strict')

def parse_output(manager,output):
    items=[]
    for line in output.splitlines():
        if not line.strip():
            continue
        if manager=='dpkg':
            fields=line.split('\t')
            if len(fields)!=3:
                raise ValueError('Unrecognized package query output')
            name,version,status=fields
            if status!='installed':
                continue
        else:
            fields=line.split()
            if len(fields)<2:
                raise ValueError('Unrecognized package query output')
            name,version=fields[0],' '.join(fields[1:])
        if not name or not version or len(name)>128 or len(version)>128:
            raise ValueError('Package field exceeds supported limits')
        items.append({'name':name,'version':version})
    return sorted(items,key=lambda item:(item['name'],item['version']))

def collect():
    result={'status':'unsupported','manager':'none','scope':'No supported package manager','collected_at':time.time(),'items':[],'total':0,'truncated':False,'message':'Package inventory is not supported on this host'}
    system=platform.system()
    if system=='Darwin':
        binary=next((str(p) for p in (Path('/opt/homebrew/bin/brew'),Path('/usr/local/bin/brew')) if p.is_file()),None)
        manager,scope='homebrew','Homebrew formulae only'
        command=[binary,'list','--formula','--versions'] if binary else None
    elif system=='Linux':
        binary='/usr/bin/dpkg-query'
        manager,scope='dpkg','Installed Debian packages'
        command=[binary,'-W','-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'] if Path(binary).is_file() else None
    else:
        return result
    if not command:
        return result
    result.update(manager=manager,scope=scope)
    try:
        items=parse_output(manager,run_query(command))
        result.update(status='complete',items=items[:MAX_ITEMS],total=len(items),truncated=len(items)>MAX_ITEMS,message='Read-only package inventory')
    except (OSError,ValueError,subprocess.TimeoutExpired):
        # Native stderr may contain host paths or other sensitive information.
        result.update(status='error',message='Package inventory could not be collected within its execution and output limits')
    result['collected_at']=time.time()
    return result

def validate_report(report, *, now=None):
    now=time.time() if now is None else now
    if not isinstance(report,dict):
        raise ValueError('Invalid package report')
    status=report.get('status')
    manager=report.get('manager')
    items=report.get('items')
    total=report.get('total')
    collected=report.get('collected_at')
    truncated=report.get('truncated')
    if status not in ('complete','unsupported','error') or manager not in ('none','dpkg','homebrew'):
        raise ValueError('Invalid package status or manager')
    if not isinstance(items,list) or len(items)>MAX_ITEMS or type(total) is not int or not len(items)<=total<=1000000 or type(truncated) is not bool:
        raise ValueError('Invalid package inventory size')
    if type(collected) not in (int,float) or not math.isfinite(collected) or not 0<collected<=now+300:
        raise ValueError('Invalid package collection time')
    if truncated != (total>len(items)) or (status!='complete' and (items or total)):
        raise ValueError('Inconsistent package inventory status')
    result={'status':status,'manager':manager,'collected_at':collected,'total':total,'truncated':truncated,'items':[]}
    for key in ('scope','message'):
        value=report.get(key)
        if not isinstance(value,str) or not 1<=len(value)<=256:
            raise ValueError('Invalid package report description')
        result[key]=value
    for item in items:
        if not isinstance(item,dict):
            raise ValueError('Invalid package entry')
        row={}
        for key in ('name','version'):
            value=item.get(key)
            if not isinstance(value,str) or not 1<=len(value)<=128 or any(ord(c)<32 for c in value):
                raise ValueError('Invalid package entry field')
            row[key]=value
        result['items'].append(row)
    return result

if __name__=='__main__':
    report=collect()
    print(json.dumps({key:value for key,value in report.items() if key!='items'},indent=2))
