"""Explicit one-off avatar update. Never print credentials, file IDs or private URLs."""
import argparse
import http.client
import json
import secrets
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--env',required=True)
parser.add_argument('--photo',required=True)
args=parser.parse_args()
try:
    values={}
    for line in Path(args.env).read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep: values[key.strip()]=value.strip().strip('\"\'')
    token=values['TELEGRAM_BOT_TOKEN']
    connection=http.client.HTTPSConnection('api.telegram.org',timeout=65)
    def call(method,body,content_type):
        connection.request('POST','/bot'+token+'/'+method,body,{'Content-Type':content_type})
        response=connection.getresponse()
        result=json.loads(response.read())
        if response.status>=400 or not result.get('ok'): raise ValueError('API rejected request')
        return result['result']
    me=call('getMe',b'{}','application/json')
    if me.get('username')!='whoofserveybot': raise ValueError('Wrong bot identity')
    photo=Path(args.photo).read_bytes()
    if not photo.startswith(b'\xff\xd8') or len(photo)>10_000_000: raise ValueError('Expected JPEG')
    boundary='whoof-'+secrets.token_hex(16)
    info=json.dumps({'type':'static','photo':'attach://avatar'})
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"\r\n\r\n{info}\r\n'
          f'--{boundary}\r\nContent-Disposition: form-data; name="avatar"; filename="whoof.jpg"\r\n'
          'Content-Type: image/jpeg\r\n\r\n').encode()+photo+f'\r\n--{boundary}--\r\n'.encode()
    if call('setMyProfilePhoto',body,'multipart/form-data; boundary='+boundary) is not True:
        raise ValueError('Avatar was not accepted')
    result=call('getUserProfilePhotos',json.dumps({'user_id':me['id'],'limit':1}).encode(),'application/json')
    if not result.get('photos'): raise ValueError('Avatar verification failed')
    connection.close()
    print('Whoof bot profile photo updated and verified; no participant messages sent.')
except Exception as error:
    print('Avatar setup failed ('+type(error).__name__+'); no credential details printed.')
    raise SystemExit(1)
