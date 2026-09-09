"""Signed mutation and crash tests for the inert disposable-guest fixture only."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time


def exercise(device,name):
    if os.geteuid()!=0 or name!='protec-preview-fixture' or not Path('/opt/protec-lab/disposable-marker').is_file():
        raise RuntimeError('Signed mutation smoke requires the marked guest and inert fixture')
    from protec.apt_preview import preview
    from protec.package_changes import run_change,load_policy
    from protec.job_signatures import generate,Signer,Trust
    from protec.agent_receipts import ReceiptJournal,ReceiptError
    origin='https://package-fixture.invalid'
    with tempfile.TemporaryDirectory(prefix='protec-mutation-') as temporary:
        temporary=Path(temporary);keys=temporary/'keys';generate(keys,origin)
        signer=Signer.load(keys/'signing-key.json');trust=Trust.load(keys/'job-trust.json',origin)
        directory=temporary/'receipts';journal=ReceiptJournal(directory,origin,device)
        policy_file=temporary/'package-policy.json'
        policy_file.write_text(json.dumps({'version':1,'packages':[name],'allow_remove':True}));policy_file.chmod(0o600)
        policy=load_policy(policy_file)
        policy_file.chmod(0o644)
        try:load_policy(policy_file)
        except ValueError:pass
        else:raise AssertionError('Insecure execution policy was accepted')
        policy_file.chmod(0o600)
        def job_for(request):
            plan=preview(request,device)
            approval={'id':secrets.token_hex(12),'approved_by':'disposable-test-administrator','approved_at':int(time.time()),'expires':plan['expires'],'plan_sha256':plan['plan_sha256']}
            job={'id':secrets.token_hex(12),'kind':'apply_packages','version':1,'device':device,'payload':{'plan':plan,'approval':approval},'created':time.time(),'attempt':1,'lease':{'token':secrets.token_urlsafe(32),'expires':min(time.time()+120,plan['expires'])}}
            return job,signer.sign(job)
        job,proof=job_for({'action':'install','packages':[{'name':name,'version':'2.0'}]})
        result=run_change(job,proof,device,trust,policy,journal)
        assert result['outcome']=='succeeded' and result['observed']==[{'name':name,'version':'2.0'}],result
        try:run_change(job,proof,device,trust,policy,journal)
        except ReceiptError:pass
        else:raise AssertionError('Signed mutation replay was accepted')
        job,proof=job_for({'action':'remove','packages':[{'name':name}]})
        result=run_change(job,proof,device,trust,policy,journal)
        assert result['outcome']=='succeeded' and result['observed']==[{'name':name,'version':None}],result
        interrupted,proof=job_for({'action':'install','packages':[{'name':name,'version':'1.0'}]})
        payload=temporary/'interrupted.json'
        payload.write_text(json.dumps({'job':interrupted,'proof':proof,'device':device,'origin':origin,'keys':str(keys),'journal':str(directory),'policy':policy}));payload.chmod(0o600)
        child="""import json,os,sys
from protec.agent_receipts import ReceiptJournal
from protec.job_signatures import Trust
from protec.package_changes import run_change
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
journal=ReceiptJournal(p['journal'],p['origin'],p['device'])
journal.reported=lambda *args:os._exit(73)
run_change(p['job'],p['proof'],p['device'],Trust.load(Path(p['keys'])/'job-trust.json',p['origin']),p['policy'],journal)
"""
        crash=subprocess.run(['/usr/bin/python3','-c',child,str(payload)],capture_output=True,text=True,timeout=90)
        assert crash.returncode==73,crash.stderr
        installed=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${Version}',name],check=True,capture_output=True,text=True).stdout
        assert installed=='1.0'
        record=next(r for r in journal.status()['recent'] if r['job']==interrupted['id'])
        assert record['state']=='started'
        try:run_change(interrupted,proof,device,trust,policy,journal)
        except ReceiptError:pass
        else:raise AssertionError('Interrupted mutation was automatically executed again')
    return {'signed_upgrade_verified':True,'signed_remove_verified':True,'signed_install_verified':True,'replay_refused':True,'crash_after_change_retained':True,'interrupted_retry_refused':True}
