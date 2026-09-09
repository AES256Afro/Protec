"""Opt-in Ed25519 signatures for leased inventory jobs with operator-pinned trust."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from protec.jobs import validate_envelope

DOMAIN=b'Protec inventory job signature v1\x00'


def origin(value):
    if not isinstance(value,str):raise ValueError('Invalid signing origin')
    url=urlsplit(value)
    if (not url.hostname or url.username or url.password or url.query or url.fragment or
            url.path not in ('','/') or any(c.isspace() for c in value) or
            (url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')))):
        raise ValueError('Signing trust requires an HTTPS origin or loopback HTTP')
    url.port
    return value.rstrip('/')


def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def decode(value,length):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise ValueError('Invalid signature encoding')
    try:raw=base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)
    except ValueError:raise ValueError('Invalid signature encoding') from None
    if len(raw)!=length or encode(raw)!=value:raise ValueError('Invalid signature length or encoding')
    return raw


def key_id(public):
    return hashlib.sha256(public).hexdigest()


def message(server,job):
    return DOMAIN+json.dumps({'server':origin(server),'job':job},sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate signing document field')
        result[key]=value
    return result


def protected_document(path):
    """Read the checked file descriptor, without following the final symlink."""
    if os.name!='posix':raise ValueError('Signing files require POSIX file protection in this release')
    path=Path(path)
    parent=path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.geteuid() or stat.S_IMODE(parent.st_mode)!=0o700:
        raise ValueError('Signing file directory must be owned by this user with mode 0700')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as file:
        info=os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or
                stat.S_IMODE(info.st_mode)!=0o600 or not 0<info.st_size<=16384):
            raise ValueError('Signing file must be a regular owner-only file with mode 0600 and bounded size')
        data=file.read(16385)
        if len(data)>16384:raise ValueError('Signing file is too large')
    return json.loads(data,object_pairs_hook=unique_object)


class Signer:
    def __init__(self,document):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if (not isinstance(document,dict) or set(document)!={'version','server','key_id','private_key'} or
                type(document['version']) is not int or document['version']!=1):
            raise ValueError('Invalid signing key document')
        self.server=origin(document['server'])
        self.private=Ed25519PrivateKey.from_private_bytes(decode(document['private_key'],32))
        self.identifier=key_id(self.private.public_key().public_bytes_raw())
        if document['key_id']!=self.identifier:raise ValueError('Signing key fingerprint mismatch')

    def sign(self,job):
        validate_envelope(job,job.get('device'))
        if job.get('version')!=1:raise ValueError('Only protocol-1 inventory jobs can be signed')
        return {'version':1,'algorithm':'Ed25519','key_id':self.identifier,
                'signature':encode(self.private.sign(message(self.server,job)))}

    @classmethod
    def load(cls,path):
        return cls(protected_document(path))


class Trust:
    def __init__(self,document,server):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        if (not isinstance(document,dict) or set(document)!={'version','server','keys'} or
                type(document['version']) is not int or document['version']!=1 or
                not isinstance(document['keys'],list) or not 1<=len(document['keys'])<=8):
            raise ValueError('Invalid job trust document')
        self.server=origin(document['server'])
        if self.server!=origin(server):raise ValueError('Job trust belongs to a different server')
        self.keys={}
        for entry in document['keys']:
            if not isinstance(entry,dict) or set(entry)!={'key_id','public_key'}:raise ValueError('Invalid trusted key entry')
            raw=decode(entry['public_key'],32)
            identifier=key_id(raw)
            if entry['key_id']!=identifier or identifier in self.keys:raise ValueError('Invalid or duplicate trusted key fingerprint')
            self.keys[identifier]=Ed25519PublicKey.from_public_bytes(raw)

    def verify(self,job,proof,device):
        from cryptography.exceptions import InvalidSignature
        validate_envelope(job,device)
        if (job.get('version')!=1 or not isinstance(proof,dict) or
                set(proof)!={'version','algorithm','key_id','signature'} or type(proof['version']) is not int or
                proof['version']!=1 or proof['algorithm']!='Ed25519' or not isinstance(proof['key_id'],str) or
                proof['key_id'] not in self.keys):
            raise ValueError('Missing, unsupported or untrusted job signature')
        try:self.keys[proof['key_id']].verify(decode(proof['signature'],64),message(self.server,job))
        except InvalidSignature:raise ValueError('Job signature verification failed') from None

    def verify_delivery(self,jobs,proofs,device,server):
        if origin(server)!=self.server:raise ValueError('Job trust belongs to a different server')
        if not isinstance(proofs,dict) or set(proofs)!={job['id'] for job in jobs} or len(proofs)!=len(jobs):
            raise ValueError('Missing or mismatched delivery signatures')
        for job in jobs:self.verify(job,proofs[job['id']],device)

    @classmethod
    def load(cls,path,server):
        return cls(protected_document(path),server)


def generate(directory,server):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    server=origin(server)
    if os.name!='posix':raise ValueError('Signing files require POSIX file protection in this release')
    private=Ed25519PrivateKey.generate()
    public=private.public_key().public_bytes_raw()
    identifier=key_id(public)
    documents={'signing-key.json':{'version':1,'server':server,'key_id':identifier,'private_key':encode(private.private_bytes_raw())},
               'job-trust.json':{'version':1,'server':server,'keys':[{'key_id':identifier,'public_key':encode(public)}]}}
    directory=Path(directory)
    directory.mkdir(mode=0o700) # New directory only; never overwrite an existing identity.
    for name,document in documents.items():
        descriptor=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'w') as file:
            json.dump(document,file,sort_keys=True);file.write('\n');file.flush();os.fsync(file.fileno())
    return identifier


def main():
    parser=argparse.ArgumentParser(description='Create an offline job signing key and public agent trust document')
    parser.add_argument('--directory',required=True,type=Path,help='New private directory; existing directories are refused')
    parser.add_argument('--server',required=True,help='Exact portal origin used by agents')
    args=parser.parse_args()
    try:
        identifier=generate(args.directory,args.server)
    except (ValueError,OSError,ImportError):
        raise SystemExit('Could not create signing files; check dependencies, origin and a new private output directory') from None
    print('Created signing-key.json and job-trust.json; public key fingerprint: '+identifier)


if __name__=='__main__':main()
