"""Bounded local APT simulation. This module has no package execution operation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from protec.jobs import inventory_digest
from protec.packages import run_query

PACKAGE=r'[a-z0-9][a-z0-9+.-]{1,127}(?::[a-z0-9][a-z0-9-]{0,31})?'
VERSION=r'[0-9][A-Za-z0-9.+:~\-]{0,127}'
SUMMARY=re.compile(r'^(\d+) upgraded, (\d+) newly installed, (\d+) to remove and (\d+) not upgraded\.$')
INSTALL=re.compile(r'^Inst ('+PACKAGE+r')(?: \[('+VERSION+r')\])? \(('+VERSION+r') [^\r\n]+\)(?: \[[^\r\n]*\])?$')
REMOVE=re.compile(r'^Remv ('+PACKAGE+r') \[('+VERSION+r')\](?: \[[^\r\n]*\])?$')
CONFIGURE=re.compile(r'^Conf ('+PACKAGE+r') \(('+VERSION+r') [^\r\n]+\)$')
MAX_CHANGES=100


def validate_request(request):
    if not isinstance(request,dict) or set(request)!={'action','packages'} or request['action'] not in ('install','remove'):
        raise ValueError('Choose install or remove with exact package selections')
    packages=request['packages']
    if not isinstance(packages,list) or not 1<=len(packages)<=20:
        raise ValueError('Select 1 to 20 packages')
    seen=set();clean=[]
    for item in packages:
        fields={'name','version'} if request['action']=='install' else {'name'}
        if not isinstance(item,dict) or set(item)!=fields or not isinstance(item['name'],str) or not re.fullmatch(PACKAGE,item['name']):
            raise ValueError('Use exact Debian package names, without paths, patterns or command options')
        if item['name'].split(':',1)[0].endswith(('+','-')):
            raise ValueError('Package names ending in APT action suffixes are not supported')
        if item['name'] in seen:
            raise ValueError('Duplicate package selection')
        seen.add(item['name'])
        if request['action']=='install' and (not isinstance(item['version'],str) or not re.fullmatch(VERSION,item['version'])):
            raise ValueError('Install previews require an exact Debian package version')
        clean.append(dict(item))
    return {'action':request['action'],'packages':sorted(clean,key=lambda x:x['name'])}


def command(request):
    request=validate_request(request)
    selections=[p['name']+('='+p['version'] if request['action']=='install' else '') for p in request['packages']]
    return ['/usr/bin/apt-get','--simulate','--no-download','--no-install-recommends',
            '-o','APT::Color=0','-o','Dpkg::Progress-Fancy=0',request['action'],'--',*selections]


def parse_simulation(output):
    """Refuse incomplete or inconsistent native output rather than invent a plan."""
    if not isinstance(output,str) or len(output.encode())>512*1024:
        raise ValueError('APT preview exceeded its output limit')
    changes={};configured=set();summary=None
    for line in output.splitlines():
        if line.startswith('Inst '):
            match=INSTALL.fullmatch(line)
            if not match:raise ValueError('Unrecognized APT installation preview')
            name,before,after=match.groups()
            item={'name':name,'before':before,'after':after,'action':'install' if before is None else 'change_version'}
        elif line.startswith('Remv '):
            match=REMOVE.fullmatch(line)
            if not match:raise ValueError('Unrecognized APT removal preview')
            name,before=match.groups();item={'name':name,'before':before,'after':None,'action':'remove'}
        elif line.startswith('Conf '):
            match=CONFIGURE.fullmatch(line)
            if not match:raise ValueError('Unrecognized APT configuration preview')
            name,version=match.groups()
            if name in configured or name not in changes or changes[name]['after']!=version:
                raise ValueError('APT would configure a package outside the installation preview')
            configured.add(name);continue
        else:
            match=SUMMARY.fullmatch(line)
            if match:
                if summary is not None:raise ValueError('Duplicate APT summary')
                summary=tuple(map(int,match.groups()))
            elif re.match(r'^\d+ not fully installed or removed\.',line) or line.startswith(('E:','W:')):
                raise ValueError('APT reported incomplete package state or a warning')
            continue
        if name in changes or len(changes)>=MAX_CHANGES:
            raise ValueError('APT preview contains duplicate or too many package changes')
        changes[name]=item
    counts=(sum(x['action']=='change_version' for x in changes.values()),sum(x['action']=='install' for x in changes.values()),sum(x['action']=='remove' for x in changes.values()))
    if summary is None or counts!=summary[:3]:
        raise ValueError('APT preview changes do not match the native summary')
    if configured!={name for name,item in changes.items() if item['after'] is not None}:
        raise ValueError('APT preview is missing package configuration steps')
    return sorted(changes.values(),key=lambda x:x['name'])


def status_digest(path=Path('/var/lib/dpkg/status')):
    with path.open('rb') as source:
        data=source.read(32*1024*1024+1)
    if len(data)>32*1024*1024:raise ValueError('Package status exceeds preview limit')
    return hashlib.sha256(data).hexdigest()


def verify_selections(request,env):
    # Native APT can fall back to pattern matching for unresolved names. Require
    # an exact metadata identity before allowing even a read-only simulation.
    for package in request['packages']:
        name,_,architecture=package['name'].partition(':')
        if request['action']=='install':
            output=run_query(['/usr/bin/apt-cache','show','--',package['name']+'='+package['version']],env=env)
            records=[]
            for paragraph in output.split('\n\n'):
                fields=dict(line.split(': ',1) for line in paragraph.splitlines() if ': ' in line and not line.startswith(' '))
                records.append(fields)
            if not any(r.get('Package')==name and r.get('Version')==package['version'] and (not architecture or r.get('Architecture') in (architecture,'all')) for r in records):
                raise ValueError('Requested package version has no exact native metadata match')
        else:
            output=run_query(['/usr/bin/dpkg-query','-W','-f=${Package}\t${Architecture}\t${db:Status-Status}\n',package['name']],env=env)
            rows=[line.split('\t') for line in output.splitlines()]
            if not any(len(row)==3 and row[0]==name and (not architecture or row[1] in (architecture,'all')) and row[2]=='installed' for row in rows):
                raise ValueError('Removal preview requires an exactly matched installed package')


def preview(request,device):
    request=validate_request(request)
    if not isinstance(device,str) or not re.fullmatch('[0-9a-f]{24}',device):
        raise ValueError('A canonical enrolled device ID is required')
    if platform.system()!='Linux' or not Path('/usr/bin/apt-get').is_file():
        raise ValueError('APT previews require a Debian or Ubuntu Linux target')
    before=status_digest()
    env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','DEBIAN_FRONTEND':'noninteractive'}
    verify_selections(request,env)
    apt_version=run_query(['/usr/bin/dpkg-query','-W','-f=${Version}','apt'],env=env).strip()
    if not re.fullmatch(VERSION,apt_version):raise ValueError('Unrecognized native APT version')
    output=run_query(command(request),env=env)
    changes=parse_simulation(output)
    if status_digest()!=before:raise ValueError('Package state changed during preview; collect a new plan')
    created=int(time.time())
    plan={'version':1,'kind':'apt_preview','device':device,'request':request,'created':created,'expires':created+900,
          'apt_version':apt_version,'dpkg_status_sha256':before,'simulation_sha256':hashlib.sha256(output.encode()).hexdigest(),
          'changes':changes,'root_simulation':os.geteuid()==0,'requires_revalidation':True}
    return {**plan,'plan_sha256':inventory_digest(plan)}


def validate_plan(plan,device,*,now=None):
    """Validate content and target binding; a valid digest is not approval or trust."""
    fields={'version','kind','device','request','created','expires','apt_version','dpkg_status_sha256',
            'simulation_sha256','changes','root_simulation','requires_revalidation','plan_sha256'}
    if not isinstance(plan,dict) or set(plan)!=fields:
        raise ValueError('Invalid APT preview plan')
    now=time.time() if now is None else now
    from protec.policies import finite_time
    if not finite_time(now) or type(plan['created']) is not int or type(plan['expires']) is not int or not 0<plan['created']<=now+300 or plan['expires']!=plan['created']+900 or plan['expires']<=now:
        raise ValueError('Expired or invalid APT preview time')
    if type(plan['version']) is not int or plan['version']!=1 or plan['kind']!='apt_preview' or not isinstance(device,str) or not re.fullmatch('[0-9a-f]{24}',device) or plan['device']!=device:
        raise ValueError('APT preview does not match this device or contract')
    if type(plan['root_simulation']) is not bool or plan['requires_revalidation'] is not True or not isinstance(plan['apt_version'],str) or not re.fullmatch(VERSION,plan['apt_version']):
        raise ValueError('Invalid APT preview metadata')
    for key in ('dpkg_status_sha256','simulation_sha256','plan_sha256'):
        if not isinstance(plan[key],str) or not re.fullmatch('[0-9a-f]{64}',plan[key]):
            raise ValueError('Invalid APT preview digest')
    if validate_request(plan['request'])!=plan['request']:
        raise ValueError('APT preview selections are not canonical')
    changes=plan['changes'];names=set()
    if not isinstance(changes,list) or len(changes)>MAX_CHANGES:
        raise ValueError('Invalid APT preview changes')
    for change in changes:
        if not isinstance(change,dict) or set(change)!={'name','before','after','action'} or not isinstance(change['name'],str) or not re.fullmatch(PACKAGE,change['name']) or change['name'] in names:
            raise ValueError('Invalid or duplicate APT change')
        names.add(change['name'])
        for key in ('before','after'):
            if change[key] is not None and (not isinstance(change[key],str) or not re.fullmatch(VERSION,change[key])):
                raise ValueError('Invalid APT change version')
        action='remove' if change['after'] is None else 'install' if change['before'] is None else 'change_version'
        if (change['before'] is None and change['after'] is None) or change['action']!=action:
            raise ValueError('Inconsistent APT change')
    if changes!=sorted(changes,key=lambda c:c['name']):raise ValueError('APT changes are not canonical')
    payload={k:v for k,v in plan.items() if k!='plan_sha256'}
    if inventory_digest(payload)!=plan['plan_sha256']:raise ValueError('APT preview content changed')
    return json.loads(json.dumps(plan))


def main():
    parser=argparse.ArgumentParser(description='Read-only native APT preview. Read a JSON request from stdin; never installs packages.')
    parser.add_argument('--device',required=True,help='Enrolled ID supplied by the caller; local preview does not authenticate it')
    args=parser.parse_args()
    try:
        raw=sys.stdin.read(8193)
        if len(raw)>8192:raise ValueError('Preview request exceeds limit')
        print(json.dumps(preview(json.loads(raw),args.device),sort_keys=True))
    except (ValueError,OSError) as error:
        parser.exit(1,'Preview unavailable: '+str(error)+'\n')


if __name__=='__main__':main()
