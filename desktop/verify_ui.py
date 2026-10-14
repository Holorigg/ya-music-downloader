"""Native widget regression tests in isolated storage, with no network or user file writes."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,time,json,threading
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication,QPushButton,QTextBrowser,QDialog
from PySide6.QtCore import Qt,QPoint,QUrl
from PySide6.QtGui import QFontDatabase,QPalette,QColor,QWheelEvent
from PySide6.QtTest import QTest
import app,auth,settings,library,windows_support
import music_export as m
from native_ui import Theme,ROLE
REAL_ACCOUNT_CHECK=app.Window.check_account

qt=QApplication.instance() or QApplication([]);qt.setQuitOnLastWindowClosed(False)
for name in ('segoeui.ttf','seguisb.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)

def wait(predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qt.processEvents();QTest.qWait(10)
        if predicate():return
    raise AssertionError('Native event-loop operation timed out')

class NativeChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.stack=ExitStack();self.window=None
        for owner,key,value in ((m,'DB',self.root/'state.db'),(m,'STATUS',self.root/'status.json'),(m,'STOP',self.root/'STOP'),(settings,'CONFIG',self.root/'settings.json'),(settings,'MOVE',self.root/'relocation.json'),(auth,'AUTH',self.root/'auth.json'),(auth,'DEVICE',self.root/'device.json')):self.stack.enter_context(patch.object(owner,key,value))
        self.stack.enter_context(patch.object(app,'running',return_value=False));self.stack.enter_context(patch.object(app.Window,'check_account',return_value=None));self.stack.enter_context(patch.object(app.Window,'make_tray',lambda self:setattr(self,'tray',None)))
        settings.save({'destination':str(self.root/'music'),'theme':'dark'});self.stack.enter_context(patch.object(m,'DEST',settings.destination()));m.initialize();self.music=self.root/'music/account_42';self.music.mkdir(parents=True);self.file=self.music/'original.mp3';self.file.write_bytes(b'owned-original-audio');self.file.with_suffix('.txt').write_text('Первая строка\nВторая строка',encoding='utf-8')
        with m.db() as c:
            for ident,liked,state,title,artist,path in (('1',1,'downloaded','Трек 01','Demo Artist',str(self.file)),('2',1,'unavailable','Недоступная песня','Другой исполнитель',None),('3',0,'downloaded','Архивная песня','Исполнитель',str(self.file)),('4',0,'failed','Удалённая из лайков','Исполнитель',None)):
                c.execute('INSERT INTO tracks(id,position,title,artist,album,liked,status,path,sha256,size,available) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident,int(ident),title,artist,'Альбом',liked,state,path,'original-sha' if path else None,self.file.stat().st_size if path else None,1))
            c.execute("INSERT INTO meta VALUES('uid','42')")
        self.status('paused',100)
    def status(self,state,stamp,**fields):m.STATUS.write_text(json.dumps({'state':state,'updated':stamp,**fields}),encoding='utf-8')
    def open(self):
        self.window=app.Window();self.window.show();wait(lambda:self.window.rows_signature is not None);qt.processEvents();QTest.qWait(220);self.window.refresh();return self.window
    def reload(self):
        rows,meta=library.snapshot();signature=tuple(tuple(row.items()) for row in rows)
        jobs=set(self.window.snapshot_jobs);self.window.request_snapshot();jobs.update(self.window.snapshot_jobs)
        # Periodic polling may already queue another read as this one finishes.
        # Observe delivery of the requested state rather than global idleness.
        wait(lambda:not jobs.intersection(self.window.snapshot_jobs))
        wait(lambda:self.window.rows_signature==signature and self.window.meta==meta)
        self.window.refresh()
    def tearDown(self):
        if self.window:
            self.window.close();wait(lambda:not self.window.isVisible(),5);self.window.deleteLater();qt.processEvents()
        for widget in qt.topLevelWidgets():
            if isinstance(widget,QDialog):widget.close()
        self.stack.close();self.temp.cleanup()
    def test_four_filters_search_and_hidden_archives(self):
        w=self.open();self.assertEqual(w.model.rowCount(),2);w.chips['downloaded'].click();self.assertEqual(w.model.rowCount(),1);w.chips['missing'].click();self.assertEqual(w.model.rowCount(),1);w.chips['archive'].click();self.assertEqual(w.model.rowCount(),2);self.assertTrue(w.archive_clear.isVisible());w.search.setText('удалённая');self.assertEqual(w.model.rowCount(),1);w.search_clear.click();self.assertEqual(w.model.rowCount(),2);w.chips['all'].click();w.search.setText('DEMO ARTIST');self.assertEqual(w.model.rowCount(),1);w.search.setText('не найдено');self.assertTrue(w.empty.isVisible());self.assertFalse(w.empty_action.isVisible())
    def test_archive_clear_undo_does_not_touch_files(self):
        w=self.open();w.chips['archive'].click();w.archive_clear.click();wait(lambda:not w.jobs);self.reload();self.assertEqual(w.model.rowCount(),0);self.assertFalse(w.archive_clear.isVisible());self.assertEqual(self.file.read_bytes(),b'owned-original-audio');w.undo_button.click();wait(lambda:not w.jobs);self.reload();self.assertEqual(w.model.rowCount(),2)
        with m.db() as c:self.assertEqual(c.execute("SELECT sha256 FROM tracks WHERE id='3'").fetchone()[0],'original-sha')
    def test_archive_row_action_and_liked_song_guard(self):
        w=self.open();w.chips['archive'].click();qt.processEvents();index=w.model.index(0,0);rect=w.list.action_rect(w.list.visualRect(index));QTest.mouseClick(w.list.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());wait(lambda:not w.jobs);self.reload();self.assertEqual(w.model.rowCount(),1);self.assertEqual(library.hide_archive(['1']),[])
        with m.db() as c:c.execute("UPDATE tracks SET liked=1,archive_hidden=0 WHERE id='3'")
        self.reload();w.chips['all'].click();self.assertEqual(w.model.rowCount(),3);self.assertTrue(self.file.exists())
    def test_external_player_and_lyrics_card(self):
        w=self.open();w.list.setCurrentIndex(w.model.index(0,0));qt.processEvents();self.assertTrue(w.detail.isVisible())
        with patch.object(app.QDesktopServices,'openUrl',return_value=True) as external:
            play=next(b for b in w.detail.findChildren(QPushButton) if b.text()=='Слушать');play.click();self.assertEqual(Path(external.call_args.args[0].toLocalFile()),self.file);point=w.list.visualRect(w.model.index(0,0)).topLeft()+QPoint(100,25);QTest.mouseClick(w.list.viewport(),Qt.MouseButton.LeftButton,pos=point);QTest.mouseDClick(w.list.viewport(),Qt.MouseButton.LeftButton,pos=point);self.assertEqual(external.call_count,2);QTest.keyClick(w.list,Qt.Key.Key_Return);self.assertEqual(external.call_count,3)
        w.open_lyrics();wait(lambda:bool(w.findChildren(QTextBrowser,'')));browser=w.findChildren(QTextBrowser,'')[0];self.assertEqual(browser.toPlainText(),'Первая строка\nВторая строка')
    def test_neutral_themes_and_system_accent(self):
        w=self.open();self.assertEqual(w.theme.surface,'#121212');self.assertEqual(w.theme.container,'#222222');w.theme_combo.setCurrentIndex(w.theme_combo.findData('light'));self.assertFalse(w.theme.dark);self.assertEqual(settings.load()['theme'],'light');palette=QPalette();palette.setColor(QPalette.ColorRole.Accent,QColor('#D54C8A'));self.assertNotEqual(Theme.from_mode('system',palette).primary,Theme.from_mode('light').primary);w.theme_combo.setCurrentIndex(w.theme_combo.findData('system'));self.assertEqual(settings.load()['theme'],'system')
    def test_transitions_finish_without_hiding_list_content(self):
        w=self.open();w.list.setCurrentIndex(w.model.index(0,0));w.theme_combo.setCurrentIndex(w.theme_combo.findData('light'));w.nav_buttons[1].click();w.nav_buttons[0].click();w.chips['archive'].click();QTest.qWait(400);self.assertIsNone(w.pages.graphicsEffect());self.assertIsNone(w.list.graphicsEffect());image=w.list.viewport().grab().toImage();self.assertNotEqual(image.pixelColor(25,35).name(),w.theme.surface);self.assertGreaterEqual(w.nav_buttons[0].height(),76)
    def test_search_alignment_and_minimum_window(self):
        w=self.open();w.resize(820,600);QTest.qWait(200);self.assertEqual(w.search_icon.mapTo(w,w.search_icon.rect().center()).y(),w.search.mapTo(w,w.search.rect().center()).y());self.assertGreater(w.search.width(),120);w.chips['archive'].click();self.assertLessEqual(w.archive_clear.mapTo(w,QPoint(w.archive_clear.width(),0)).x(),w.width());self.assertEqual(len(w.nav_buttons),3)
    def test_dismissal_survives_refresh_reopen_and_new_result(self):
        w=self.open();self.assertTrue(w.notice.isVisible());w.dismiss_button.click();self.assertFalse(w.notice.isVisible());w.refresh();self.assertFalse(w.notice.isVisible());w.close();wait(lambda:not w.isVisible());w.deleteLater();qt.processEvents();w=self.open();self.assertFalse(w.notice.isVisible());self.status('paused',200);w.refresh();self.assertTrue(w.notice.isVisible())
    def test_swipe_dismisses_only_idle_notice(self):
        w=self.open();QTest.mousePress(w.notice,Qt.MouseButton.LeftButton,pos=QPoint(40,20));QTest.mouseRelease(w.notice,Qt.MouseButton.LeftButton,pos=QPoint(260,20));self.assertFalse(w.notice.isVisible());self.status('downloading',200,work_total=10,work_completed=3)
        with patch.object(w,'is_active',return_value=True):
            w.refresh();self.assertTrue(w.notice.isVisible());self.assertFalse(w.notice.dismissible);w.dismiss_notice();self.assertTrue(w.notice.isVisible());self.assertEqual(w.progress.maximum(),10)
    def test_optional_auto_obeys_interval_wifi_and_close(self):
        w=self.open();self.assertFalse(settings.load()['auto_sync']);self.assertFalse(w.interval.isEnabled());auth.AUTH.write_text('{}');self.status('ready',200);w.refresh()
        with patch.object(w,'sync') as sync,patch.object(windows_support,'wifi_connected',return_value=False):
            w.auto_check();sync.assert_not_called();w.auto_switch.setChecked(True);self.assertTrue(settings.load()['auto_sync']);w.wifi_switch.setChecked(True);w.auto_check();sync.assert_not_called()
            with patch.object(windows_support,'wifi_connected',return_value=True):w.auto_check();sync.assert_called_once_with(automatic=True)
            sync.reset_mock();w.auto_check();sync.assert_not_called();w.closing=True;settings.save({'auto_checked_at':0});w.auto_check();sync.assert_not_called();w.closing=False
    def test_folder_new_songs_and_verified_move_choices(self):
        w=self.open();chosen=self.root/'new'
        with patch.object(app.QFileDialog,'getExistingDirectory',return_value=str(chosen)),patch.object(w,'ask_folder_action',return_value='new'):w.choose_folder()
        self.assertEqual(settings.destination(),chosen);self.assertTrue(self.file.exists())
        chosen2=self.root/'moved'
        with patch.object(app.QFileDialog,'getExistingDirectory',return_value=str(chosen2)),patch.object(w,'ask_folder_action',return_value='move'),patch.object(settings,'relocate',return_value=2) as relocate:
            w.choose_folder();wait(lambda:not w.jobs);relocate.assert_called_once_with(str(chosen2))
    def test_same_library_is_not_rebuilt_on_poll(self):
        w=self.open();w.list.setCurrentIndex(w.model.index(0,0));old_id=w.selected_row['id']
        with patch.object(w.model,'replace',wraps=w.model.replace) as replacement:self.reload();replacement.assert_not_called()
        self.assertEqual(w.selected_row['id'],old_id)
    def test_background_updates_preserve_scroll_position(self):
        with m.db() as c:
            for ident in range(10,150):c.execute('INSERT INTO tracks(id,title,position,liked,status) VALUES(?,?,?,1,\'pending\')',(str(ident),'Песня '+str(ident),ident))
        w=self.open();w.list.verticalScrollBar().setValue(380)
        with m.db() as c:c.execute("UPDATE tracks SET title='Изменено' WHERE id='100'")
        self.reload();self.assertEqual(w.list.verticalScrollBar().value(),380)
    def test_reload_delivers_changes_while_periodic_poll_has_another_read_queued(self):
        w=self.open()
        with m.db() as c:c.execute("UPDATE tracks SET title='Новая версия' WHERE id='1'")
        w.request_snapshot();w.request_snapshot();self.assertTrue(w.snapshot_again)
        self.reload();self.assertEqual(next(row for row in w.rows if row['id']=='1')['title'],'Новая версия')
    def test_background_job_keeps_ui_alive_and_close_waits(self):
        w=self.open();gate=threading.Event();w.job(lambda:gate.wait(3),lambda _:None);w.search.setText('Demo Artist');self.assertEqual(w.model.rowCount(),1);w.close();self.assertTrue(w.isVisible());self.assertTrue(m.STOP.exists());gate.set();wait(lambda:not w.isVisible());self.assertFalse(w.auto_timer.isActive())
    def test_notification_rules(self):
        w=self.open();w.tray=Mock();self.status('done',200);w.meta['last_added']='0';w.rows=[r for r in w.rows if r['status']=='downloaded'];w.automatic_run=True;w.notify_result();w.tray.showMessage.assert_not_called();w.meta['last_added']='2';w.notify_result();w.tray.showMessage.assert_called_once();self.status('needs_login',300);w.notify_result();w.notify_result();self.assertEqual(w.tray.showMessage.call_count,2);settings.save({'notify_results':False});w.notify_result();self.assertEqual(w.tray.showMessage.call_count,2)
    def test_device_login_can_resume_and_explicit_login_keeps_validated_account(self):
        auth.DEVICE.write_text(json.dumps({'expires_at':time.time()+300,'user_code':'TEST123','verification_url':'https://ya.ru/device'}));w=self.open();self.assertTrue(w.login_pending);w.nav_buttons[2].click();self.assertTrue(w.code_card.isVisible());self.assertEqual(w.code_label.text(),'TEST123')
        w.authorized({'name':'Проверенный аккаунт'});self.assertFalse(w.login_pending);self.assertFalse(auth.DEVICE.exists());self.assertEqual(settings.load()['account_name'],'Проверенный аккаунт')
    def test_expired_saved_login_is_flagged_without_erasing_credentials(self):
        auth.AUTH.write_text('{"access_token":"fixture-existing-auth"}');before=auth.AUTH.read_bytes();w=self.open()
        with patch.object(m,'api',side_effect=auth.AuthRequired()):REAL_ACCOUNT_CHECK(w);wait(lambda:not w.jobs)
        w.refresh();self.assertEqual(w.last_status['state'],'needs_login');self.assertEqual(auth.AUTH.read_bytes(),before);self.assertTrue(w.notice.isVisible());self.assertEqual(w.account_status.text(),'Нужен повторный вход')

if __name__=='__main__':unittest.main(verbosity=2)
