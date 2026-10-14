"""Recover a fresh profile from complete exported MP3s without media writes."""
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import os,shutil,tempfile,unittest
from mutagen.id3 import ID3,TIT2,TPE1,TALB,USLT
import auth,music_export as m
from test_media import create_mp3


class ExistingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();cls.audio=create_mp3(Path(cls.fixture.name).resolve()/'fixture.mp3')
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.stack=ExitStack()
        for owner,key,value in ((m,'DB',self.root/'state.db'),(m,'DEST',self.root/'music'),(m,'STOP',self.root/'STOP')):self.stack.enter_context(patch.object(owner,key,value))
        m.initialize()
        with m.db() as c:
            c.execute("INSERT INTO meta VALUES('uid','42')")
            c.execute("INSERT INTO tracks(id,title,artist,album,duration_ms,status,available,liked) VALUES('17','Test track','Test artist','Test album',3000,'failed',1,1)")
        self.target=m.DEST/'account_42'/m.name(self.row());self.target.parent.mkdir(parents=True)
        shutil.copy2(self.audio,self.target)
        self.api=self.stack.enter_context(patch.object(m,'api',side_effect=AssertionError('Network request while restoring a local file')))
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def row(self):
        with m.db() as c:return dict(c.execute("SELECT * FROM tracks WHERE id='17'").fetchone())
    def reject(self):
        before=self.target.read_bytes()
        with self.assertRaises(RuntimeError):m.download(self.row())
        self.assertEqual(self.target.read_bytes(),before);self.assertNotEqual(self.row()['status'],'downloaded');self.api.assert_not_called()
    def test_existing_export_restores_status_and_hash_without_network_or_retagging(self):
        before=self.target.read_bytes();modified=self.target.stat().st_mtime_ns
        self.assertTrue(m.download(self.row()));row=self.row()
        self.assertEqual(row['status'],'downloaded');self.assertEqual(row['path'],str(self.target.resolve()))
        self.assertEqual(row['sha256'],m.checksum(self.target));self.assertEqual(row['size'],len(before));self.assertEqual(row['bitrate'],128)
        self.assertEqual(row['cover_status'],'done');self.assertEqual(self.target.read_bytes(),before);self.assertEqual(self.target.stat().st_mtime_ns,modified);self.api.assert_not_called()
    def test_existing_lyrics_are_recognized_without_being_rewritten(self):
        tags=ID3(self.target);tags.add(USLT(encoding=3,lang='und',desc='Test',text='Original fixture lyric'));tags.save(self.target,v2_version=3)
        before=self.target.read_bytes();m.download(self.row());self.assertEqual(self.row()['lyrics_status'],'done');self.assertEqual(self.target.read_bytes(),before)
    def test_wrong_title_artist_or_album_are_not_claimed(self):
        for frame in (TIT2,TPE1,TALB):
            with self.subTest(frame=frame.__name__):
                shutil.copy2(self.audio,self.target);tags=ID3(self.target);tags.setall(frame.__name__,[frame(encoding=3,text=['Different metadata'])]);tags.save(self.target,v2_version=3);self.reject()
    def test_preview_length_and_truncated_mp3_are_not_claimed(self):
        with m.db() as c:c.execute("UPDATE tracks SET duration_ms=120000 WHERE id='17'")
        self.reject()
        with m.db() as c:c.execute("UPDATE tracks SET duration_ms=3000 WHERE id='17'")
        data=self.target.read_bytes();self.target.write_bytes(data[:-1500]);self.reject()
    def test_foreign_bytes_and_unlabelled_mp3_are_not_claimed(self):
        self.target.write_bytes(b'An unrelated file with a colliding name');self.reject()
        shutil.copy2(self.audio,self.target);ID3(self.target).delete(self.target);self.reject()
    def test_a_known_hash_can_restore_a_tracked_file(self):
        sha=m.checksum(self.target)
        with m.db() as c:c.execute("UPDATE tracks SET path=?,size=?,sha256=?,cover_status='done' WHERE id='17'",(str(self.target),self.target.stat().st_size,sha))
        with patch.object(m,'validate',side_effect=AssertionError('Known verified bytes need no fresh decode')):self.assertTrue(m.download(self.row()))
        self.assertEqual(self.row()['sha256'],sha);self.assertEqual(self.row()['status'],'downloaded');self.api.assert_not_called()
    def test_a_changed_known_file_cannot_get_a_new_hash_baseline(self):
        original=m.checksum(self.target)
        with m.db() as c:c.execute("UPDATE tracks SET path=?,size=?,sha256=? WHERE id='17'",(str(self.target),self.target.stat().st_size,original))
        tags=ID3(self.target);tags.add(USLT(encoding=3,lang='und',desc='Changed',text='External edit'));tags.save(self.target,v2_version=3)
        self.reject();self.assertEqual(self.row()['sha256'],original)
    def test_a_change_during_validation_prevents_registration(self):
        changed=[]
        def external_change(*_):
            tags=ID3(self.target);tags.add(USLT(encoding=3,lang='und',desc='External',text='Changed during import'));tags.save(self.target,v2_version=3);changed.append(self.target.read_bytes())
        with patch.object(m,'validate',side_effect=external_change),self.assertRaises(RuntimeError):m.download(self.row())
        self.assertEqual(self.target.read_bytes(),changed[0]);self.assertIsNone(self.row()['sha256']);self.assertEqual(self.row()['status'],'failed');self.api.assert_not_called()
    def test_a_symbolic_link_is_preserved_and_not_registered(self):
        self.target.unlink()
        try:self.target.symlink_to(self.audio)
        except OSError as exc:self.skipTest('OS does not allow creating a test symbolic link: '+type(exc).__name__)
        with self.assertRaises(RuntimeError):m.download(self.row())
        self.assertTrue(self.target.is_symlink());self.assertEqual(self.row()['status'],'failed');self.api.assert_not_called()
    def test_stop_during_validation_leaves_the_record_and_file_unchanged(self):
        before=self.target.read_bytes()
        with patch.object(m,'validate',side_effect=lambda *_:m.STOP.touch()):self.assertFalse(m.download(self.row()))
        self.assertEqual(self.target.read_bytes(),before);self.assertIsNone(self.row()['sha256']);self.assertEqual(self.row()['status'],'failed');self.api.assert_not_called()
    def sync_local(self):
        credentials=self.root/'test-auth.json';credentials.write_text('{}',encoding='utf-8')
        with patch.object(m,'AUTH',credentials),patch.object(m,'catalog',return_value=True),patch.object(m.settings,'destination',return_value=m.DEST),patch.object(m.settings,'load',return_value={'lyrics':False}),patch.object(m.settings,'MOVE',self.root/'move.json'),patch.object(m,'status'):
            m.run()
        self.api.assert_not_called()
    def unavailable_sync(self):
        with m.db() as c:c.execute("UPDATE tracks SET status='unavailable',available=0 WHERE id='17'")
        self.sync_local()
    def test_sync_restores_local_export_even_when_service_track_is_unavailable(self):
        before=self.target.read_bytes();self.unavailable_sync()
        self.assertEqual(self.row()['status'],'downloaded');self.assertEqual(self.target.read_bytes(),before)
    def test_unavailable_missing_or_foreign_file_stays_unavailable_without_download(self):
        self.target.unlink();self.unavailable_sync();self.assertEqual(self.row()['status'],'unavailable');self.assertFalse(self.target.exists())
        self.target.write_bytes(b'Unrelated local file');self.unavailable_sync();self.assertEqual(self.row()['status'],'unavailable');self.assertEqual(self.target.read_bytes(),b'Unrelated local file')
    def test_unavailable_local_recovery_obeys_stop_and_retains_known_hash(self):
        original=m.checksum(self.target)
        with m.db() as c:c.execute("UPDATE tracks SET status='unavailable',available=0,path=?,size=?,sha256=? WHERE id='17'",(str(self.target),self.target.stat().st_size,original))
        m.STOP.touch();m.recover_unavailable();self.assertEqual(self.row()['status'],'unavailable');m.STOP.unlink()
        self.target.write_bytes(b'Changed known file');m.recover_unavailable()
        self.assertEqual(self.row()['status'],'unavailable');self.assertEqual(self.row()['sha256'],original);self.api.assert_not_called()
    def test_a_deleted_known_file_does_not_trigger_download_when_service_is_unavailable(self):
        original=m.checksum(self.target);size=self.target.stat().st_size
        with m.db() as c:c.execute("UPDATE tracks SET status='downloaded',available=0,path=?,size=?,sha256=? WHERE id='17'",(str(self.target),size,original))
        self.target.unlink();self.sync_local()
        self.assertEqual(self.row()['status'],'unavailable');self.assertEqual(self.row()['sha256'],original);self.assertFalse(self.target.exists())


if __name__=='__main__':unittest.main(verbosity=2)
