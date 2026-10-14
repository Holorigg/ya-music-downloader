"""Offline migrations, archive restoration and multiple-folder library regression checks."""
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import tempfile,unittest,sqlite3
import auth,settings,library,music_export as m

class LibraryChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.stack=ExitStack()
        for owner,key,value in ((m,'DB',self.root/'state.db'),(m,'AUTH',self.root/'auth.json'),(m,'STATUS',self.root/'status.json'),(m,'STOP',self.root/'STOP'),(m,'DEST',self.root/'old'),(settings,'CONFIG',self.root/'settings.json'),(settings,'MOVE',self.root/'move.json'),(auth,'AUTH',self.root/'auth.json')):self.stack.enter_context(patch.object(owner,key,value))
        settings.save({'destination':str(m.DEST),'lyrics':False});auth.AUTH.write_text('{}');m.initialize()
        with m.db() as c:c.execute("INSERT INTO meta VALUES('uid','42')")
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def add(self,ident,base,liked=1):
        path=base/'account_42'/(ident+'.mp3');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('Original audio '+ident).encode());sha=m.checksum(path)
        with m.db() as c:c.execute('INSERT INTO tracks(id,position,title,artist,liked,status,path,size,sha256,available) VALUES(?,?,?,?,?,?,?,?,?,1)',(ident,int(ident),'Песня '+ident,'Исполнитель',liked,'downloaded',str(path),path.stat().st_size,sha))
        return path,sha
    def test_migration_preserves_owned_paths_and_hashes(self):
        path,sha=self.add('1',m.DEST)
        with m.db() as c:c.execute('ALTER TABLE tracks DROP COLUMN archive_hidden')
        m.initialize()
        with m.db() as c:row=dict(c.execute('SELECT * FROM tracks').fetchone())
        self.assertEqual(row['archive_hidden'],0);self.assertEqual(row['sha256'],sha);self.assertEqual(Path(row['path']),path)
    def test_hidden_archived_song_reappears_when_liked(self):
        path,sha=self.add('1',m.DEST,liked=0);self.assertEqual(library.hide_archive(['1']),['1']);self.assertFalse(library.snapshot()[0])
        def response(endpoint,data=None,params=None):
            if endpoint=='/account/status':return {'account':{'uid':'42'}}
            if endpoint.endswith('/likes/tracks'):return {'library':{'tracks':[{'id':'1'}]}}
            return [{'id':'1','title':'Новое название','available':True,'artists':[{'name':'Исполнитель'}]}]
        with patch.object(m,'api',side_effect=response):self.assertTrue(m.catalog())
        row=library.snapshot()[0][0];self.assertEqual(row['archive_hidden'],0);self.assertEqual(row['status'],'downloaded');self.assertEqual(row['sha256'],sha);self.assertEqual(m.checksum(path),sha)
    def test_playlist_retains_songs_left_in_an_earlier_folder(self):
        path,_=self.add('1',m.DEST);new=self.root/'new';settings.save({'destination':str(new)});m.DEST=new;m.export_lists();entry=(new/'Мне_нравится.m3u8').read_text(encoding='utf-8').splitlines()[1];self.assertEqual((new/entry).resolve(),path)
        with patch.object(m.os.path,'relpath',side_effect=ValueError('different drives')):m.export_lists()
        self.assertEqual((new/'Мне_нравится.m3u8').read_text(encoding='utf-8').splitlines()[1],path.as_posix())
    def test_move_collects_verified_files_from_multiple_folders(self):
        first,first_sha=self.add('1',m.DEST);new=self.root/'new';settings.save({'destination':str(new)});m.DEST=new;second,second_sha=self.add('2',new);final=self.root/'final'
        self.assertEqual(settings.relocate(final),2)
        with m.db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM tracks ORDER BY id')]
        self.assertFalse(first.exists());self.assertFalse(second.exists());self.assertTrue(all(Path(r['path']).resolve().is_relative_to(final) for r in rows));self.assertEqual([m.checksum(Path(r['path'])) for r in rows],[first_sha,second_sha])
    def test_move_rejects_active_sync_and_retains_files(self):
        path,sha=self.add('1',m.DEST);original=settings.destination()
        with m.worker_lock():
            self.assertTrue(m.worker_running())
            with self.assertRaises(RuntimeError):settings.relocate(self.root/'blocked')
        self.assertFalse(m.worker_running());self.assertEqual(settings.destination(),original)
        self.assertEqual(m.checksum(path),sha);self.assertFalse(settings.MOVE.exists())
    def test_result_counts_new_downloads_without_recounting_previous_songs(self):
        self.add('1',m.DEST)
        with m.db() as c:c.execute("INSERT INTO tracks(id,title,position,liked,status,available) VALUES('2','Новая песня',2,1,'pending',1)")
        def download_rows(rows,*_):
            for row in rows:self.add_download(row['id'])
        with patch.object(m,'catalog',return_value=True),patch.object(m,'process_rows',side_effect=download_rows):m.run()
        _,meta=library.snapshot();self.assertEqual(meta['last_added'],'1');self.assertEqual(meta['last_missing'],'0')
    def add_download(self,ident):
        path=self.root/'old/account_42'/('new-'+ident+'.mp3');path.write_bytes(b'new-audio')
        with m.db() as c:c.execute("UPDATE tracks SET status='downloaded',path=? WHERE id=?",(str(path),ident))

if __name__=='__main__':unittest.main(verbosity=2)
