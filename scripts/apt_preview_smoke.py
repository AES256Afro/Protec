"""Native APT preview fixture. Requires the marked disposable Ubuntu guest.

Creates a local, explicitly trusted fixture repository only in this guest. The
fixture package contains one inert data file and no scripts or dependencies.
It is installed directly solely to test installed-version and removal previews.
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


def main():
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
        assert upgrade['changes']==[{'name':name,'before':'1.0','after':'2.0','action':'change_version'}],upgrade['changes']
        removal=preview({'action':'remove','packages':[{'name':name}]},device)
        assert removal['changes']==[{'name':name,'before':'1.0','after':None,'action':'remove'}],removal['changes']
        assert preview(request('1.0'),device)['changes']==[]
        assert status_digest()==before
        assert run('/usr/bin/dpkg-query','-W','-f=${Version}',name)=='1.0'
        print(json.dumps({'native_apt':upgrade['apt_version'],'install_preview':True,'upgrade_preview':True,'remove_preview':True,'noop_preview':True,'unchanged_by_previews':True}))
    finally:
        if installed:run('/usr/bin/dpkg','--purge',name)
        source.unlink(missing_ok=True)
        shutil.rmtree(repo)
        # Remove only this fixture repository's lists, leaving all other sources alone.
        for path in Path('/var/lib/apt/lists').glob('*protec-lab_apt-preview-repo*'):
            if path.is_file():path.unlink()


if __name__=='__main__':main()
