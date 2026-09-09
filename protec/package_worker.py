"""Root-only single-request package worker. Remote submission remains disabled."""
import argparse
import fcntl
import os
from pathlib import Path
import re
import sys
from protec.agent_receipts import ReceiptJournal
from protec.job_signatures import protected_document,Trust,origin
from protec.package_changes import load_policy,run_change

DEFAULT_DIRECTORY=Path('/var/lib/protec-package-worker')


def execute(directory=DEFAULT_DIRECTORY):
    if os.geteuid()!=0:raise ValueError('Package worker requires root')
    directory=Path(directory)
    # Every input is a protected local document. Jobs cannot choose policy,
    # trust, identity, interpreter, journal or command paths.
    config=protected_document(directory/'worker.json')
    if (not isinstance(config,dict) or set(config)!={'version','server','device'} or
            type(config['version']) is not int or config['version']!=1 or
            not isinstance(config['device'],str) or not re.fullmatch('[0-9a-f]{24}',config['device'])):
        raise ValueError('Invalid local worker identity')
    server=origin(config['server'])
    trust=Trust.load(directory/'job-trust.json',server)
    policy=load_policy(directory/'package-policy.json')
    # Lock the already-protected config inode without changing it. Provisioning
    # must stop the service before replacing local configuration.
    descriptor=os.open(directory/'worker.json',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        request=protected_document(directory/'request.json')
        if not isinstance(request,dict) or set(request)!={'job','proof'}:
            raise ValueError('Invalid local worker request')
        journal=ReceiptJournal(directory/'receipts',server,config['device'])
        return run_change(request['job'],request['proof'],config['device'],trust,policy,journal)
    finally:
        os.close(descriptor)


def main():
    parser=argparse.ArgumentParser(description='Run one locally provisioned signed package request')
    parser.add_argument('--directory',type=Path,default=DEFAULT_DIRECTORY)
    args=parser.parse_args()
    try:
        result=execute(args.directory)
    except (ValueError,OSError,RuntimeError):
        print('Package worker refused or interrupted; inspect the protected local journal.',file=sys.stderr)
        return 1
    # Do not echo input, signature, lease, native output or package observations.
    return 0 if result['outcome']=='succeeded' else 1


if __name__=='__main__':raise SystemExit(main())
