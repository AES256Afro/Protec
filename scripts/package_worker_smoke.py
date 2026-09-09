"""Verify worker cgroup timeout on the marked disposable Linux guest only."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
UNIT='protec-package-worker-lab.service'
DESTINATION=Path('/run/systemd/system')/UNIT


def run(*args,check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=20)


def main():
    if os.geteuid()!=0 or not Path('/opt/protec-lab/disposable-marker').is_file():
        raise RuntimeError('Use only the marked disposable guest')
    if DESTINATION.exists():raise RuntimeError('An existing worker test requires inspection')
    with tempfile.TemporaryDirectory(prefix='protec-worker-supervision-') as directory:
        directory=Path(directory);fixture=directory/'hang.py';pidfile=directory/'child.pid'
        fixture.write_text("""import os,signal,time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
child=os.fork()
if child==0:
    os.setsid()
    Path(__file__).with_name('child.pid').write_text(str(os.getpid()))
while True:time.sleep(1)
""")
        unit=(ROOT/'packaging/protec-package-worker.service').read_text()
        unit=unit.replace('WorkingDirectory=/opt/protec-agent/current','WorkingDirectory='+str(directory))
        unit=unit.replace('ExecStart=/usr/bin/python3 -m protec.package_worker','ExecStart=/usr/bin/python3 '+str(fixture))
        unit=unit.replace('RuntimeMaxSec=120','RuntimeMaxSec=3').replace('TimeoutStopSec=10','TimeoutStopSec=1')
        DESTINATION.write_text(unit)
        try:
            run('systemd-analyze','verify',str(DESTINATION))
            run('systemctl','daemon-reload');run('systemctl','start',UNIT)
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                state=run('systemctl','show',UNIT,'--property=ActiveState','--value').stdout.strip()
                if state=='failed':break
                time.sleep(.5)
            assert state=='failed',state
            assert run('systemctl','show',UNIT,'--property=Result','--value').stdout.strip()=='timeout'
            child=int(pidfile.read_text())
            # systemd/PID 1 must reap the detached child after killing its cgroup.
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and Path('/proc',str(child)).exists():time.sleep(.1)
            assert not Path('/proc',str(child)).exists(),'Detached child survived timeout'
            print(json.dumps({'runtime_timeout':True,'detached_child_killed':True,'native_systemd':True}))
        finally:
            run('systemctl','stop',UNIT,check=False)
            run('systemctl','reset-failed',UNIT,check=False)
            DESTINATION.unlink();run('systemctl','daemon-reload')


if __name__=='__main__':main()
