"""Root-only credential setup in VNC; input is hidden and never echoed."""
import base64
import argparse
import getpass
import json
import os
from pathlib import Path

if os.geteuid()!=0:
    raise SystemExit('Run as root')
parser=argparse.ArgumentParser()
parser.add_argument('--answers-id',required=True)
parser.add_argument('--contacts-id',required=True)
args=parser.parse_args()
import re
if (not all(re.fullmatch(r'[A-Za-z0-9_-]{20,100}',v) for v in (args.answers_id,args.contacts_id))
    or args.answers_id==args.contacts_id):
    raise SystemExit('Two distinct spreadsheet IDs required')
directory=Path('/etc/whoof-sheets-sync')
key=directory/'google-key.json'
if key.exists():
    raise SystemExit('Credential already exists; refusing to overwrite')
encoded=getpass.getpass('Google key JSON, base64 (hidden): ')
try:
    data=base64.b64decode(encoded,validate=True)
    parsed=json.loads(data)
    if (parsed.get('type')!='service_account' or not parsed.get('client_email','').endswith('.iam.gserviceaccount.com')
        or parsed.get('token_uri')!='https://oauth2.googleapis.com/token'
        or not parsed.get('private_key','').startswith('-----BEGIN PRIVATE KEY-----')):
        raise ValueError('Wrong key format')
except (ValueError,TypeError):
    raise SystemExit('Invalid credential; nothing saved')
directory.mkdir(mode=0o700,exist_ok=True)
os.chmod(directory,0o700)
with os.fdopen(os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:
    stream.write(data)
env=Path('/etc/whoof-sheets-sync.env')
if not env.exists():
    with os.fdopen(os.open(env,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
        stream.write('GOOGLE_APPLICATION_CREDENTIALS=/etc/whoof-sheets-sync/google-key.json\n')
        stream.write('WHOOF_ANSWERS_ID='+args.answers_id+'\nWHOOF_CONTACTS_ID='+args.contacts_id+'\n')
print('Google credential saved privately; no credential values printed.')
