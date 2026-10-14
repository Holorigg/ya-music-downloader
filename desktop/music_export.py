"""Read a user's Music favourites and save available full MP3 streams locally."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from urllib.parse import urlsplit,urljoin
import argparse
import csv
import hashlib
import json
import io
import msvcrt
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
import requests
from auth import AUTH,ROOT,write_private,atomic_bytes,AuthRequired,access_token,refresh
import settings
from runtime_paths import DATA,media_tool

DEST=settings.destination()
DB=DATA/'music_state.db'
STATUS=DATA/'music_status.json'
STOP=DATA/'STOP_MUSIC'
TOOLS=ROOT/'tools'
API='https://api.music.yandex.net'
SALT='XGRlBW9FXlekgbPrRHuSiA'
LOCK=threading.RLock()
STATE='ready';MESSAGE='Готово к запуску';PASS=0
WORK_TOTAL=0;WORK_COMPLETED=0


@contextmanager
def db():
    c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row
    try: yield c;c.commit()
    finally: c.close()


@contextmanager
def worker_lock():
    with (DATA/'music_worker.lock').open('a+b') as f:
        if f.seek(0,2)==0:f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('Загрузчик музыки уже работает.') from None
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def worker_running():
    try:
        with worker_lock():pass
        return False
    except RuntimeError:return True


def initialize():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript("""CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS tracks(id TEXT PRIMARY KEY,position INTEGER,title TEXT,artist TEXT,album TEXT,year TEXT,
        duration_ms INTEGER,available INTEGER,status TEXT DEFAULT 'pending',path TEXT,size INTEGER,sha256 TEXT,bitrate INTEGER,error TEXT);""")
        columns={r[1] for r in c.execute('PRAGMA table_info(tracks)')}
        for field,definition in (('cover_uri','TEXT'),('cover_status',"TEXT DEFAULT 'pending'"),('cover_error','TEXT'),('cover_new_sha','TEXT'),('cover_new_size','INTEGER'),('liked','INTEGER DEFAULT 1'),('archive_hidden','INTEGER NOT NULL DEFAULT 0'),('lyrics_available','INTEGER'),('lyrics_sync','INTEGER'),('lyrics_status',"TEXT DEFAULT 'pending'"),('lyrics_error','TEXT'),('lyrics_format','TEXT'),('lyrics_new_sha','TEXT'),('lyrics_new_size','INTEGER'),('download_new_sha','TEXT'),('download_new_size','INTEGER'),('download_new_bitrate','INTEGER')):
            if field not in columns:c.execute('ALTER TABLE tracks ADD COLUMN '+field+' '+definition)


def status(message=None,state=None):
    global MESSAGE,STATE
    with LOCK:
        if message is not None:MESSAGE=message;print(message,flush=True)
        if state is not None:STATE=state
        with db() as c:
            groups=[dict(r) for r in c.execute('SELECT status,COUNT(*) AS count,COALESCE(SUM(size),0) AS bytes FROM tracks GROUP BY status')]
        try:
            write_private(STATUS,{'state':STATE,'message':MESSAGE,'groups':groups,'pass':PASS,'workers':2,'destination':str(DEST),'updated':time.time(),'work_total':WORK_TOTAL,'work_completed':WORK_COMPLETED})
        except OSError as exc:
            # A Windows reader can temporarily block replacement; SQLite still
            # holds verified progress. Status failure must not abort audio work.
            print('Снимок прогресса временно недоступен: '+type(exc).__name__,flush=True)


class APIError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__('Music API: HTTP '+str(code))


def api(endpoint,data=None,params=None):
    token=access_token();renewed=False
    for attempt in range(3):
        try:
            with requests.request('GET' if data is None else 'POST',API+endpoint,data=data,params=params,
                 headers={'Authorization':'OAuth '+token,'X-Yandex-Music-Client':'YandexMusicAndroid/24023621'},
                 timeout=(10,15),allow_redirects=False) as r:
                if r.status_code==401:
                    if renewed:raise AuthRequired()
                    token=refresh(token);renewed=True;continue
                if r.status_code==403 and endpoint=='/account/status':raise AuthRequired()
                if r.status_code==429 or r.status_code>=500:
                    if attempt<2:time.sleep(2*(attempt+1));continue
                if r.status_code!=200:raise APIError(r.status_code)
                result=r.json()
                if 'error' in result:raise RuntimeError('Music API не выдал запрошенные данные.')
                return result['result']
        except (requests.exceptions.RequestException,ValueError,KeyError) as exc:
            if attempt==2:raise RuntimeError('Сетевая ошибка Music API: '+type(exc).__name__) from None
            time.sleep(1)
    raise AuthRequired()


def ident(value):
    value=str(value)
    if not re.fullmatch(r'[0-9]+(?::[0-9]+)?',value):raise RuntimeError('Неожиданный ID трека.')
    return value


def catalog():
    account=api('/account/status')['account'];uid=ident(account['uid'])
    with db() as c:
        previous=c.execute("SELECT value FROM meta WHERE key='uid'").fetchone()
        if previous and previous[0]!=uid:raise RuntimeError('В базе другой аккаунт. Его архив сохранён; нужен отдельный экспорт.')
        c.execute("INSERT OR REPLACE INTO meta VALUES ('uid',?)",(uid,))
    liked=api('/users/'+uid+'/likes/tracks')
    liked=(liked.get('library') or liked)['tracks']
    ids=list(dict.fromkeys(ident(t['id']) for t in liked));all_metadata={}
    for offset in range(0,len(ids),100):
        if STOP.exists():return False
        batch=ids[offset:offset+100]
        all_metadata.update({str(t['id']):t for t in api('/tracks',{'track-ids':','.join(batch)})})
        status(f'Проверяю избранное: {min(offset+100,len(ids))} из {len(ids)}.','cataloging')
    if STOP.exists():return False
    # Commit likes only after a complete response; a network failure cannot
    # turn a partial catalogue into removals. Unliked local files are retained.
    with db() as c:
        c.execute('UPDATE tracks SET liked=0')
        for n,trackid in enumerate(ids):
            t=all_metadata.get(trackid) or all_metadata.get(trackid.split(':')[0])
            if not t:
                c.execute("INSERT INTO tracks(id,position,title,status,error,liked,available) VALUES (?,?,?,'unavailable',?,1,0) ON CONFLICT(id) DO UPDATE SET liked=1,archive_hidden=0,position=excluded.position",(trackid,n,trackid,'Метаданные трека недоступны.'))
                continue
            albums=t.get('albums') or [{}]
            artist=', '.join(str(x.get('name','')) for x in t.get('artists',[]))
            available=bool(t.get('available') or t.get('availableForPremiumUsers'))
            c.execute("""INSERT INTO tracks(id,position,title,artist,album,year,duration_ms,available,status,liked) VALUES (?,?,?,?,?,?,?,?,?,1)
                 ON CONFLICT(id) DO UPDATE SET position=excluded.position,title=excluded.title,artist=excluded.artist,
                 album=excluded.album,year=excluded.year,duration_ms=excluded.duration_ms,available=excluded.available,liked=1,archive_hidden=0,
                 status=CASE WHEN tracks.status='downloaded' THEN 'downloaded' WHEN excluded.available=0 THEN 'unavailable' WHEN tracks.status='unavailable' THEN 'pending' ELSE tracks.status END""",
                 (trackid,n,t.get('title',trackid),artist,albums[0].get('title',''),str(albums[0].get('year') or ''),t.get('durationMs') or 0,available,'pending' if available else 'unavailable'))
            lyrics=t.get('lyricsInfo') or {}
            has_text=lyrics.get('hasAvailableTextLyrics');has_sync=lyrics.get('hasAvailableSyncLyrics')
            c.execute("UPDATE tracks SET cover_uri=?,cover_status=CASE WHEN cover_status='unavailable' AND ? IS NOT NULL THEN 'pending' ELSE cover_status END,lyrics_available=?,lyrics_sync=?,lyrics_status=CASE WHEN lyrics_status='unavailable' AND (COALESCE(lyrics_available,0)=0 AND COALESCE(lyrics_sync,0)=0) AND (?=1 OR ?=1) THEN 'pending' ELSE lyrics_status END WHERE id=?",(t.get('coverUri'),t.get('coverUri'),has_text,has_sync,has_text,has_sync,trackid))
        c.execute("INSERT OR REPLACE INTO meta VALUES('catalog_updated',?)",(str(time.time()),))
    return True


def allowed(url):
    u=urlsplit(url);host=(u.hostname or '').lower()
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or not any(host==d or host.endswith('.'+d) for d in ('yandex.net','yandex.ru')):
        raise RuntimeError('Неожиданный сервер аудиофайла.')
    return url


def public_get(url,stream=False):
    for _ in range(6):
        allowed(url)
        try:r=requests.get(url,timeout=(10,10),stream=stream,allow_redirects=False,headers={'Accept-Encoding':'identity'})
        except requests.exceptions.RequestException as exc:raise RuntimeError('Сетевая ошибка аудиофайла: '+type(exc).__name__) from None
        if r.status_code in (301,302,303,307,308):
            nexturl=urljoin(url,r.headers.get('Location',''));r.close();url=nexturl;continue
        if r.status_code!=200:
            code=r.status_code;r.close();raise RuntimeError('Аудиофайл: HTTP '+str(code))
        return r
    raise RuntimeError('Слишком много перенаправлений аудиофайла.')


def direct(info):
    with public_get(info['downloadInfoUrl']) as r:
        xml=ET.fromstring(r.content)
    values={k:xml.findtext(k) for k in ('host','path','ts','s')}
    if not all(values.values()):raise RuntimeError('Нет полной ссылки MP3.')
    sign=hashlib.md5((SALT+values['path'][1:]+values['s']).encode()).hexdigest()
    return allowed('https://'+values['host']+'/get-mp3/'+sign+'/'+values['ts']+values['path'])


def checksum(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def name(row):
    value=re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',row['artist']+' - '+row['title']).strip(' .')[:120].rstrip(' .')
    return (value or 'Track')+'__'+row['id'].replace(':','_')+'.mp3'


def command(args):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('Аудиофайл не прошёл проверку FFmpeg.')
    return result.stdout


def validate(path,row):
    data=json.loads(command([media_tool('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',str(path)]))
    audio=[s for s in data['streams'] if s.get('codec_type')=='audio']
    duration=float(data['format'].get('duration',0));expected=row['duration_ms']/1000
    if len(audio)!=1 or audio[0].get('codec_name')!='mp3' or not expected or abs(duration-expected)>max(2,expected*.015):
        raise RuntimeError('Сохранённый файл не является полным MP3 нужной длительности.')
    command([media_tool('ffmpeg'),'-v','error','-xerror','-nostdin','-i',str(path),'-map','0:a:0','-f','null','-'])
    return duration


def complete_mp3_frames(path):
    """Check physical MPEG frame boundaries; decoders may ignore a cut tail."""
    with path.open('rb') as handle:
        length=path.stat().st_size;header=handle.read(10);start=0;end=length
        if header[:3]==b'ID3':
            if len(header)!=10 or any(x&128 for x in header[6:10]):return False
            start=10+sum(x<<(7*(3-i)) for i,x in enumerate(header[6:10]))
            if header[3]==4 and header[5]&16:start+=10
        if end>=128:
            handle.seek(end-128)
            if handle.read(3)==b'TAG':end-=128
        if end>=32:
            handle.seek(end-32);footer=handle.read(16)
            if footer[:8]==b'APETAGEX':
                size=int.from_bytes(footer[12:16],'little')
                if not 32<=size<end-start:return False
                end-=size
        at=start;frames=0;v1=(0,32,40,48,56,64,80,96,112,128,160,192,224,256,320);v2=(0,8,16,24,32,40,48,56,64,80,96,112,128,144,160)
        while at<end:
            handle.seek(at);data=handle.read(4)
            if len(data)!=4:return False
            bits=int.from_bytes(data,'big');version=(bits>>19)&3;layer=(bits>>17)&3;bitrate=(bits>>12)&15;rate=(bits>>10)&3
            if bits&0xffe00000!=0xffe00000 or version==1 or layer!=1 or bitrate in (0,15) or rate==3:return False
            hz=(44100,48000,32000)[rate]//(1 if version==3 else 2 if version==2 else 4)
            size=(144000 if version==3 else 72000)*(v1 if version==3 else v2)[bitrate]//hz+((bits>>9)&1)
            if size<4 or at+size>end:return False
            at+=size;frames+=1
        return frames>0 and at==end


def reuse_existing(row,target,uid):
    """Restore an existing export read-only; retain any known hash baseline."""
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    from mutagen import MutagenError
    if not target.is_file() or target.is_symlink():return False
    if not target.resolve().is_relative_to(DEST.resolve()):return False
    before=target.stat();sha=checksum(target)
    tracked=bool(row.get('path') or row.get('sha256') or row.get('download_new_sha'))
    if tracked:
        if (not row.get('path') or not row.get('sha256') or
                Path(row['path']).resolve()!=target.resolve() or
                before.st_size!=row.get('size') or sha!=row['sha256']):return False
        cover=row.get('cover_status') or 'pending';lyrics=row.get('lyrics_status') or 'pending'
        bitrate=row.get('bitrate')
    else:
        if target.name!=name(row) or target.parent.resolve()!=(DEST/('account_'+uid)).resolve():return False
        if not row.get('title') or not row.get('artist') or not row.get('duration_ms'):return False
        # Legacy exports have no ownership record in a fresh profile. Require
        # their exact ID-bearing name, identity tags and a complete decoded MP3.
        with target.open('rb') as handle:
            header=handle.read(10)
        if len(header)!=10 or header[:3]!=b'ID3' or any(x&128 for x in header[6:10]):return False
        tag_size=sum(x<<(7*(3-i)) for i,x in enumerate(header[6:10]))
        if tag_size>16*1024*1024:return False
        def normalized(value):return unicodedata.normalize('NFC',str(value or '')).strip()
        try:
            tags=ID3(target)
            if any(normalized(tags.get(key))!=normalized(row.get(field)) for key,field in
                    (('TIT2','title'),('TPE1','artist'),('TALB','album'))):return False
            if not complete_mp3_frames(target):return False
            media_tool('ffprobe');media_tool('ffmpeg')
            validate(target,row)
            bitrate=round(MP3(target).info.bitrate/1000)
            cover='done' if tags.getall('APIC') else 'pending'
            lyrics='done' if tags.getall('USLT') else 'pending'
        except (OSError,ValueError,RuntimeError,MutagenError,KeyError):return False
    after=target.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):return False
    if checksum(target)!=sha:return False
    if STOP.exists():return False
    with db() as c:c.execute("UPDATE tracks SET status='downloaded',path=?,size=?,sha256=?,bitrate=?,error=NULL,cover_status=?,lyrics_status=? WHERE id=?",
                            (str(target.resolve()),after.st_size,sha,bitrate,cover,lyrics,row['id']))
    return True


def download(row):
    with db() as c:uid=c.execute("SELECT value FROM meta WHERE key='uid'").fetchone()[0]
    target=Path(row['path']) if row.get('path') else DEST/('account_'+uid)/name(row)
    if not target.resolve().is_relative_to(DEST.resolve()):raise RuntimeError('Путь трека вне выбранной папки.')
    if target.is_symlink():raise RuntimeError('По этому пути находится ссылка. Она сохранена без изменений.')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if row.get('download_new_sha') and target.stat().st_size==row['download_new_size'] and checksum(target)==row['download_new_sha']:
            with db() as c:c.execute("UPDATE tracks SET status='downloaded',path=?,sha256=download_new_sha,size=download_new_size,bitrate=download_new_bitrate,error=NULL,download_new_sha=NULL,download_new_size=NULL,download_new_bitrate=NULL WHERE id=?",(str(target),row['id']))
            return True
        if row['status']=='downloaded' and row['path']==str(target) and target.stat().st_size==row['size'] and checksum(target)==row['sha256']:return True
        if reuse_existing(row,target,uid):return True
        if STOP.exists():return False
        raise RuntimeError('По этому пути уже есть файл. Он сохранён без перезаписи.')
    if shutil.disk_usage(DEST).free<512*1024*1024:raise RuntimeError('Недостаточно места в выбранной папке.')
    options=api('/tracks/'+ident(row['id'])+'/download-info')
    options=[x for x in options if x.get('codec')=='mp3' and x.get('preview') is False]
    if not options:raise RuntimeError('API не выдал доступный полный MP3 этого трека.')
    info=max(options,key=lambda x:x.get('bitrateInKbps',0))
    raw=target.with_name(target.name+'.download.part');tagged=target.with_name(target.name+'.tagged.part')
    try:
        with public_get(direct(info),stream=True) as r,raw.open('wb') as f:
            expected=int(r.headers.get('Content-Length','0'));count=0
            for chunk in r.iter_content(64*1024):
                if STOP.exists():return False
                if chunk:count+=len(chunk);f.write(chunk)
            f.flush();os.fsync(f.fileno())
        if not count or (expected and count!=expected):raise RuntimeError('Аудиофайл загружен не полностью.')
        validate(raw,row)
        cmd=[media_tool('ffmpeg'),'-v','error','-nostdin','-y','-i',str(raw),'-map','0:a:0','-c:a','copy','-id3v2_version','3']
        for key in ('title','artist','album','year'):
            cmd+=['-metadata',('date' if key=='year' else key)+'='+str(row[key]).replace('\0','')]
        command(cmd+['-f','mp3',str(tagged)])
        validate(tagged,row)
        cover_state='pending';cover_error=None
        if row.get('cover_uri'):
            try:
                from music_covers import add_picture
                add_picture(tagged,row['cover_uri'])
                cover_state='done'
            except Exception as exc:cover_state='failed';cover_error=str(exc)[:500]
        with tagged.open('r+b') as f:os.fsync(f.fileno())
        sha=checksum(tagged);size=tagged.stat().st_size
        with db() as c:c.execute('UPDATE tracks SET download_new_sha=?,download_new_size=?,download_new_bitrate=? WHERE id=?',(sha,size,info.get('bitrateInKbps'),row['id']))
        os.rename(tagged,target)
        if checksum(target)!=sha:raise RuntimeError('Сохранённый файл не прошёл проверку после записи.')
        with db() as c:c.execute("UPDATE tracks SET status='downloaded',path=?,size=?,sha256=?,bitrate=?,error=NULL,cover_status=?,cover_error=?,download_new_sha=NULL,download_new_size=NULL,download_new_bitrate=NULL WHERE id=?",(str(target),size,sha,info.get('bitrateInKbps'),cover_state,cover_error,row['id']))
        return True
    except requests.exceptions.RequestException as exc:
        raise RuntimeError('Сетевая ошибка аудиофайла: '+type(exc).__name__) from None
    finally:
        raw.unlink(missing_ok=True);tagged.unlink(missing_ok=True)


def export_lists():
    with db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM tracks ORDER BY position')]
    DEST.mkdir(parents=True,exist_ok=True)
    with io.StringIO() as f:
        f.write('#EXTM3U\n')
        for r in rows:
            if r['status']=='downloaded' and r['liked'] and Path(r['path']).is_file():
                try:relative=os.path.relpath(r['path'],DEST).replace('\\','/')
                except ValueError:relative=Path(r['path']).as_posix()
                f.write(relative.replace('\r','').replace('\n','')+'\n')
        atomic_bytes(DEST/'Мне_нравится.m3u8',f.getvalue().encode('utf-8'))
    with io.StringIO(newline='') as f:
        w=csv.writer(f);w.writerow(['ID','Исполнитель','Название','Статус','Битрейт','Путь','Ошибка','В избранном','Текст'])
        for r in rows:
            values=[r[k] for k in ('id','artist','title','status','bitrate','path','error','liked','lyrics_status')]
            w.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r','\n')) else v for v in values])
        atomic_bytes(DEST/'Список_музыки.csv',f.getvalue().encode('utf-8-sig'))


def process_rows(rows,action,on_error):
    """Keep just two requests in flight; stop never schedules the rest."""
    global WORK_TOTAL,WORK_COMPLETED
    WORK_TOTAL=len(rows);WORK_COMPLETED=0
    iterator=iter(rows);completed=0
    with ThreadPoolExecutor(max_workers=2) as pool:
        active={}
        def enqueue():
            if STOP.exists():return
            row=next(iterator,None)
            if row is not None:active[pool.submit(action,row)]=row
        enqueue();enqueue()
        while active:
            finished,_=wait(active,timeout=.25,return_when=FIRST_COMPLETED)
            for future in finished:
                row=active.pop(future)
                try:future.result()
                except AuthRequired:
                    STOP.touch();raise
                except Exception as exc:on_error(row,safe_error(exc))
                completed+=1
                WORK_COMPLETED=completed
                status(f'{completed} из {len(rows)}: '+row.get('artist','')+' — '+row.get('title',row['id']))
                enqueue()


def safe_error(exc):
    if isinstance(exc,(requests.exceptions.RequestException,OSError)):
        if isinstance(exc,PermissionError):return 'Файл занят плеером или недоступен. Закрой плеер и повтори синхронизацию.'
        return 'Ошибка файла или сети: '+type(exc).__name__
    # Never put URLs, credential strings or provider response bodies in a log.
    text=str(exc)
    if 'https://' in text or 'access_token' in text or 'OAuth ' in text:return type(exc).__name__
    return text[:500]


def enhance(row):
    if STOP.exists():return
    if row['cover_status']!='done' and row.get('cover_uri'):
        from music_covers import embed
        try:embed(row)
        except AuthRequired:raise
        except Exception as exc:
            with db() as c:c.execute("UPDATE tracks SET cover_status='failed',cover_error=? WHERE id=?",(safe_error(exc),row['id']))
    if settings.load()['lyrics'] and row['lyrics_status'] not in ('done','unavailable') and not STOP.exists():
        from music_lyrics import embed as embed_lyrics
        with db() as c:current=dict(c.execute('SELECT * FROM tracks WHERE id=?',(row['id'],)).fetchone())
        try:embed_lyrics(current)
        except AuthRequired:raise
        except Exception as exc:
            with db() as c:c.execute("UPDATE tracks SET lyrics_status='failed',lyrics_error=? WHERE id=?",(safe_error(exc),row['id']))


def run(probe=False,reset_stop=True):
    global PASS,DEST,WORK_TOTAL,WORK_COMPLETED
    DEST=settings.destination();PASS=0;WORK_TOTAL=0;WORK_COMPLETED=0
    if reset_stop:STOP.unlink(missing_ok=True)
    if settings.MOVE.exists():raise RuntimeError('Нужно завершить перенос: выбери ту же папку в настройках.')
    if not AUTH.exists():raise AuthRequired()
    with db() as c:before={r[0] for r in c.execute("SELECT id FROM tracks WHERE status='downloaded'")}
    if not catalog():status('Остановлено. Прогресс сохранён.','stopped');return
    DEST.mkdir(parents=True,exist_ok=True)
    # Recover missing tracked files; changed files are never overwritten.
    with db() as c:
        for r in c.execute("SELECT id,path FROM tracks WHERE status='downloaded' AND liked=1").fetchall():
            if not Path(r['path']).is_file():c.execute("UPDATE tracks SET status='pending',lyrics_status='pending',cover_status='pending',error=NULL WHERE id=?",(r['id'],))
    for PASS in range(1,(1 if probe else 3)+1):
        if STOP.exists():break
        with db() as c:rows=[dict(r) for r in c.execute("SELECT * FROM tracks WHERE status IN ('pending','failed') AND available=1 AND liked=1 ORDER BY position")]
        if probe:rows=rows[:3]
        if not rows:break
        status(f'Скачиваю MP3: проход {PASS}; файлов в очереди {len(rows)}.','downloading')
        def failed(row,error):
            with db() as c:c.execute("UPDATE tracks SET status='failed',error=? WHERE id=?",(error,row['id']))
        process_rows(rows,download,failed)
        export_lists()
    if not STOP.exists():
        with db() as c:rows=[dict(r) for r in c.execute("SELECT * FROM tracks WHERE status='downloaded' AND liked=1 AND ((cover_status!='done' AND cover_uri IS NOT NULL) OR lyrics_status NOT IN ('done','unavailable')) ORDER BY position")]
        if not settings.load()['lyrics']:rows=[r for r in rows if r['cover_status']!='done' and r.get('cover_uri')]
        if probe:rows=rows[:3]
        if rows:
            status(f'Добавляю тексты и обложки: {len(rows)} треков.','enriching')
            process_rows(rows,enhance,lambda row,error:None)
    export_lists()
    with db() as c:
        done=c.execute("SELECT COUNT(*) FROM tracks WHERE status='downloaded'").fetchone()[0]
        remaining=c.execute("SELECT COUNT(*) FROM tracks WHERE liked=1 AND status!='downloaded'").fetchone()[0]
        extras=c.execute("SELECT COUNT(*) FROM tracks WHERE status='downloaded' AND (cover_status='failed' OR lyrics_status='failed')").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO meta VALUES('last_sync',?)",(str(time.time()),))
        added=sum(r[0] not in before for r in c.execute("SELECT id FROM tracks WHERE status='downloaded' AND liked=1"))
        for key,value in (('last_added',added),('last_missing',remaining),('last_extras',extras)):
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,str(value)))
    status(f'Сохранено MP3: {done}. Не скачалось: {remaining}. Ошибок обложек/текстов: {extras}.','stopped' if STOP.exists() else ('probe_done' if probe else ('done' if not remaining and not extras else 'paused')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--probe',action='store_true');args=p.parse_args()
    initialize()
    try:
        with worker_lock():run(args.probe)
    except Exception as exc:status(safe_error(exc),'needs_login' if isinstance(exc,AuthRequired) else 'failed');raise SystemExit(1)
