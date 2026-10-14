"""Local OAuth device login. Passwords are entered only on Yandex's website."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import json
import os
import secrets
import time
import threading
import tempfile
from contextlib import contextmanager,closing
import msvcrt
import requests

from runtime_paths import ROOT,DATA
AUTH=DATA/'auth_private.json'
DEVICE=DATA/'device_private.json'
# Public credentials documented in the reviewed Music API client, not user secrets.
CLIENT_ID='23cabbbdc6cd418abb4b39c32c41195d'
CLIENT_SECRET='53bc75238f0c4d08a118e51fe9203300'


def atomic_bytes(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,filename=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    temp=Path(filename)
    try:
        with os.fdopen(fd,'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
        for attempt in range(8):
            try:os.replace(temp,path);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.05*(attempt+1))
    finally:temp.unlink(missing_ok=True)


def write_private(path,data):
    atomic_bytes(path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))


class AuthRequired(RuntimeError):
    def __init__(self):super().__init__('Нужно снова войти в Яндекс или вставить новый токен в разделе «Аккаунт».')


AUTH_LOCK=threading.RLock()


@contextmanager
def auth_guard():
    with AUTH_LOCK,(DATA/'auth_worker.lock').open('a+b') as f:
        if f.seek(0,2)==0:f.write(b'0');f.flush()
        deadline=time.monotonic()+45
        while True:
            f.seek(0)
            try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('Вход уже выполняется. Повтори чуть позже.') from None
                time.sleep(.1)
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def read_auth():
    try:
        data=json.loads(AUTH.read_text(encoding='utf-8'))
        if not isinstance(data.get('access_token'),str) or not data['access_token']:raise ValueError()
        return data
    except (OSError,ValueError,KeyError):raise AuthRequired() from None


def access_token():return read_auth()['access_token']


def expected_uid():
    import sqlite3
    path=DATA/'music_state.db'
    if not path.exists():return None
    with closing(sqlite3.connect(path,timeout=30)) as c:
        row=c.execute("SELECT value FROM meta WHERE key='uid'").fetchone()
    return row[0] if row else None


def validate_token(token):
    if not isinstance(token,str) or not token or len(token)>4096 or any(x.isspace() for x in token):
        raise RuntimeError('Вставь только сам токен, без пробелов и префикса OAuth.')
    try:
        with requests.get('https://api.music.yandex.net/account/status',headers={'Authorization':'OAuth '+token,'X-Yandex-Music-Client':'YandexMusicAndroid/24023621'},timeout=(10,15),allow_redirects=False) as r:
            if r.status_code in (401,403):raise AuthRequired()
            if r.status_code!=200:raise RuntimeError('Проверка аккаунта: HTTP '+str(r.status_code))
            account=r.json()['result']['account']
    except requests.exceptions.RequestException as exc:raise RuntimeError('Не удалось проверить вход: '+type(exc).__name__) from None
    except (ValueError,KeyError,TypeError):raise RuntimeError('Неожиданный ответ при проверке аккаунта.') from None
    uid=str(account['uid']);previous=expected_uid()
    if previous and uid!=previous:raise RuntimeError('Это другой аккаунт. Войди в тот, из которого сохранено избранное. Текущий токен и музыка сохранены.')
    return {'uid':uid,'name':str(account.get('displayName') or 'Аккаунт Яндекса'),'checked_at':time.time()}


def save_token(token):
    with auth_guard():
        account=validate_token(token)
        write_private(AUTH,{'access_token':token,'saved_at':time.time(),'account':account})
        return account


def refresh(rejected_token):
    with auth_guard():
        data=read_auth()
        if data['access_token']!=rejected_token:return data['access_token']
        if not data.get('refresh_token'):raise AuthRequired()
        result=oauth('token',{'grant_type':'refresh_token','refresh_token':data['refresh_token'],'client_id':CLIENT_ID,'client_secret':CLIENT_SECRET})
        if 'access_token' not in result:raise AuthRequired()
        account=validate_token(result['access_token'])
        updated={**data,**result,'saved_at':time.time(),'account':account}
        write_private(AUTH,updated)
        return updated['access_token']


def oauth(endpoint,data):
    try:
        with requests.post('https://oauth.yandex.ru/'+endpoint,data=data,timeout=(10,20),allow_redirects=False) as r:
            if r.status_code not in (200,400): raise RuntimeError('Ошибка входа Яндекса: HTTP '+str(r.status_code))
            return r.json()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError('Сетевая ошибка входа: '+type(exc).__name__) from None


def request_code():
    data=oauth('device/code',{'client_id':CLIENT_ID,'device_id':secrets.token_hex(8),'device_name':'Music favourites backup on PC'})
    if not all(k in data for k in ('device_code','user_code','verification_url','expires_in')):
        raise RuntimeError('Яндекс не выдал код входа: '+str(data.get('error','неожиданный ответ')))
    u=urlsplit(data['verification_url'])
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or not (u.hostname in ('oauth.yandex.ru','oauth.yandex.com') or (u.hostname=='ya.ru' and u.path=='/device')):
        raise RuntimeError('Неожиданный адрес подтверждения входа.')
    data['expires_at']=time.time()+data['expires_in']
    write_private(DEVICE,data)
    return {k:data[k] for k in ('user_code','verification_url','expires_in')}


def poll():
    if not DEVICE.exists():return {'state':'idle'}
    data=json.loads(DEVICE.read_text(encoding='utf-8'))
    if time.time()>=data['expires_at']: return {'state':'expired'}
    result=oauth('token',{'grant_type':'device_code','code':data['device_code'],'client_id':CLIENT_ID,'client_secret':CLIENT_SECRET})
    if result.get('error')=='authorization_pending': return {'state':'waiting'}
    if result.get('error')=='slow_down':return {'state':'waiting','interval':10}
    if 'access_token' not in result:
        return {'state':'error','error':str(result.get('error','неожиданный ответ'))}
    with auth_guard():
        if not DEVICE.exists() or json.loads(DEVICE.read_text(encoding='utf-8'))['device_code']!=data['device_code']:
            return {'state':'idle'}
        account=validate_token(result['access_token'])
        result['saved_at']=time.time();result['account']=account
        write_private(AUTH,result)
        DEVICE.unlink(missing_ok=True)
    return {'state':'authorized','account':account}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('request','poll'));a=p.parse_args()
    try: print(json.dumps(request_code() if a.command=='request' else poll(),ensure_ascii=False))
    except Exception as exc:
        print(str(exc));raise SystemExit(1)
