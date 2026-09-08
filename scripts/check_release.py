"""Verify a public demo against a container release without exposing credentials.

Usage: python3 scripts/check_release.py --revision COMMIT --site https://example.com
Run from a checkout containing the deployed commit. Requires curl and Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision',required=True,help='Full revision label of the running container')
    parser.add_argument('--site',default='https://foragefournuts.com')
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}',args.revision):
        parser.error('Use the full 40-character source revision')
    url=urlsplit(args.site)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','') or url.query or url.fragment:
        parser.error('Use an HTTPS site origin without credentials or a path')
    release=json.loads(subprocess.check_output(['curl','--fail','--silent','--show-error','--max-time','20',args.site+'/release.json']))
    expected=hashlib.sha256(subprocess.check_output(['git','show',args.revision+':static/app.js'],cwd=ROOT)).hexdigest()
    deployed=hashlib.sha256(subprocess.check_output(['curl','--fail','--silent','--show-error','--max-time','20',args.site+'/demo/app.js'])).hexdigest()
    if release.get('revision')!=args.revision or release.get('dashboard_sha256')!=expected or deployed!=expected or release.get('mode')!='mock-data-only':
        raise SystemExit('Release mismatch: demo metadata or dashboard differs from the deployed container revision')
    print('Demo source revision and served dashboard match '+args.revision)

if __name__=='__main__':
    main()
