"""Embed official cover images without changing compressed audio packets."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import threading
from mutagen.id3 import ID3,APIC,PictureType
import music_export as m

CACHE=m.DATA/'cover_cache'
LOCK=threading.RLock()
URI_LOCKS={}


def mime(data):
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    raise RuntimeError('Сервис выдал неподдерживаемый формат обложки.')


def image(uri):
    url=uri if uri.startswith('https://') else 'https://'+uri
    url=m.allowed(url.replace('%%','400x400'))
    key=hashlib.sha256(url.encode()).hexdigest()
    with LOCK:lock=URI_LOCKS.setdefault(key,threading.Lock())
    with lock:
        CACHE.mkdir(parents=True,exist_ok=True)
        path=CACHE/(key+'.image')
        if path.exists():data=path.read_bytes();return data,mime(data)
        try:
            with m.public_get(url,stream=True) as response:
                data=bytearray()
                for chunk in response.iter_content(64*1024):
                    data.extend(chunk)
                    if len(data)>5*1024*1024:raise RuntimeError('Обложка слишком большая.')
        except m.requests.exceptions.RequestException as exc:
            raise RuntimeError('Сетевая ошибка обложки: '+type(exc).__name__) from None
        data=bytes(data);kind=mime(data)
        part=path.with_suffix('.part')
        try:
            part.write_bytes(data)
            info=json.loads(m.command([m.media_tool('ffprobe'),'-v','error','-show_streams','-of','json',str(part)]))
            video=[s for s in info['streams'] if s.get('codec_type')=='video']
            if len(video)!=1 or not (1<=video[0].get('width',0)<=4096 and 1<=video[0].get('height',0)<=4096):
                raise RuntimeError('Некорректная картинка обложки.')
            os.replace(part,path)
        finally:part.unlink(missing_ok=True)
        return data,kind


def audio_hash(path):
    return m.command([m.media_tool('ffmpeg'),'-v','error','-nostdin','-i',str(path),'-map','0:a:0','-c:a','copy','-f','hash','-hash','sha256','-']).strip()


def prepare(source,target,uri):
    data,kind=image(uri)
    before=audio_hash(source)
    shutil.copy2(source,target)
    tags=ID3(target,v2_version=3)
    previous={key:str(value) for key,value in tags.items() if not key.startswith('APIC')}
    tags.setall('APIC',[APIC(encoding=1,mime=kind,type=PictureType.COVER_FRONT,desc='Cover',data=data)])
    tags.save(target,v2_version=3)
    saved=ID3(target,v2_version=3)
    after={key:str(value) for key,value in saved.items() if not key.startswith('APIC')}
    pictures=saved.getall('APIC')
    if previous!=after or len(pictures)!=1 or pictures[0].data!=data or audio_hash(target)!=before:
        raise RuntimeError('Проверка добавления обложки не пройдена; исходный MP3 сохранён.')
    with target.open('r+b') as handle:os.fsync(handle.fileno())


def add_picture(path,uri):
    part=path.with_name(path.name+'.cover.part')
    original=m.checksum(path)
    try:
        prepare(path,part,uri)
        if m.checksum(path)!=original:raise RuntimeError('MP3 изменился во время добавления обложки.')
        os.replace(part,path)
    finally:part.unlink(missing_ok=True)


def embed(row):
    path=Path(row['path']).resolve()
    if not path.is_relative_to(m.DEST.resolve()):raise RuntimeError('Неожиданный путь музыкального файла.')
    current=m.checksum(path)
    if row.get('cover_new_sha') and current==row['cover_new_sha']:
        # Recover a crash after file replacement but before the DB commit.
        with m.db() as c:c.execute("UPDATE tracks SET sha256=cover_new_sha,size=cover_new_size,cover_status='done',cover_error=NULL,cover_new_sha=NULL,cover_new_size=NULL WHERE id=?",(row['id'],))
        return
    if current!=row['sha256'] or path.stat().st_size!=row['size']:
        raise RuntimeError('MP3 изменён после загрузки; файл сохранён без перезаписи.')
    part=path.with_name(path.name+'.cover.part')
    if not (row.get('cover_new_sha') and part.is_file() and m.checksum(part)==row['cover_new_sha']):
        prepare(path,part,row['cover_uri'])
        newsha=m.checksum(part);newsize=part.stat().st_size
        with m.db() as c:c.execute('UPDATE tracks SET cover_new_sha=?,cover_new_size=? WHERE id=?',(newsha,newsize,row['id']))
    if m.checksum(path)!=current:raise RuntimeError('MP3 изменился во время добавления обложки; он сохранён.')
    os.replace(part,path)
    with m.db() as c:c.execute("UPDATE tracks SET sha256=cover_new_sha,size=cover_new_size,cover_status='done',cover_error=NULL,cover_new_sha=NULL,cover_new_size=NULL WHERE id=?",(row['id'],))


def fetch_metadata():
    with m.db() as c:ids=[r[0] for r in c.execute('SELECT id FROM tracks ORDER BY position')]
    for i in range(0,len(ids),100):
        tracks=m.api('/tracks',{'track-ids':','.join(ids[i:i+100])})
        found={str(t['id']):t for t in tracks}
        with m.db() as c:
            for ident in ids[i:i+100]:
                data=found.get(ident) or found.get(ident.split(':')[0]) or {}
                uri=data.get('coverUri')
                c.execute("UPDATE tracks SET cover_uri=?,cover_status=CASE WHEN ? IS NULL THEN 'unavailable' WHEN cover_status='unavailable' THEN 'pending' ELSE cover_status END WHERE id=?",(uri,uri,ident))
