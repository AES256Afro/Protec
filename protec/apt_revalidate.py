"""Resolve an artifact-bound plan while holding native APT locks. Never commits."""
from contextlib import contextmanager
import os
import platform
import time
from protec.apt_preview import status_digest,validate_plan


@contextmanager
def locked_plan(plan,device):
    """Yield the resolved cache only while native package locks remain held.

This is an internal prerequisite for future guarded execution, not an approval
or execution endpoint. Callers must not retain or commit the cache after exit.
"""
    plan=validate_plan(plan,device)
    if plan['version']!=2:raise ValueError('Artifact-bound preview version 2 is required')
    if platform.system()!='Linux' or os.geteuid()!=0:
        raise ValueError('Locked revalidation requires root on the intended Linux target')
    try:
        import apt
        import apt_pkg
        import apt.progress.base
    except ImportError:
        raise ValueError('Native python3-apt is required on the Linux target') from None
    apt_pkg.init_config()
    apt_pkg.config['APT::Install-Recommends']='false'
    apt_pkg.config['APT::Install-Suggests']='false'
    apt_pkg.config['APT::Get::AllowUnauthenticated']='false'
    apt_pkg.init_system()
    with apt_pkg.SystemLock():
        if status_digest()!=plan['dpkg_status_sha256']:
            raise ValueError('Installed package state changed; request a new preview')
        cache=apt.Cache(progress=apt.progress.base.OpProgress())
        try:
            if cache.broken_count:raise ValueError('Package state is broken; manual recovery is required')
            for selection in plan['request']['packages']:
                if selection['name'] not in cache:raise ValueError('Requested package is no longer available')
                package=cache[selection['name']]
                if plan['request']['action']=='install':
                    versions=[v for v in package.versions if v.version==selection['version']]
                    if len(versions)!=1:raise ValueError('Requested version is unavailable or ambiguous')
                    package.candidate=versions[0]
                    package.mark_install(auto_fix=True,auto_inst=True,from_user=True)
                else:
                    if not package.is_installed:raise ValueError('Requested removal is no longer installed')
                    package.mark_delete(auto_fix=True,purge=False)
            if cache.broken_count:raise ValueError('Requested plan does not resolve cleanly')
            expected={change['name']:change for change in plan['changes']}
            resolved=[];artifacts=[]
            for package in cache.get_changes():
                name=package.fullname if package.fullname in expected else package.name
                before=package.installed.version if package.installed else None
                after=None if package.marked_delete else package.candidate.version if package.candidate else None
                if package.marked_reinstall or (before is None and after is None):raise ValueError('Unexpected package action during resolution')
                resolved.append({'name':name,'before':before,'after':after,'action':'remove' if after is None else 'install' if before is None else 'change_version'})
                if after is not None:
                    record=package.candidate.record
                    try:artifact={'name':name,'version':after,'sha256':record['SHA256'],'size':int(record['Size'])}
                    except (KeyError,ValueError):raise ValueError('Native package artifact metadata is incomplete') from None
                    artifacts.append(artifact)
            if sorted(resolved,key=lambda x:x['name'])!=plan['changes']:
                raise ValueError('Resolved package changes differ from the preview')
            if sorted(artifacts,key=lambda x:x['name'])!=plan['artifacts']:
                raise ValueError('Package artifacts differ from the preview')
            validate_plan(plan,device)
            yield cache
        finally:
            cache.close()


def inspect_plan(plan,device):
    with locked_plan(plan,device):
        return {'plan_sha256':plan['plan_sha256'],'checked_at':time.time(),'native_locks_held':True,'executed':False}
