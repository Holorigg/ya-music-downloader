"""Save lyrics supplied by the Music API, with an MP3 replacement journal."""
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
from mutagen.id3 import ID3,USLT
from auth import atomic_bytes
import music_export as m
from music_covers import audio_hash

CACHE=m.DATA/'lyrics_cache'
# Public request signature parameter from the reviewed Android API client.
SIGN_KEY=b'p93jhgh689SBReK6ghtw62'


def fetch(row):
    track=m.ident(row['id']);numeric=track.split(':')[0]
    formats=['LRC','TEXT'] if row.get('lyrics_sync') else ['TEXT']
    for fmt in formats:
        stamp=int(time.time())
        sign=base64.b64encode(hmac.new(SIGN_KEY,(numeric+str(stamp)).encode(),hashlib.sha256).digest()).decode('ascii')
        try:info=m.api('/tracks/'+track+'/lyrics',params={'format':fmt,'timeStamp':stamp,'sign':sign})
        except m.APIError as exc:
            if exc.code==404:continue
            raise
        if not info or not info.get('downloadUrl'):continue
        content=bytearray()
        with m.public_get(info['downloadUrl'],stream=True) as response:
            for chunk in response.iter_content(64*1024):
                if m.STOP.exists():return None
                content.extend(chunk)
                if len(content)>2*1024*1024:raise RuntimeError('Текст песни превышает допустимый размер.')
        try:text=bytes(content).decode('utf-8-sig').replace('\r\n','\n').strip()
        except UnicodeError:raise RuntimeError('Неподдерживаемая кодировка текста песни.') from None
        if not text:continue
        if '\x00' in text or re.match(r'(?is)\s*(<!doctype|<html|<script)',text):raise RuntimeError('Сервис выдал страницу вместо текста песни.')
        return {'format':fmt,'text':text,'provider':str((info.get('major') or {}).get('name') or ''),'writers':info.get('writers') or []}
    return None


def plain(data):
    if data['format']!='LRC':return data['text']
    lines=[]
    for line in data['text'].splitlines():
        if re.match(r'^\[(ar|al|ti|by|offset|length):',line,re.I):continue
        lines.append(re.sub(r'\[\d+:\d+(?:[.,]\d+)?\]','',line).strip())
    return '\n'.join(lines).strip()


def cache_path(row):return CACHE/(m.ident(row['id']).replace(':','_')+'.json')


def sidecars(path,data):
    contents={'.txt':plain(data)}
    if data['format']=='LRC':contents['.lrc']=data['text']
    for ext,text in contents.items():
        target=path.with_suffix(ext);content=(text+'\n').encode('utf-8')
        if target.exists():
            if target.read_bytes()!=content:raise RuntimeError('Рядом с MP3 уже есть другой текст. Он сохранён без перезаписи: '+target.name)
        else:atomic_bytes(target,content)


def prepare(source,target,data):
    before=audio_hash(source)
    shutil.copy2(source,target)
    tags=ID3(target,v2_version=3)
    previous={k:str(v) for k,v in tags.items() if k!='USLT:YandexLyrics:und'}
    tags.add(USLT(encoding=1,lang='und',desc='YandexLyrics',text=plain(data)))
    tags.save(target,v2_version=3)
    saved=ID3(target,v2_version=3)
    after={k:str(v) for k,v in saved.items() if k!='USLT:YandexLyrics:und'}
    if previous!=after or saved['USLT:YandexLyrics:und'].text!=plain(data) or audio_hash(target)!=before:
        raise RuntimeError('Проверка текста в MP3 не пройдена; исходный файл сохранён.')
    with target.open('r+b') as f:os.fsync(f.fileno())


def embed(row):
    if m.STOP.exists():return
    path=Path(row['path']).resolve()
    if not path.is_relative_to(m.DEST.resolve()):raise RuntimeError('Неожиданный путь музыкального файла.')
    cache=cache_path(row)
    data=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else fetch(row)
    if m.STOP.exists():return
    if data is None:
        with m.db() as c:c.execute("UPDATE tracks SET lyrics_status='unavailable',lyrics_error=NULL WHERE id=?",(row['id'],))
        return
    if not cache.exists():m.write_private(cache,data)
    current=m.checksum(path)
    if row.get('lyrics_new_sha') and current==row['lyrics_new_sha']:
        sidecars(path,data)
        with m.db() as c:c.execute("UPDATE tracks SET sha256=lyrics_new_sha,size=lyrics_new_size,lyrics_status='done',lyrics_format=?,lyrics_error=NULL,lyrics_new_sha=NULL,lyrics_new_size=NULL WHERE id=?",(data['format'],row['id']))
        return
    if current!=row['sha256'] or path.stat().st_size!=row['size']:raise RuntimeError('MP3 изменён после загрузки; он сохранён без перезаписи.')
    part=path.with_name(path.name+'.lyrics.part')
    if not (row.get('lyrics_new_sha') and part.exists() and m.checksum(part)==row['lyrics_new_sha']):
        prepare(path,part,data)
        with m.db() as c:c.execute('UPDATE tracks SET lyrics_new_sha=?,lyrics_new_size=? WHERE id=?',(m.checksum(part),part.stat().st_size,row['id']))
    sidecars(path,data)
    if m.checksum(path)!=current:raise RuntimeError('MP3 изменился во время добавления текста; он сохранён.')
    os.replace(part,path)
    with m.db() as c:c.execute("UPDATE tracks SET sha256=lyrics_new_sha,size=lyrics_new_size,lyrics_status='done',lyrics_format=?,lyrics_error=NULL,lyrics_new_sha=NULL,lyrics_new_size=NULL WHERE id=?",(data['format'],row['id']))
