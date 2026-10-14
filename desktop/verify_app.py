"""Offline regression checks: incremental sync, login replacement and MP3 lyrics."""
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import json
import os
import shutil
import tempfile
import auth
import settings
import music_export as m
import music_lyrics as lyrics
from music_covers import audio_hash
from mutagen.id3 import ID3


def read_row(ident):
    with m.db() as c:return dict(c.execute('SELECT * FROM tracks WHERE id=?',(ident,)).fetchone())


def metadata(ident):return {'id':ident,'title':'Title '+ident,'artists':[{'name':'Artist'}],'albums':[{'title':'Album'}],'durationMs':120000,'available':True}


def response(endpoint,data=None,params=None):
    if endpoint=='/account/status':return {'account':{'uid':'42'}}
    if endpoint.endswith('/likes/tracks'):return {'library':{'tracks':[{'id':'2'},{'id':'3'}]}}
    if endpoint=='/tracks':return [metadata('2'),metadata('3')]
    raise AssertionError(endpoint)


from test_media import create_mp3
with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
    root=Path(folder).resolve();archive=root/'archive';archive.mkdir()
    fixture=create_mp3(root/'fixture.mp3')
    for owner,field,value in ((m,'DB',root/'state.db'),(m,'AUTH',root/'auth.json'),(m,'DEST',archive),(m,'STATUS',root/'status.json'),(m,'STOP',root/'STOP'),(auth,'AUTH',root/'auth.json'),(auth,'DEVICE',root/'device.json'),(settings,'CONFIG',root/'settings.json'),(settings,'MOVE',root/'relocation.json'),(lyrics,'CACHE',root/'cache')):
        stack.enter_context(patch.object(owner,field,value))
    settings.save({'destination':str(archive)});m.initialize()
    one=archive/'account_42'/'1.mp3';one.parent.mkdir();one.write_bytes(b'kept local file')
    with m.db() as c:
        c.execute("INSERT INTO meta VALUES('uid','42')")
        c.execute("INSERT INTO tracks(id,position,title,artist,album,status,path,size,sha256) VALUES('1',0,'Old','Artist','Album','downloaded',?,?,?)",(str(one),one.stat().st_size,m.checksum(one)))
        c.execute("INSERT INTO tracks(id,position,title,artist,album,status,available) VALUES('2',1,'Previously blocked','Artist','Album','unavailable',0)")
    with patch.object(m,'api',side_effect=response):assert m.catalog()
    assert read_row('1')['liked']==0 and one.read_bytes()==b'kept local file'
    assert read_row('2')['liked']==1 and read_row('2')['status']=='pending'
    assert read_row('3')['status']=='pending'
    m.export_lists();assert '1.mp3' not in (archive/'Мне_нравится.m3u8').read_text(encoding='utf-8')
    before=[(read_row(x)['liked'],read_row(x)['status']) for x in ('1','2','3')]
    def broken(endpoint,data=None,params=None):
        if endpoint=='/tracks':raise RuntimeError('Temporary network error')
        return response(endpoint,data,params)
    with patch.object(m,'api',side_effect=broken):
        try:m.catalog();raise AssertionError('Partial catalogue accepted')
        except RuntimeError:pass
    assert before==[(read_row(x)['liked'],read_row(x)['status']) for x in ('1','2','3')]
    attempted=[]
    def stopped(row):attempted.append(row['id']);m.STOP.touch()
    m.process_rows([{'id':str(i)} for i in range(20)],stopped,lambda *_:None)
    assert len(attempted)<=2;m.STOP.unlink()
    # A valid file renamed before a crash is adopted only via its journal hash.
    target=archive/'account_42'/m.name(read_row('2'));target.write_bytes(b'journalled audio')
    with m.db() as c:c.execute('UPDATE tracks SET download_new_sha=?,download_new_size=?,download_new_bitrate=320 WHERE id=?',(m.checksum(target),target.stat().st_size,'2'))
    assert m.download(read_row('2')) and read_row('2')['status']=='downloaded'
    # An existing auth file must not short-circuit a fresh device-code login.
    auth.write_private(auth.AUTH,{'access_token':'old-test-token'})
    auth.write_private(auth.DEVICE,{'device_code':'test','expires_at':99999999999})
    with patch.object(auth,'oauth',return_value={'access_token':'new-test-token'}),patch.object(auth,'validate_token',return_value={'name':'Test'}):
        assert auth.poll()['state']=='authorized'
    assert auth.read_auth()['access_token']=='new-test-token'
    with patch.object(auth,'validate_token',side_effect=RuntimeError('Wrong account')):
        try:auth.save_token('wrong-test-token');raise AssertionError('Wrong account accepted')
        except RuntimeError:pass
    assert auth.read_auth()['access_token']=='new-test-token'
    auth.write_private(auth.AUTH,{'access_token':'new-test-token','refresh_token':'refresh-test-token'})
    with patch.object(auth,'oauth',return_value={'access_token':'refreshed-test-token'}),patch.object(auth,'validate_token',return_value={'name':'Test'}):
        assert auth.refresh('new-test-token')=='refreshed-test-token'
    with patch.object(auth,'oauth') as oauth:
        assert auth.refresh('new-test-token')=='refreshed-test-token' and not oauth.called
    # Embed synthetic lyrics in generated audio; covers and audio survive.
    song=archive/'account_42'/'3.mp3';shutil.copy2(fixture,song)
    initial_audio=audio_hash(song);initial_cover=[(x.mime,x.type,x.data) for x in ID3(song).getall('APIC')]
    initial_sha=m.checksum(song)
    with m.db() as c:c.execute("UPDATE tracks SET status='downloaded',path=?,size=?,sha256=? WHERE id='3'",(str(song),song.stat().st_size,initial_sha))
    data={'format':'LRC','text':'[ar:Test]\n[00:01.00]Synthetic test line\n[00:03.00]Another test line','provider':'Test','writers':[]}
    with patch.object(lyrics,'fetch',return_value=data),patch.object(lyrics.os,'replace',side_effect=PermissionError()):
        try:lyrics.embed(read_row('3'));raise AssertionError('Locked file replaced')
        except PermissionError:pass
    # atomic cache writes also use os.replace, so explicitly populate the cache
    # before simulating the media-file lock in the next check.
    auth.write_private(lyrics.cache_path(read_row('3')),data)
    with patch.object(lyrics.os,'replace',side_effect=PermissionError()):
        try:lyrics.embed(read_row('3'));raise AssertionError('Locked file replaced')
        except PermissionError:pass
    assert m.checksum(song)==initial_sha
    lyrics.embed(read_row('3'));assert read_row('3')['lyrics_status']=='done'
    assert audio_hash(song)==initial_audio
    assert [(x.mime,x.type,x.data) for x in ID3(song).getall('APIC')]==initial_cover
    assert ID3(song)['USLT:YandexLyrics:und'].text==lyrics.plain(data)
    assert song.with_suffix('.lrc').exists() and song.with_suffix('.txt').exists()
    # Crash after media replacement, before database commit.
    with m.db() as c:c.execute("UPDATE tracks SET sha256=?,lyrics_status='failed',lyrics_new_sha=?,lyrics_new_size=? WHERE id='3'",(initial_sha,m.checksum(song),song.stat().st_size))
    lyrics.embed(read_row('3'));assert read_row('3')['sha256']==m.checksum(song) and read_row('3')['lyrics_status']=='done'
    # Stop recorded before process startup must not be cleared by a GUI worker.
    m.STOP.touch()
    with patch.object(m,'catalog',return_value=False) as catalogue:
        m.run(reset_stop=False);assert m.STOP.exists()
    m.STOP.unlink()
    # Relocation preserves unrelated files and finishes after an interrupted run.
    new=root/'new';new.mkdir();(new/'my-other-song.mp3').write_bytes(b'other')
    real_rename=os.rename;renames=[]
    def interrupted(source,target):
        renames.append((Path(source),Path(target)))
        if len(renames)==2:raise PermissionError('Simulated interruption')
        return real_rename(source,target)
    with patch.object(settings.os,'rename',side_effect=interrupted):
        try:settings.relocate(new);raise AssertionError('Interruption was ignored')
        except PermissionError:pass
    assert settings.MOVE.exists() and settings.destination()==archive
    first_source,first_target=renames[0]
    assert first_target.is_file() and not first_source.exists()
    assert any(Path(read_row(ident)['path'])==first_target for ident in ('1','2','3'))
    journal=json.loads(settings.MOVE.read_text(encoding='utf-8'))
    count=settings.relocate(new)
    assert count==3 and (new/'my-other-song.mp3').read_bytes()==b'other'
    assert settings.destination()==new and all(Path(read_row(x)['path']).exists() for x in ('1','2','3'))
    assert not one.exists() and not song.exists()
    # Recover the final narrow crash window after settings were saved.
    auth.write_private(settings.MOVE,journal)
    assert settings.relocate(new)==3
    assert not settings.MOVE.exists()
    collision=root/'collision';dest=collision/'account_42'/'3.mp3';dest.parent.mkdir(parents=True);dest.write_bytes(b'other file')
    try:settings.relocate(collision);raise AssertionError('Collision overwritten')
    except RuntimeError:pass
    assert dest.read_bytes()==b'other file' and settings.destination()==new
    # Exercise the copy/verify/delete path used for a different disk.
    copied=root/'copied'
    with patch.object(settings,'same_volume',return_value=False):assert settings.relocate(copied)==3
    assert all(Path(read_row(x)['path']).is_relative_to(copied) and Path(read_row(x)['path']).exists() for x in ('1','2','3'))
print('PASS: transactional likes, removed-file retention, bounded stop, crash recovery, login replacement/refresh, lyrics/APIC/audio integrity, verified relocation')
