"""Execute one signed inert-fixture upgrade through the actual systemd worker."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parent.parent
UNIT='protec-signed-worker-lab.service'
DESTINATION=Path('/run/systemd/system')/UNIT


def run(*args,check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=20)


def execute_fixture(directory,job,proof,origin,device):
    directory=Path(directory)
    if os.geteuid()!=0 or not Path('/opt/protec-lab/disposable-marker').is_file():
        raise RuntimeError('Use only the marked disposable guest')
    if job['payload']['plan']['request']!={'action':'install','packages':[{'name':'protec-preview-fixture','version':'2.0'}]}:
        raise RuntimeError('Requires the fixed inert fixture upgrade')
    if DESTINATION.exists():raise RuntimeError('An existing signed worker test requires inspection')
    for name,value in (('worker.json',{'version':1,'device':device,'server':origin}),('request.json',{'job':job,'proof':proof})):
        file=directory/name;file.write_text(json.dumps(value));file.chmod(0o600)
    trust=directory/'job-trust.json';trust.write_bytes((directory/'keys/job-trust.json').read_bytes());trust.chmod(0o600)
    unit=(ROOT/'packaging/protec-package-worker.service').read_text()
    unit=unit.replace('/opt/protec-agent/current',str(ROOT))
    unit=unit.replace('ExecStart=/usr/bin/python3 -m protec.package_worker','ExecStart=/usr/bin/python3 -m protec.package_worker --directory '+str(directory))
    DESTINATION.write_text(unit)
    def activate():
        run('systemctl','reset-failed',UNIT,check=False)
        run('systemctl','start',UNIT)
        deadline=time.monotonic()+140
        while time.monotonic()<deadline:
            state=run('systemctl','show',UNIT,'--property=ActiveState','--value').stdout.strip()
            if state in ('inactive','failed'):
                return run('systemctl','show',UNIT,'--property=Result','--value').stdout.strip()
            time.sleep(.5)
        raise RuntimeError('Worker did not reach a terminal service state')
    try:
        run('systemd-analyze','verify',str(DESTINATION))
        run('systemctl','daemon-reload')
        assert activate()=='success','Signed service failed'
        result=json.loads(run('/usr/bin/python3','-m','protec.package_worker','--directory',str(directory),'--result',job['id']).stdout)
        assert result['state']=='completion_pending' and not result['requires_inspection']
        assert result['result']['outcome']=='succeeded'
        assert activate()=='exit-code','Repeated service activation did not refuse the existing attempt'
        recovered=json.loads(run('/usr/bin/python3','-m','protec.package_worker','--directory',str(directory),'--result',job['id']).stdout)
        assert recovered==result,'Replay altered the retained result'
        version=run('/usr/bin/dpkg-query','-W','-f=${Version}','protec-preview-fixture').stdout
        assert version=='2.0'
        return result['result']
    finally:
        run('systemctl','stop',UNIT,check=False)
        run('systemctl','reset-failed',UNIT,check=False)
        DESTINATION.unlink();run('systemctl','daemon-reload')
        (directory/'request.json').unlink(missing_ok=True)
