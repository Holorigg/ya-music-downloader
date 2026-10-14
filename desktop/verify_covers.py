"""Check audio/metadata preservation, resume and interrupted-commit recovery."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from mutagen.id3 import ID3
import music_export as m
import music_covers as covers

from test_media import create_mp3,COVER
picture,kind=COVER,'image/png'
with TemporaryDirectory() as d:
    root=Path(d).resolve();source=root/'music'/'sample.mp3';source.parent.mkdir()
    import shutil
    create_mp3(source)
    real={'path':str(source),'size':source.stat().st_size,'cover_uri':'avatars.yandex.net/test-only/%%'}
    original=m.checksum(source);audio=covers.audio_hash(source)
    with patch.object(m,'DB',root/'state.db'),patch.object(m,'DEST',source.parent),patch.object(covers,'image',return_value=(picture,kind)):
        m.initialize()
        with m.db() as c:
            c.execute("INSERT INTO tracks(id,status,path,size,sha256,cover_uri) VALUES ('1','downloaded',?,?,?,?)",(str(source),source.stat().st_size,original,real['cover_uri']))
            row=dict(c.execute('SELECT * FROM tracks').fetchone())
        # A failure to replace an open file preserves the original and a prepared
        # verified copy. The next attempt can recover without downloading audio.
        with patch.object(covers.os,'replace',side_effect=PermissionError('reader holds file')):
            try:covers.embed(row);raise AssertionError('Replacement failure ignored')
            except PermissionError:pass
        assert m.checksum(source)==original
        with m.db() as c:row=dict(c.execute('SELECT * FROM tracks').fetchone())
        assert row['cover_new_sha'] and row['cover_status']=='pending'
        covers.embed(row)
        assert covers.audio_hash(source)==audio
        tags=ID3(source)
        assert len(tags.getall('APIC'))==1 and tags.getall('APIC')[0].data==picture
        assert tags.version[:2]==(2,3)
        with m.db() as c:row=dict(c.execute('SELECT * FROM tracks').fetchone())
        assert row['sha256']==m.checksum(source) and row['cover_status']=='done' and not row['cover_new_sha']
        # Simulate a crash after replacement but before its final DB commit.
        with m.db() as c:
            c.execute("UPDATE tracks SET sha256=?,size=?,cover_status='pending',cover_new_sha=?,cover_new_size=?",(original,real['size'],row['sha256'],row['size']))
            row=dict(c.execute('SELECT * FROM tracks').fetchone())
        covers.embed(row)
        with m.db() as c:
            row=dict(c.execute('SELECT * FROM tracks').fetchone())
            assert row['cover_status']=='done' and row['sha256']==m.checksum(source)
        source.write_bytes(source.read_bytes()+b'user edit')
        with patch.object(covers,'prepare') as prepare:
            try:covers.embed(row);raise AssertionError('Changed file accepted')
            except RuntimeError:pass
            assert not prepare.called
print('PASS: APIC/front cover in ID3v2.3, identical MP3 audio packets and text tags, safe locked-file retry, crash recovery, changed-file refusal')
