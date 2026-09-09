"""Cross-schema activation failure acceptance, only in the marked disposable guest.

Starts from its retained schema-1 journal and absent installed service. Preserves
that fixture baseline, tests refusal to roll older code onto schema 3, verifies
recovery with compatible code, uninstalls and restores only the lab baseline.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent.parent
STATE=Path('/var/lib/protec-agent/agent.json.receipts/journal.db')
BASE=Path('/opt/protec-agent')


def run(*args,check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=60)


def schema(path):
    connection=sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True)
    try:return connection.execute('PRAGMA user_version').fetchone()[0]
    finally:connection.close()


def main():
    if os.geteuid()!=0 or not Path('/opt/protec-lab/disposable-marker').is_file():
        raise RuntimeError('Use only the marked disposable guest')
    old=Path('/opt/protec-lab/source')
    if BASE.exists() or not STATE.is_file() or schema(STATE)!=1:
        raise RuntimeError('Requires absent installed service and retained lab schema-1 journal')
    if "elif version!=1:" not in (old/'protec/agent_receipts.py').read_text():
        raise RuntimeError('Expected original older agent source fixture')
    info=STATE.stat();installer=ROOT/'scripts/linux_agent.sh'
    with tempfile.TemporaryDirectory(prefix='protec-schema-') as temporary:
        temporary=Path(temporary);backup=temporary/'before.db'
        source=sqlite3.connect(STATE);target=sqlite3.connect(backup)
        try:source.backup(target)
        finally:target.close();source.close()
        broken=temporary/'broken';(broken/'protec').mkdir(parents=True)
        for file in (ROOT/'protec').glob('*.py'):shutil.copyfile(file,broken/'protec'/file.name)
        (broken/'VERSION').write_text('0.6.98\n')
        agent=broken/'protec/agent.py'
        text=agent.read_text();needle='    job_trust=None'
        if text.count(needle)!=1:raise RuntimeError('Agent failure injection point changed')
        agent.write_text(text.replace(needle,"    raise RuntimeError('Intentional failure after receipt migration')\n"+needle))
        try:
            run('sh',str(installer),'install',str(old))
            assert run('systemctl','is-active','--quiet','protec-agent.service',check=False).returncode==0
            failed=run('sh',str(installer),'install',str(broken),check=False)
            assert failed.returncode!=0 and 'receipt schema changed' in failed.stderr,failed.stderr
            assert schema(STATE)==3
            assert '0.6.98-' in os.readlink(BASE/'current')
            assert run('systemctl','is-active','--quiet','protec-agent.service',check=False).returncode!=0
            run('sh',str(installer),'install',str(ROOT))
            assert schema(STATE)==3
            assert run('systemctl','is-active','--quiet','protec-agent.service',check=False).returncode==0
            run('sh',str(installer),'uninstall')
            print(json.dumps({'schema_change_detected':True,'unsafe_code_rollback_refused':True,'receipts_retained':True,'compatible_recovery':True,'uninstalled':True}))
        finally:
            if BASE.exists():
                run('systemctl','stop','protec-agent.service',check=False)
                run('sh',str(installer),'uninstall')
            # This is an explicit reset of the disposable test baseline only.
            restored=STATE.with_name('journal.lab-restore')
            shutil.copyfile(backup,restored);os.chown(restored,info.st_uid,info.st_gid);restored.chmod(0o600)
            os.replace(restored,STATE)
            assert schema(STATE)==1


if __name__=='__main__':main()
