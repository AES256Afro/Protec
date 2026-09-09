"""Read-only package-presence evaluation. Never dispatches changes to a device."""
import math
import re
import time
from protec.jobs import inventory_digest
from protec.packages import validate_report


def finite_time(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except OverflowError:return False


def validate_rule(rule):
    if not isinstance(rule,dict) or set(rule)!={'kind','manager','package','max_age_seconds'}:
        raise ValueError('Use a package_present rule with manager, package and max_age_seconds')
    if rule['kind']!='package_present' or rule['manager'] not in ('dpkg','homebrew'):
        raise ValueError('Only dpkg and Homebrew package-presence rules are supported')
    if not isinstance(rule['package'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+._:@/-]{0,127}',rule['package']):
        raise ValueError('Use an exact package name with at most 128 supported characters')
    if type(rule['max_age_seconds']) is not int or not 60<=rule['max_age_seconds']<=86400:
        raise ValueError('Evidence age must be between 60 and 86400 seconds')
    return dict(rule)


def evaluate(rule,device,*,now=None):
    """Return an explained result for one exact rule and inventory snapshot.

The caller owns policy identity, revision and assignment. This function evaluates
only evidence supplied for one device and never treats group membership as proof.
"""
    rule=validate_rule(rule)
    now=time.time() if now is None else now
    if not finite_time(now):
        raise ValueError('Evaluation time must be finite')
    result={'status':'unknown','reason':None,'evaluated_at':now,'collected_at':None,
            'inventory_sha256':None,'observed_versions':[], 'rule':rule}
    def finish(status,reason):
        return {**result,'status':status,'reason':reason}
    if not isinstance(device,dict) or device.get('revoked'):
        return finish('unknown','Device is revoked or unavailable')
    inventory=device.get('inventory')
    if not isinstance(inventory,dict):
        return finish('unknown','No inventory is available')
    try:
        result['inventory_sha256']=inventory_digest(inventory)
    except (ValueError,TypeError,OverflowError):
        return finish('unknown','Inventory cannot be evaluated')
    seen=device.get('seen')
    if not finite_time(seen) or seen<=0 or seen>now+300:
        return finish('unknown','Device check-in time is missing or invalid')
    if now-seen>rule['max_age_seconds']:
        return finish('unknown','Device check-in is older than the policy evidence limit')
    report=inventory.get('packages')
    if not isinstance(report,dict):
        return finish('unknown','No package inventory is available')
    collected=report.get('collected_at')
    if not finite_time(collected) or collected<=0 or collected>now+300:
        return finish('unknown','Package collection time is missing or invalid')
    result['collected_at']=collected
    try:
        checked=validate_report(report,now=now)
    except (ValueError,TypeError,OverflowError):
        return finish('unknown','Package inventory is malformed or inconsistent')
    if checked['manager']!=rule['manager']:
        return finish('unknown','The reported package manager does not match the policy')
    if checked['status']!='complete':
        return finish('unknown','Package collection is unsupported or failed')
    if now-collected>rule['max_age_seconds']:
        return finish('unknown','Package inventory is older than the policy evidence limit')
    versions=sorted({item['version'] for item in checked['items'] if item['name']==rule['package']})
    result['observed_versions']=versions
    if versions:
        return finish('compliant','The required package is present in fresh inventory')
    if checked['truncated']:
        return finish('unknown','The package is not in the reported subset; inventory is truncated')
    return finish('noncompliant','Complete fresh inventory does not contain the required package')
