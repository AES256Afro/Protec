"""Destructive test fixture for a disposable systemd guest, never an existing endpoint.

Requires /opt/protec-lab/disposable-marker created by the lab operator.
Run as root: before, reboot the guest, then after. All fleet data is fictional.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

LAB=Path('/opt/protec-lab')
SOURCE=LAB/'source'
STATE=Path('/var/lib/protec-agent/agent.json')
BASE=Path('/opt/protec-agent')
ORIGIN='http://127.0.0.1:8765'
INSTALLER=SOURCE/'scripts/linux_agent.sh'
EVIDENCE=LAB/'evidence.json'
PLANE=Path('/var/lib/protec-lab')


def run(*args,expected=0,stdin=None):
    result=subprocess.run(args,input=stdin,text=True,capture_output=True,timeout=120)
    if result.returncode!=expected:
        # Command arguments contain paths only. Enrollment token stays in stdin.
        raise AssertionError(f'{args[0]} returned {result.returncode}, expected {expected}: '+result.stderr[-1200:])
    return result.stdout.strip()


def request(path,body=None):
    token=(PLANE/'admin-token').read_text().strip()
    req=Request(ORIGIN+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urlopen(req,timeout=10) as response:return json.load(response)


def wait_for(check,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            value=check()
            if value:return value
        except (OSError,AssertionError):pass
        time.sleep(1)
    raise AssertionError('Timed out waiting for guest acceptance condition')


def snapshot():return request('dashboard')
def identity_hash():return hashlib.sha256(STATE.read_bytes()).hexdigest()
def version_is(version):
    data=snapshot()
    return len(data['devices'])==1 and data['devices'][0]['inventory']['agent_version']==version


def refresh():
    device=snapshot()['devices'][0]['id']
    job=request('jobs',{'device':device})['id']
    run('systemctl','restart','protec-agent.service')
    return wait_for(lambda:next((j for j in snapshot()['jobs'] if j['id']==job and j['status']=='completed' and j['receipt']),None))


def before():
    if BASE.exists() or STATE.exists() or EVIDENCE.exists():raise SystemExit('Refusing to test an existing installation')
    uid=pwd.getpwnam('lab').pw_uid;gid=pwd.getpwnam('lab').pw_gid
    PLANE.mkdir(mode=0o700);os.chown(PLANE,uid,gid)
    plane_unit=Path('/etc/systemd/system/protec-lab-plane.service')
    plane_unit.write_text('[Unit]\nDescription=Disposable Protec test control plane\n[Service]\nUser=lab\nWorkingDirectory=/opt/protec-lab/source\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nExecStart=/usr/bin/python3 -m protec.server --data /var/lib/protec-lab\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n')
    run('systemctl','daemon-reload');run('systemctl','enable','--now','protec-lab-plane.service')
    wait_for(lambda:(PLANE/'admin-token').exists() and snapshot()['fleet']['records']==0)
    run('sh',str(INSTALLER),'install',str(SOURCE))
    assert run('systemctl','is-enabled','protec-agent.service')=='enabled'
    original=(SOURCE/'VERSION').read_text().strip()
    # Symlinked source content must be refused without moving the selected release.
    initial=os.readlink(BASE/'current')
    invalid=LAB/'invalid';shutil.copytree(SOURCE,invalid)
    (invalid/'protec/agent.py').unlink();(invalid/'protec/agent.py').symlink_to(SOURCE/'protec/agent.py')
    run('sh',str(INSTALLER),'install',str(invalid),expected=1)
    assert os.readlink(BASE/'current')==initial
    token=request('enrollments',{})['token']
    run('sh',str(INSTALLER),'enroll',ORIGIN,stdin=token+'\n')
    identity=identity_hash()
    wait_for(lambda:version_is(original))
    job=refresh();assert job['receipt']['outcome']=='succeeded'
    inv=snapshot()['devices'][0]['inventory']
    assert inv['os']=='Linux' and inv['privilege']=='standard'
    assert inv['packages']['status']=='complete' and inv['packages']['manager']=='dpkg'
    agent_uid=pwd.getpwnam('protec-agent').pw_uid
    assert STATE.stat().st_uid==agent_uid and STATE.stat().st_mode&0o777==0o600
    assert STATE.parent.stat().st_mode&0o777==0o700
    pid=int(run('systemctl','show','-p','MainPID','--value','protec-agent.service'))
    status=Path(f'/proc/{pid}/status').read_text()
    assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status
    denied=subprocess.run(['runuser','-u','protec-agent','--','touch',str(BASE/'current'/'unexpected-write')],capture_output=True)
    assert denied.returncode!=0
    run('sh',str(INSTALLER),'enroll',ORIGIN,expected=1)
    assert identity_hash()==identity
    # Import succeeds but service execution fails: activation must restore prior code.
    broken=LAB/'broken';shutil.copytree(SOURCE,broken);(broken/'VERSION').write_text('0.6.98\n')
    agent=broken/'protec/agent.py';text=agent.read_text()
    assert "if __name__=='__main__':\n    main()" in text
    agent.write_text(text.replace("if __name__=='__main__':\n    main()","if __name__=='__main__':\n    raise SystemExit(1)"))
    run('sh',str(INSTALLER),'install',str(broken),expected=1)
    assert os.readlink(BASE/'current')==initial
    wait_for(lambda:version_is(original));refresh()
    # A synthetic version proves code replacement and identity preservation.
    updated=LAB/'updated';shutil.copytree(SOURCE,updated);(updated/'VERSION').write_text('0.6.99\n')
    run('sh',str(INSTALLER),'install',str(updated))
    wait_for(lambda:version_is('0.6.99'))
    run('sh',str(BASE/'manage.sh'),'install',str(updated))
    assert identity_hash()==identity
    refresh()
    EVIDENCE.write_text(json.dumps({'identity_hash':identity,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text(),'original':original,'device':snapshot()['devices'][0]['id']}))
    EVIDENCE.chmod(0o600)
    print('PASS: non-root installation/enrollment, dpkg inventory, receipts, protected state/code, symlink refusal, failed activation rollback, upgrade and repeat install')
    print('Reboot this disposable guest, then run the after phase.')


def after():
    saved=json.loads(EVIDENCE.read_text())
    assert Path('/proc/sys/kernel/random/boot_id').read_text()!=saved['boot_id'],'Actual guest reboot is required'
    boot_time=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
    wait_for(lambda:version_is('0.6.99') and snapshot()['devices'][0]['seen']>=boot_time)
    assert identity_hash()==saved['identity_hash']
    assert snapshot()['devices'][0]['id']==saved['device']
    assert run('systemctl','is-active','protec-agent.service')=='active'
    refresh()
    run('sh',str(BASE/'manage.sh'),'uninstall')
    assert not BASE.exists() and not Path('/etc/systemd/system/protec-agent.service').exists()
    assert identity_hash()==saved['identity_hash']
    # Reinstallation reuses the protected state instead of creating a second device.
    run('sh',str(INSTALLER),'install',str(SOURCE))
    wait_for(lambda:version_is(saved['original']))
    refresh();assert snapshot()['fleet']['records']==1 and identity_hash()==saved['identity_hash']
    run('sh',str(BASE/'manage.sh'),'uninstall')
    assert STATE.exists() and STATE.with_name('agent.json.receipts').is_dir()
    print('PASS: actual guest reboot persistence, same enrolled identity, new receipt after reboot, uninstall and reinstall with preserved state')


if __name__=='__main__':
    os.umask(0o077)
    if os.geteuid()!=0 or not (LAB/'disposable-marker').is_file() or len(sys.argv)!=2 or sys.argv[1] not in ('before','after'):
        raise SystemExit('Requires root in the explicitly marked disposable lab guest and before|after phase')
    {'before':before,'after':after}[sys.argv[1]]()
