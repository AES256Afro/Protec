"""Signed, locally constrained package mutation core. Not admitted for remote jobs yet."""
import os
from os import geteuid
import re
import time
from protec.apt_preview import PACKAGE,validate_plan
from protec.apt_revalidate import locked_plan
from protec.jobs import inventory_digest
from protec.agent_receipts import ReceiptError


def validate_payload(payload,*,now=None):
    if not isinstance(payload,dict) or set(payload)!={'plan','approval'}:
        raise ValueError('An artifact-bound plan and approval are required')
    raw=payload['plan']
    if not isinstance(raw,dict):raise ValueError('Invalid package plan')
    plan=validate_plan(raw,raw.get('device'),now=now)
    if plan['version']!=2:raise ValueError('Package changes require artifact-bound plan version 2')
    approval=payload['approval']
    fields={'id','approved_by','approved_at','expires','plan_sha256'}
    if (not isinstance(approval,dict) or set(approval)!=fields or
            not isinstance(approval['id'],str) or not re.fullmatch('[0-9a-f]{24}',approval['id']) or
            not isinstance(approval['approved_by'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',approval['approved_by']) or
            type(approval['approved_at']) is not int or not plan['created']<=approval['approved_at']<(plan['expires']) or
            approval['approved_at']>(time.time() if now is None else now)+300 or
            type(approval['expires']) is not int or approval['expires']!=plan['expires'] or approval['plan_sha256']!=plan['plan_sha256']):
        raise ValueError('Approval does not bind this package plan and expiry')
    return {'plan':plan,'approval':dict(approval)}


def validate_policy(policy):
    if not isinstance(policy,dict) or set(policy)!={'version','packages','allow_remove'} or type(policy['version']) is not int or policy['version']!=1 or type(policy['allow_remove']) is not bool:
        raise ValueError('Invalid local package execution policy')
    packages=policy['packages']
    if not isinstance(packages,list) or not 1<=len(packages)<=100 or any(not isinstance(p,str) or not re.fullmatch(PACKAGE,p) for p in packages) or len(set(packages))!=len(packages):
        raise ValueError('Choose 1 to 100 exact locally permitted package names')
    return {'version':1,'packages':list(packages),'allow_remove':policy['allow_remove']}


def load_policy(path):
    if geteuid()!=0:raise ValueError('Package execution policy must be loaded by root')
    from protec.job_signatures import protected_document
    return validate_policy(protected_document(path))


def run_change(job,proof,device,trust,policy,journal):
    """One signed attempt; any recorded attempt blocks automatic execution again.

The caller supplies root-owned local policy and pinned trust. Remote delivery is
not registered in this release. A completion result is only reported locally;
acknowledgement must come from the control plane in a subsequent integration.
"""
    if geteuid()!=0:raise ValueError('Package changes require root on the intended endpoint')
    from protec.jobs import validate_envelope
    validate_envelope(job,device)
    if job['kind']!='apply_packages' or trust is None or journal is None or journal.device!=device or trust.server!=journal.server:
        raise ValueError('Signed package job and bound local journal are required')
    trust.verify(job,proof,device)
    payload=validate_payload(job['payload']);plan=payload['plan'];policy=validate_policy(policy)
    if not journal.begin(job):
        raise ReceiptError('Package attempt is already recorded; inspect or reconcile it instead of retrying')
    attempted=False
    try:
        names={p['name'] for p in plan['request']['packages']} | {p['name'] for p in plan['changes']}
        if not names<=set(policy['packages']):raise ValueError('Package is outside the endpoint policy')
        if not policy['allow_remove'] and (plan['request']['action']=='remove' or any(p['after'] is None for p in plan['changes'])):
            raise ValueError('Endpoint policy does not permit package removal')
        with locked_plan(plan,device) as cache:
            # Preserve existing local conffiles and suppress interactive debconf.
            # This affects only the local worker process, not host configuration files.
            import apt_pkg
            import apt.progress.base
            previous_options=apt_pkg.config.value_list('DPkg::Options')
            apt_pkg.config.clear('DPkg::Options')
            apt_pkg.config['DPkg::Options::']='--force-confold'
            previous_frontend=os.environ.get('DEBIAN_FRONTEND')
            os.environ['DEBIAN_FRONTEND']='noninteractive'
            try:
                validate_envelope(job,device)
                attempted=True
                if not cache.commit(allow_unauthenticated=False):raise RuntimeError('Package manager did not complete')
            finally:
                apt_pkg.config.clear('DPkg::Options')
                for option in previous_options:apt_pkg.config['DPkg::Options::']=option
                if previous_frontend is None:os.environ.pop('DEBIAN_FRONTEND',None)
                else:os.environ['DEBIAN_FRONTEND']=previous_frontend
            cache.open(progress=apt.progress.base.OpProgress())
            observed=[]
            for change in plan['changes']:
                package=cache[change['name']] if change['name'] in cache else None
                version=package.installed.version if package and package.installed else None
                observed.append({'name':change['name'],'version':version})
            expected=[{'name':c['name'],'version':c['after']} for c in plan['changes']]
            result={'outcome':'succeeded' if observed==expected else 'uncertain','plan_sha256':plan['plan_sha256'],'observed':observed}
    except (ValueError,OSError,SystemError,RuntimeError):
        result={'outcome':'uncertain' if attempted else 'refused','plan_sha256':plan['plan_sha256'],'reason':'execution_or_verification_failed' if attempted else 'preflight_refused'}
    # A process interruption before this durable write leaves a started record.
    # It must be reconciled, never treated as permission to execute again.
    journal.reported(job,inventory_digest(result))
    return result
