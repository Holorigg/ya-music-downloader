"""Local settings and a restartable, verified library relocation."""
from pathlib import Path
import json
import os
import shutil
import secrets
import sqlite3
from auth import ROOT,DATA,write_private

CONFIG=DATA/'settings.json'
MOVE=DATA/'relocation.json'
DEFAULTS={'destination':str(Path.home()/'Music'),'lyrics':True,'schedule_hours':0,'workers':2,
          'theme':'system','auto_sync':False,'auto_hours':6,'wifi_only':False,'notify_results':True}


def load():
    if CONFIG.exists():
        data=json.loads(CONFIG.read_text(encoding='utf-8'))
        return {**DEFAULTS,**data}
    return dict(DEFAULTS)


def save(data):write_private(CONFIG,{**load(),**data})


def destination():return Path(load()['destination'])


def same_volume(source,target):return source.drive.casefold()==target.drive.casefold()


def relocate(target):
    import music_export as m
    with m.worker_lock():
        m.initialize()
        old=destination().resolve();new=Path(target).expanduser().resolve()
        if not new.is_absolute() or new==Path(new.anchor):raise RuntimeError('Выбери папку для музыки.')
        if MOVE.exists():
            journal=json.loads(MOVE.read_text(encoding='utf-8'))
            if old not in (Path(journal['old']),Path(journal['new'])) or Path(journal['new'])!=new:raise RuntimeError('Предыдущий перенос не закончен. Выбери ту же папку, чтобы продолжить.')
            old=Path(journal['old'])
        else:
            if old==new:return 0
            if old.is_relative_to(new) or new.is_relative_to(old):raise RuntimeError('Выбери отдельную папку, вне текущей папки архива.')
            with m.db() as c:
                rows=[dict(r) for r in c.execute("SELECT id,path,size,sha256 FROM tracks WHERE status='downloaded'")]
                uid=c.execute("SELECT value FROM meta WHERE key='uid'").fetchone()
            entries=[]
            for row in rows:
                source=Path(row['path']).resolve()
                if source.is_relative_to(old):relative=source.relative_to(old)
                else:
                    # "Only new songs" can leave verified owned files in earlier folders.
                    import re
                    account=source.parent.name if re.fullmatch(r'account_[0-9]+',source.parent.name) else 'account_'+m.ident(uid[0] if uid else '0')
                    relative=Path(account)/source.name
                dest=(new/relative).resolve()
                if not dest.is_relative_to(new):raise RuntimeError('Путь назначения вне выбранной папки.')
                if dest.exists():raise RuntimeError('В новой папке уже есть одноимённый файл. Он сохранён: '+dest.name)
                if not source.is_file() or source.stat().st_size!=row['size'] or m.checksum(source)!=row['sha256']:
                    raise RuntimeError('Один из MP3 изменился или отсутствует. Перенос остановлен: '+source.name)
                entries.append({**row,'old':str(source),'new':str(dest)})
                for ext in ('.lrc','.txt'):
                    side=source.with_suffix(ext)
                    if side.exists():
                        to=dest.with_suffix(ext)
                        if to.exists():raise RuntimeError('В новой папке уже есть текст: '+to.name)
                        entries.append({'id':None,'old':str(side),'new':str(to),'sha256':m.checksum(side),'size':side.stat().st_size})
            journal={'old':str(old),'new':str(new),'entries':entries}
            write_private(MOVE,journal)
        new.mkdir(parents=True,exist_ok=True)
        for item in journal['entries']:
            source=Path(item['old']);dest=Path(item['new']);dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():
                if dest.stat().st_size!=item['size'] or m.checksum(dest)!=item['sha256']:raise RuntimeError('Файл в новой папке изменился: '+dest.name)
            else:
                if not source.exists() or source.stat().st_size!=item['size'] or m.checksum(source)!=item['sha256']:raise RuntimeError('Исходный файл изменился: '+source.name)
                if same_volume(source,dest):os.rename(source,dest)
                else:
                    if shutil.disk_usage(new).free<item['size']+64*1024*1024:raise RuntimeError('Недостаточно места для переноса.')
                    part=dest.with_name(dest.name+'.move-'+secrets.token_hex(4)+'.part')
                    try:
                        shutil.copy2(source,part)
                        if m.checksum(part)!=item['sha256']:raise RuntimeError('Копия не прошла проверку.')
                        with part.open('r+b') as f:os.fsync(f.fileno())
                        os.rename(part,dest)
                    finally:part.unlink(missing_ok=True)
            if item['id']:
                with m.db() as c:c.execute('UPDATE tracks SET path=? WHERE id=?',(str(dest),item['id']))
            if source.exists():
                if m.checksum(source)!=item['sha256']:raise RuntimeError('Исходный файл изменился после копирования; он сохранён.')
                source.unlink()
        save({'destination':str(new)})
        m.DEST=new;m.export_lists()
        MOVE.unlink(missing_ok=True)
        # Remove only our old, derived lists; never other user files or folders.
        for filename in ('Мне_нравится.m3u8','Список_музыки.csv'):(old/filename).unlink(missing_ok=True)
        return sum(bool(x['id']) for x in journal['entries'])
