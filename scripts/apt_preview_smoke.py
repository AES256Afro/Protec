"""Native APT preview fixture. Requires the marked disposable Ubuntu guest.

Creates a local, explicitly trusted fixture repository only in this guest. The
fixture package contains one inert data file and no scripts or dependencies.
It is installed directly to prepare installed-version and removal previews.
The explicit --with-changes flag additionally exercises the signed mutation core
and a process exit after a real fixture installation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(*args):
    return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=60).stdout


def main(with_changes=False):
    if os.geteuid()!=0 or not Path('/opt/protec-lab/disposable-marker').is_file():
        raise RuntimeError('Run only as root inside the marked disposable Protec guest')
    name='protec-preview-fixture'
    repo=Path('/opt/protec-lab/apt-preview-repo')
    source=Path('/etc/apt/sources.list.d/protec-preview-fixture.list')
    if repo.exists() or source.exists():raise RuntimeError('Fixture already exists; inspect before retrying')
    check=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${Status}',name],capture_output=True,text=True)
    if check.returncode==0:raise RuntimeError('Fixture package already registered')
    repo.mkdir(mode=0o755)
    installed=False
    try:
        records=[]
        for version in ('1.0','2.0'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'package';(root/'DEBIAN').mkdir(parents=True)
                control=f'Package: {name}\nVersion: {version}\nArchitecture: all\nMaintainer: Protec Lab <lab@example.invalid>\nDescription: Inert disposable preview test\n'
                (root/'DEBIAN/control').write_text(control)
                data=root/'usr/share'/name;data.mkdir(parents=True);(data/'version').write_text(version+'\n')
                deb=repo/f'{name}_{version}_all.deb';run('/usr/bin/dpkg-deb','--build',str(root),str(deb))
            content=deb.read_bytes()
            records.append(control+f'Filename: ./{deb.name}\nSize: {len(content)}\nSHA256: {hashlib.sha256(content).hexdigest()}\n')
        (repo/'Packages').write_text('\n'.join(records)+'\n')
        source.write_text(f'deb [trusted=yes] file:{repo} ./\n')
        run('/usr/bin/apt-get','-o','Dir::Etc::sourcelist='+str(source),'-o','Dir::Etc::sourceparts=-','update')
        from protec.apt_preview import preview,status_digest
        device='f'*24
        def request(version):return {'action':'install','packages':[{'name':name,'version':version}]}
        before=status_digest()
        fresh=preview(request('1.0'),device)
        assert fresh['changes']==[{'name':name,'before':None,'after':'1.0','action':'install'}],fresh['changes']
        assert status_digest()==before
        run('/usr/bin/dpkg','--install',str(repo/f'{name}_1.0_all.deb'));installed=True
        before=status_digest()
        upgrade=preview(request('2.0'),device)
        from protec.apt_revalidate import inspect_plan,locked_plan
        assert inspect_plan(upgrade,device)['executed'] is False
        with locked_plan(upgrade,device):
            competing=subprocess.run(['/usr/bin/python3','-c','import apt_pkg; apt_pkg.init(); apt_pkg.pkgsystem_lock()'],capture_output=True,text=True,timeout=10)
            assert competing.returncode!=0,'A competing process acquired held package locks'
        from protec.jobs import inventory_digest
        changed=json.loads(json.dumps(upgrade));changed['artifacts'][0]['sha256']='e'*64
        changed['plan_sha256']=inventory_digest({k:v for k,v in changed.items() if k!='plan_sha256'})
        try:inspect_plan(changed,device)
        except ValueError:pass
        else:raise AssertionError('Changed artifact was accepted')
        assert upgrade['version']==2 and len(upgrade['artifacts'])==1
        assert upgrade['changes']==[{'name':name,'before':'1.0','after':'2.0','action':'change_version'}],upgrade['changes']
        removal=preview({'action':'remove','packages':[{'name':name}]},device)
        assert removal['changes']==[{'name':name,'before':'1.0','after':None,'action':'remove'}],removal['changes']
        assert preview(request('1.0'),device)['changes']==[]
        assert status_digest()==before
        assert run('/usr/bin/dpkg-query','-W','-f=${Version}',name)=='1.0'
        # Exercise the real HTTP transport, capability negotiation and local journal.
        import threading
        from protec.server import make_server
        from protec.agent import cycle,inventory
        from protec.agent_receipts import ReceiptJournal
        with tempfile.TemporaryDirectory() as temporary:
            plane=make_server(Path(temporary)/'plane.db','t'*43,0)
            thread=threading.Thread(target=plane.serve_forever,daemon=True);thread.start()
            try:
                enrolled=plane.store.enroll(plane.store.enrollment()['token'],inventory())
                state={**enrolled,'server':'http://127.0.0.1:'+str(plane.server_port)}
                journal=ReceiptJournal(Path(temporary)/'receipts',state['server'],state['id'])
                cycle(state,journal);cycle(state,journal)
                job=plane.store.queue(state['id'],package_request=request('2.0'))
                cycle(state,journal)
                record=plane.store.snapshot()['jobs'][0]
                assert record['id']==job['id'] and record['status']=='completed'
                assert record['preview']['outcome']=='succeeded',record['result']
                assert record['preview']['plan']['changes']==upgrade['changes']
                assert journal.status()['counts']=={'acknowledged':1}
                assert status_digest()==before
            finally:
                plane.shutdown();plane.server_close();thread.join()
        mutation_results={}
        if with_changes:
            from scripts.package_change_smoke import exercise
            mutation_results=exercise(device,name)
        print(json.dumps({**mutation_results,'competing_lock_denied':True,'artifact_change_denied':True,'locked_revalidation':True,'remote_roundtrip':True,'local_receipt':True,'native_apt' :upgrade['apt_version'],'install_preview':True,'upgrade_preview':True,'remove_preview':True,'noop_preview':True,'unchanged_by_previews':True}))
    finally:
        if installed:run('/usr/bin/dpkg','--purge',name)
        source.unlink(missing_ok=True)
        shutil.rmtree(repo)
        # Remove only this fixture repository's lists, leaving all other sources alone.
        for path in Path('/var/lib/apt/lists').glob('*protec-lab_apt-preview-repo*'):
            if path.is_file():path.unlink()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-changes',action='store_true',help='Also exercise signed changes to the inert fixture in this disposable guest')
    main(parser.parse_args().with_changes)
