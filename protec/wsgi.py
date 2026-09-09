"""Deployment adapter. Keep one route and authorization implementation for all installs."""
from email.message import Message
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import secrets
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from protec.server import Handler, Store


def public_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or
            parsed.username or parsed.password or parsed.path not in ('','/') or
            parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError('PROTEC_PUBLIC_URL must be an absolute origin without a path')
    if parsed.scheme != 'https' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Remote deployments require an HTTPS public URL')
    # Accessing port validates malformed or out-of-range values.
    parsed.port
    return value.rstrip('/')


class RequestHandler(Handler):
    def __init__(self, environ, context):
        self.server = context
        self.path = environ.get('PATH_INFO','/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_','-')] = value
        for name in ('CONTENT_TYPE','CONTENT_LENGTH'):
            if environ.get(name):
                self.headers[name.replace('_','-')] = environ[name]
        self.rfile = environ['wsgi.input']

    def reply(self, status, value, content_type='application/json'):
        self.status = status
        self.data = json.dumps(value).encode() if content_type=='application/json' else value
        self.response_headers = [
            ('Content-Type',content_type), ('Content-Length',str(len(self.data))),
            ('Cache-Control','no-store'), ('X-Content-Type-Options','nosniff'),
            ('Referrer-Policy','no-referrer'),
            ('Content-Security-Policy',"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
        ]


def create_app(data=None, public_url=None, admin_token=None, job_signing_key=None):
    os.umask(0o077)
    directory = Path(data or os.environ.get('PROTEC_DATA','/data'))
    origin = public_origin(public_url or os.environ.get('PROTEC_PUBLIC_URL','http://127.0.0.1:8765'))
    directory.mkdir(parents=True,mode=0o700,exist_ok=True)
    directory.chmod(0o700)
    token_path = directory/'admin-token'
    token = admin_token or os.environ.get('PROTEC_ADMIN_TOKEN')
    if not token:
        try:
            # Exclusive creation avoids overwriting identity on worker restart.
            with token_path.open('x') as output:
                output.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = token_path.read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):
        raise ValueError('Administrator token must contain 32 to 128 URL-safe characters')
    signer=None
    signing_path=job_signing_key or os.environ.get('PROTEC_JOB_SIGNING_KEY')
    if signing_path:
        from protec.job_signatures import Signer
        signer=Signer.load(signing_path)
        if signer.server!=origin:
            raise ValueError('Signing key origin must match PROTEC_PUBLIC_URL')
    context = SimpleNamespace(store=Store(directory/'protec.db',signer),admin_token=token,
                              public_url=origin,started=time.monotonic())

    def application(environ, start_response):
        handler = RequestHandler(environ,context)
        method = environ.get('REQUEST_METHOD','GET')
        if method in ('GET','POST'):
            getattr(handler,'do_'+method)()
        elif method=='HEAD':
            handler.do_GET()
        else:
            handler.reply(405,{'error':'Method not allowed'})
        start_response(f'{handler.status} {HTTPStatus(handler.status).phrase}',handler.response_headers)
        return [] if method=='HEAD' else [handler.data]
    return application
