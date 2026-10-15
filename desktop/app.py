"""Native desktop companion: Material styling, external playback, manual by default."""
from __future__ import annotations
from pathlib import Path
import json,sys,time
from PySide6.QtCore import Qt,QTimer,QThread,Signal,QProcess,QUrl,QLockFile,QSize
from PySide6.QtGui import QDesktopServices,QFont,QIcon,QAction,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QLineEdit,QProgressBar,QFileDialog,QMessageBox,QFrame,QScrollArea,QStackedWidget,
    QComboBox,QButtonGroup,QDialog,QTextBrowser,QSystemTrayIcon,QMenu,QPushButton,QLayout)
import auth,settings,library
import music_export as m
from music_export import worker_running as running
from runtime_paths import sync_worker_command
from native_ui import Theme,Switch,NavButton,RoundedArt,Artwork,MusicModel,MusicList,SongDelegate,SwipeCard,button,icon,fade,ROLE

VERSION='2.0.4'
PHASES={'cataloging':'Проверка избранного','downloading':'Скачивание музыки','enriching':'Обложки и тексты','stopped':'Синхронизация остановлена','failed':'Синхронизация не завершена','needs_login':'Нужен вход в Яндекс'}

class Job(QThread):
    result=Signal(object);error=Signal(str)
    def __init__(self,action,parent=None):super().__init__(parent);self.action=action
    def run(self):
        try:self.result.emit(self.action())
        except Exception as exc:self.error.emit(m.safe_error(exc))

class Window(QMainWindow):
    def __init__(self):
        super().__init__();m.initialize();self.setWindowTitle('Моя музыка');self.setWindowIcon(QIcon(str(auth.ROOT/'music.ico')));self.resize(1120,800);self.setMinimumSize(820,600)
        self.jobs={};self.closing=False;self.login_pending=False;self.login_busy=False;self.snapshot_pending=False;self.snapshot_again=False;self.rows=[];self.meta={};self.rows_signature=None;self.selected_row=None;self.scope='all';self.last_status={};self.sync_started=0;self.automatic_run=False;self.task_message='';self.notice_key='';self.last_notified='';self.snapshot_jobs=set()
        self.artwork=Artwork(self);self.artwork.loaded.connect(self.art_loaded);self.theme=Theme.from_mode(settings.load()['theme']);self.process=QProcess(self);self.process.finished.connect(self.worker_finished);self.process.errorOccurred.connect(self.worker_error)
        self.build();self.apply_theme();self.make_tray();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1000)
        self.login_timer=QTimer(self);self.login_timer.setInterval(5000);self.login_timer.timeout.connect(self.poll_login);self.auto_timer=QTimer(self);self.auto_timer.setInterval(60000);self.auto_timer.timeout.connect(self.auto_check);self.auto_timer.start()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_theme_changed);QApplication.instance().paletteChanged.connect(self.system_theme_changed)
        self.close_timer=QTimer(self);self.close_timer.setInterval(100);self.close_timer.timeout.connect(self.finish_close);self.closed=False
        screen=QApplication.instance().primaryScreen()
        if screen:
            area=screen.availableGeometry();self.resize(min(1120,max(820,area.width()-80)),min(800,max(600,area.height()-80)))
        self.restore_login();self.refresh();QTimer.singleShot(200,self.check_account);QTimer.singleShot(1500,self.auto_check)

    def label(self,text='',kind='',parent=None):
        value=QLabel(text,parent);value.setObjectName(kind);value.setTextFormat(Qt.TextFormat.PlainText);return value
    def vbox(self,parent,margins=(0,0,0,0),spacing=12):
        layout=QVBoxLayout(parent);layout.setContentsMargins(*margins);layout.setSpacing(spacing);return layout
    def build(self):
        root=QWidget();root.setObjectName('root');self.setCentralWidget(root);layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        rail=QWidget();rail.setObjectName('rail');rail.setFixedWidth(104);nav=self.vbox(rail,(10,24,10,20),10)
        brand=QLabel();brand.setAlignment(Qt.AlignmentFlag.AlignCenter);brand.setPixmap(QIcon(str(auth.ROOT/'music.ico')).pixmap(48,48));nav.addWidget(brand);nav.addSpacing(24)
        self.nav_group=QButtonGroup(self);self.nav_buttons=[]
        for at,(title,name) in enumerate((('Библиотека','library'),('Настройки','settings'),('Аккаунт','account'))):
            b=NavButton(title,name);self.nav_group.addButton(b,at);self.nav_buttons.append(b);nav.addWidget(b)
        nav.addStretch();self.open_folder_button=button('', 'folder','icon','Открыть папку музыки');self.open_folder_button.clicked.connect(self.open_folder);nav.addWidget(self.open_folder_button,0,Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rail);main=QWidget();body=self.vbox(main,(28,24,28,20),16);layout.addWidget(main,1)
        self.pages=QStackedWidget();body.addWidget(self.pages,1);self.build_library();self.build_settings();self.build_account()
        self.notice=SwipeCard();self.notice.dismissed.connect(self.dismiss_notice);n=QVBoxLayout(self.notice);n.setContentsMargins(18,10,8,14);n.setSpacing(8);row=QHBoxLayout();labels=QVBoxLayout();labels.setSpacing(4);self.notice_title=self.label();self.notice_detail=self.label('', 'muted');labels.addWidget(self.notice_title);labels.addWidget(self.notice_detail);row.addLayout(labels,1);self.notice_count=self.label('', 'muted');row.addWidget(self.notice_count);self.notice_action=button('', 'stop','icon','Остановить синхронизацию');self.notice_action.clicked.connect(self.notice_clicked);row.addWidget(self.notice_action);self.dismiss_button=button('', 'close','icon','Скрыть уведомление');self.dismiss_button.clicked.connect(self.dismiss_notice);row.addWidget(self.dismiss_button);n.addLayout(row);self.progress=QProgressBar();self.progress.setFixedHeight(4);self.progress.setTextVisible(False);n.addWidget(self.progress);body.addWidget(self.notice);self.notice.hide()
        for label in (self.notice_title,self.notice_detail,self.notice_count):label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.snackbar=QFrame();self.snackbar.setObjectName('snackbar');s=QHBoxLayout(self.snackbar);s.setContentsMargins(18,4,8,4);self.snack_label=self.label();s.addWidget(self.snack_label,1);self.undo_button=button('Отменить',kind='textButton');self.undo_button.clicked.connect(self.undo);s.addWidget(self.undo_button);self.snack_close=button('', 'close','icon','Закрыть сообщение');self.snack_close.clicked.connect(self.snackbar.hide);s.addWidget(self.snack_close);body.addWidget(self.snackbar);self.snackbar.hide();self.snack_timer=QTimer(self);self.snack_timer.setSingleShot(True);self.snack_timer.timeout.connect(self.snackbar.hide);self.undo_action=None
        self.nav_group.idClicked.connect(self.navigate);self.nav_buttons[0].setChecked(True)
        for key,slot in (('Ctrl+F',self.focus_search),('F5',self.sync),('Delete',self.remove_selected_archive)):
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(slot);self.addAction(action)

    def header(self,layout,title,detail='',sync=False):
        row=QHBoxLayout();labels=QVBoxLayout();labels.setSpacing(6);heading=self.label(title,'heading');labels.addWidget(heading);subtitle=self.label(detail,'muted');subtitle.setVisible(bool(detail));labels.addWidget(subtitle);row.addLayout(labels,1)
        if sync:self.sync_button=button('', 'sync','icon','Синхронизировать избранное');self.sync_button.setObjectName('primary');self.sync_button.setFixedSize(48,48);self.sync_button.clicked.connect(lambda:self.sync());row.addWidget(self.sync_button)
        layout.addLayout(row);return subtitle
    def build_library(self):
        page=QWidget();page.setObjectName('page');layout=self.vbox(page,(0,0,0,0),16);self.summary=self.header(layout,'Моя музыка','Избранное из Яндекс Музыки',True)
        box=QFrame();box.setObjectName('searchBox');box.setFixedHeight(56);searchrow=QHBoxLayout(box);searchrow.setContentsMargins(16,0,8,0);searchrow.setSpacing(12);self.search_icon=self.label();self.search_icon.setFixedSize(24,24);searchrow.addWidget(self.search_icon);self.search=QLineEdit();self.search.setObjectName('search');self.search.setPlaceholderText('Поиск по библиотеке');self.search.setAccessibleName('Поиск по библиотеке');self.search.setFrame(False);searchrow.addWidget(self.search,1);self.search_clear=button('', 'close','icon','Очистить поиск');self.search_clear.clicked.connect(self.search.clear);searchrow.addWidget(self.search_clear);self.search_clear.hide();self.search.textChanged.connect(self.apply_filter);layout.addWidget(box)
        filters=QHBoxLayout();filters.setSpacing(8);self.filter_group=QButtonGroup(self);self.chips={}
        for at,(key,title) in enumerate((('all','Все'),('downloaded','Скачано'),('missing','Не скачано'),('archive','Архив'))):
            b=button(title,kind='chip');b.setCheckable(True);self.filter_group.addButton(b,at);self.chips[key]=b;filters.addWidget(b);b.clicked.connect(lambda checked=False,key=key:self.set_scope(key))
        self.chips['all'].setChecked(True);filters.addStretch();self.archive_clear=button('Очистить архив','close','textButton');self.archive_clear.clicked.connect(lambda:self.remove_archive(None));filters.addWidget(self.archive_clear);self.archive_clear.hide();layout.addLayout(filters)
        librarybody=QHBoxLayout();librarybody.setSpacing(20);listbody=QWidget();ll=self.vbox(listbody,(0,0,0,0),0);self.model=MusicModel(self);self.list=MusicList();self.list.setModel(self.model);self.delegate=SongDelegate(self.list,self.artwork);self.list.setItemDelegate(self.delegate);self.list.actionRequested.connect(self.row_action);self.list.doubleClicked.connect(lambda index:self.play(index.data(ROLE)));self.list.selectionModel().currentChanged.connect(self.selection_changed);ll.addWidget(self.list,1)
        self.empty=QWidget();el=self.vbox(self.empty);el.addStretch();self.empty_icon=self.label();self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter);el.addWidget(self.empty_icon);self.empty_title=self.label('Пока пусто','songTitle');self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter);el.addWidget(self.empty_title);self.empty_action=button('Синхронизировать','sync','primary');self.empty_action.clicked.connect(lambda:self.sync());el.addWidget(self.empty_action,0,Qt.AlignmentFlag.AlignHCenter);el.addStretch();ll.addWidget(self.empty,1);self.empty.hide();librarybody.addWidget(listbody,1)
        self.detail=QFrame();self.detail.setObjectName('detail');self.detail.setFixedWidth(288);detail_outer=self.vbox(self.detail,(0,0,0,0),0);detail_scroll=QScrollArea();detail_scroll.setWidgetResizable(True);detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);detail_panel=QWidget();self.detail_layout=self.vbox(detail_panel,(20,20,20,20),12);self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);detail_scroll.setWidget(detail_panel);detail_outer.addWidget(detail_scroll);self.detail.hide();librarybody.addWidget(self.detail);layout.addLayout(librarybody,1);self.pages.addWidget(page)

    def scroll_page(self,title):
        page=QWidget();page.setObjectName('page');outer=self.vbox(page);self.header(outer,title);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);panel=QWidget();layout=self.vbox(panel,(0,4,8,16),12);scroll.setWidget(panel);outer.addWidget(scroll,1);self.pages.addWidget(page);return layout
    def group(self,layout):
        card=QFrame();card.setObjectName('card');body=self.vbox(card,(4,4,4,4),0);layout.addWidget(card);return body
    def section(self,layout,title):layout.addSpacing(8);layout.addWidget(self.label(title,'section'))
    def setting_row(self,layout,name,title,description='',control=None):
        row=QWidget();rl=QHBoxLayout(row);rl.setContentsMargins(16,14,12,14);rl.setSpacing(16);glyph=self.label();glyph.setProperty('glyphName',name);glyph.setFixedSize(24,24);rl.addWidget(glyph);labels=QVBoxLayout();labels.setSpacing(4);labels.addWidget(self.label(title));detail=self.label(description,'muted');detail.setWordWrap(True);detail.setVisible(bool(description));labels.addWidget(detail);rl.addLayout(labels,1)
        if control:rl.addWidget(control)
        layout.addWidget(row);return row,detail
    def build_settings(self):
        layout=self.scroll_page('Настройки');group=self.group(layout);self.choose_button=button('', 'chevron','icon','Выбрать папку сохранения');self.choose_button.clicked.connect(self.choose_folder);_,self.destination=self.setting_row(group,'folder','Папка сохранения',str(settings.destination()),self.choose_button)
        cfg=settings.load();self.section(layout,'Синхронизация');group=self.group(layout);self.auto_switch=Switch('Автосинхронизация');self.auto_switch.setChecked(cfg['auto_sync']);self.setting_row(group,'sync','Автосинхронизация','Пока приложение открыто',self.auto_switch);self.auto_switch.toggled.connect(self.auto_toggled)
        self.interval=QComboBox();self.interval.setAccessibleName('Проверять избранное');self.interval.addItem('Каждый час',1);self.interval.addItem('Каждые 6 часов',6);self.interval.addItem('Раз в день',24);self.interval.setCurrentIndex(max(0,self.interval.findData(cfg['auto_hours'])));self.setting_row(group,'clock','Проверять избранное',control=self.interval);self.interval.currentIndexChanged.connect(lambda _:settings.save({'auto_hours':self.interval.currentData()}))
        self.wifi_switch=Switch('Только Wi-Fi');self.wifi_switch.setChecked(cfg['wifi_only']);self.setting_row(group,'wifi','Только Wi-Fi',control=self.wifi_switch);self.wifi_switch.toggled.connect(lambda on:settings.save({'wifi_only':on}))
        self.section(layout,'Файлы');group=self.group(layout);self.lyrics_switch=Switch('Тексты песен');self.lyrics_switch.setChecked(cfg['lyrics']);self.setting_row(group,'lyrics','Тексты песен','Сохранять .txt и .lrc',self.lyrics_switch);self.lyrics_switch.toggled.connect(lambda on:settings.save({'lyrics':on}));self.retry_button=button('', 'chevron','icon','Обновить обложки и тексты');self.retry_button.clicked.connect(self.retry_extras);self.setting_row(group,'sync','Обновить обложки и тексты',control=self.retry_button)
        self.section(layout,'Оформление');group=self.group(layout);self.theme_combo=QComboBox();self.theme_combo.setAccessibleName('Тема');self.theme_combo.addItem('Тёмная','dark');self.theme_combo.addItem('Светлая','light');self.theme_combo.addItem('От Windows','system');self.theme_combo.setCurrentIndex(max(0,self.theme_combo.findData(cfg['theme'])));self.setting_row(group,'theme','Тема',control=self.theme_combo);self.theme_combo.currentIndexChanged.connect(self.theme_changed)
        self.section(layout,'Уведомления');group=self.group(layout);self.results_switch=Switch('Итоги синхронизации');self.results_switch.setChecked(cfg['notify_results']);self.setting_row(group,'notifications','Итоги синхронизации',control=self.results_switch);self.results_switch.toggled.connect(lambda on:settings.save({'notify_results':on}));notifications=button('', 'external','icon','Настройки уведомлений Windows');notifications.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('ms-settings:notifications')));self.setting_row(group,'notifications','Настройки Windows',control=notifications)
        layout.addSpacing(12);logs=button('Открыть журнал',kind='textButton');logs.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(auth.DATA/'music.log'))));layout.addWidget(logs,0,Qt.AlignmentFlag.AlignHCenter);version=self.label('Моя музыка · '+VERSION,'muted');version.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(version);layout.addStretch()

    def build_account(self):
        layout=self.scroll_page('Аккаунт');identity=QWidget();il=self.vbox(identity,(0,16,0,12),12);self.avatar=self.label('','avatar');self.avatar.setProperty('emptyAvatar',True);self.avatar.setFixedSize(88,88);self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter);il.addWidget(self.avatar,0,Qt.AlignmentFlag.AlignHCenter);self.account_name=self.label('Твоё избранное','songTitle');self.account_name.setAlignment(Qt.AlignmentFlag.AlignCenter);il.addWidget(self.account_name);self.account_status=self.label('Подключи аккаунт','muted');self.account_status.setWordWrap(True);self.account_status.setAlignment(Qt.AlignmentFlag.AlignCenter);il.addWidget(self.account_status);layout.addWidget(identity)
        self.login_button=button('Войти через Яндекс','external','primary');self.login_button.clicked.connect(self.login);layout.addWidget(self.login_button)
        self.code_card=QFrame();self.code_card.setObjectName('card');c=self.vbox(self.code_card,(20,20,20,20),12);c.addWidget(self.label('Код для входа','muted'));self.code_label=self.label('','songTitle');self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);self.code_label.setFont(QFont('Consolas',22));c.addWidget(self.code_label);actions=QHBoxLayout();copy=button('Копировать','copy');copy.clicked.connect(lambda:(QApplication.clipboard().setText(self.code_label.text()),self.snack('Код скопирован')));actions.addWidget(copy);self.code_url='';self.code_open=button('Яндекс','external','primary');self.code_open.clicked.connect(self.open_code_site);actions.addWidget(self.code_open);c.addLayout(actions);self.confirm_button=button('Проверить вход',kind='textButton');self.confirm_button.clicked.connect(self.poll_login);c.addWidget(self.confirm_button);layout.addWidget(self.code_card);self.code_card.hide()
        self.token_button=button('Вставить токен',kind='textButton');self.token_button.clicked.connect(self.token_dialog);layout.addWidget(self.token_button);layout.addStretch()
        try:
            saved=auth.read_auth().get('account',{}) if auth.AUTH.exists() else {}
            if auth.AUTH.exists():self.set_account(saved or {'name':settings.load().get('account_name') or 'Аккаунт Яндекса'})
        except (OSError,ValueError,RuntimeError):pass

    def apply_theme(self):
        self.theme=Theme.from_mode(settings.load()['theme']);self.setStyleSheet(self.theme.css());self.delegate.theme=self.theme
        for widget in self.findChildren(QPushButton):
            name=widget.property('iconName')
            if name:widget.setIcon(icon(name,self.theme.on_primary_container if widget.objectName()=='primary' or widget.isChecked() else self.theme.primary if widget.objectName()=='textButton' else self.theme.muted))
        for widget in self.findChildren(Switch):widget.theme=self.theme;widget.update()
        for widget in self.nav_buttons:widget.theme=self.theme;widget.update()
        for widget in self.findChildren(RoundedArt):widget.theme=self.theme;widget.update()
        for widget in self.findChildren(QLabel):
            if widget.property('glyphName'):widget.setPixmap(icon(widget.property('glyphName'),self.theme.muted).pixmap(24,24))
        self.search_icon.setPixmap(icon('search',self.theme.muted).pixmap(24,24));self.empty_icon.setPixmap(icon('library',self.theme.muted,48).pixmap(48,48));self.list.viewport().update()
        if self.avatar.property('emptyAvatar'):self.avatar.setPixmap(icon('account',self.theme.on_primary_container,32).pixmap(32,32))
        try:
            import ctypes
            value=ctypes.c_int(int(self.theme.dark));ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()),20,ctypes.byref(value),4)
        except (AttributeError,OSError):pass
        if hasattr(self,'timer'):self.refresh()
    def theme_changed(self):settings.save({'theme':self.theme_combo.currentData()});self.apply_theme();fade(self.pages)
    def system_theme_changed(self,*_):
        if settings.load()['theme']=='system':self.apply_theme()
    def navigate(self,at):self.pages.setCurrentIndex(at);self.apply_theme();fade(self.pages)
    def focus_search(self):self.nav_buttons[0].click();self.search.setFocus();self.search.selectAll()
    def set_scope(self,scope):self.scope=scope;self.apply_filter();fade(self.list)
    def apply_filter(self,*_,preserve_scroll=False):
        previous=self.selected_row;selected=previous['id'] if previous else None;scroll=self.list.verticalScrollBar().value();rows=library.filtered(self.rows,self.scope,self.search.text());self.model.replace(rows);self.search_clear.setVisible(bool(self.search.text()));self.archive_clear.setVisible(self.scope=='archive' and any(not r['liked'] for r in self.rows));self.list.setVisible(bool(rows));self.empty.setVisible(not rows)
        likes=[r for r in self.rows if r['liked']];count=sum(r['status']=='downloaded' for r in likes);self.summary.setText(library.tracks(sum(not r['liked'] for r in self.rows))+' в архиве' if self.scope=='archive' else library.tracks(count)+' на компьютере' if likes else 'Избранное из Яндекс Музыки');self.summary.show()
        self.empty_title.setText('Ничего не найдено' if self.search.text().strip() else 'Архив пуст' if self.scope=='archive' else 'Всё скачано' if self.scope=='missing' and likes else 'Пока нет скачанных треков' if self.scope=='downloaded' else 'Пока пусто');self.empty_action.setVisible(not likes and self.scope!='archive' and not self.search.text().strip())
        found=next((n for n,r in enumerate(rows) if r['id']==selected),None)
        if found is not None:
            self.list.selectionModel().blockSignals(True);self.list.setCurrentIndex(self.model.index(found,0));self.list.selectionModel().blockSignals(False);self.selected_row=rows[found]
            if previous!=self.selected_row:self.show_details(self.selected_row)
        else:self.selected_row=None;self.detail.hide()
        if preserve_scroll:self.list.doItemsLayout();self.list.verticalScrollBar().setValue(scroll)
    def selection_changed(self,index,*_):
        row=index.data(ROLE)
        if row:self.selected_row=row;self.show_details(row)
    def clear_layout(self,layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():self.clear_layout(item.layout())
    def detail_content(self,layout,row):
        art=RoundedArt(192,24);art.image=self.artwork.get(row);art.setProperty('coverKey',self.artwork.key(row));art.theme=self.theme;layout.addWidget(art,0,Qt.AlignmentFlag.AlignHCenter);title=self.label(row.get('title') or '','songTitle');title.setWordWrap(True);layout.addWidget(title);artist=self.label(row.get('artist') or '', 'muted');artist.setWordWrap(True);layout.addWidget(artist)
        info=' · '.join(str(row.get(k) or '') for k in ('album','year') if row.get(k))
        if info:value=self.label(info,'muted');value.setWordWrap(True);layout.addWidget(value)
        path=Path(row['path']) if row.get('path') else None;downloaded=row['status']=='downloaded' and path is not None and path.is_file()
        if downloaded:
            play=button('Слушать','play','primary');play.clicked.connect(lambda:self.play(row));layout.addWidget(play)
            if path.with_suffix('.txt').is_file() or path.with_suffix('.lrc').is_file():lyrics=button('Текст песни','lyrics');lyrics.clicked.connect(lambda:self.open_lyrics(row));layout.addWidget(lyrics)
        else:
            value=self.label(row.get('error') or ('Недоступен для скачивания' if row['status']=='unavailable' else 'Трек пока не скачан'),'error');value.setWordWrap(True);layout.addWidget(value)
            if row['liked']:retry=button('Повторить','sync','primary');retry.clicked.connect(lambda:self.sync());layout.addWidget(retry)
        if not row['liked']:remove=button('Убрать из архива','close','textButton');remove.clicked.connect(lambda:self.remove_archive([row['id']]));layout.addWidget(remove)
        layout.addStretch();return art
    def show_details(self,row):self.clear_layout(self.detail_layout);self.detail_content(self.detail_layout,row);self.detail.show();self.apply_detail_icons();fade(self.detail)
    def apply_detail_icons(self):
        for b in self.detail.findChildren(QPushButton):
            if b.property('iconName'):b.setIcon(icon(b.property('iconName'),self.theme.on_primary_container if b.objectName()=='primary' else self.theme.primary))
    def art_loaded(self,key,image):
        self.list.viewport().update()
        for widget in self.findChildren(RoundedArt):
            if widget.property('coverKey')==key:widget.image=image;widget.update()
    def row_action(self,row):
        if not row['liked']:self.remove_archive([row['id']])
        elif row['status']=='downloaded':self.play(row)
        elif row['status']=='unavailable':self.selected_row=row;self.show_details(row)
        else:self.sync()
    def play(self,row=None):
        row=row or self.selected_row
        if not row or row['status']!='downloaded':return
        path=Path(row['path'] or '')
        if not path.is_file():self.snack('Файл отсутствует. Запусти синхронизацию');return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):self.show_error('Не удалось открыть песню в плеере Windows')
    def open_lyrics(self,row=None):
        row=row or self.selected_row
        if not row or not row.get('path'):return
        path=Path(row['path']).with_suffix('.txt')
        if not path.is_file():path=path.with_suffix('.lrc')
        if not path.is_file():self.snack('Для этой песни текст не выдан');return
        def show(value):
            dialog=QDialog(self);dialog.setWindowTitle('Текст песни');dialog.resize(520,620);body=self.vbox(dialog,(24,24,24,20),16);heading=self.label(row['title'],'songTitle');heading.setWordWrap(True);body.addWidget(heading);text=QTextBrowser();text.setPlainText(value);text.setOpenExternalLinks(False);body.addWidget(text,1);close=button('Закрыть');close.clicked.connect(dialog.accept);body.addWidget(close);dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);dialog.show();fade(dialog)
        def read():
            value=path.read_text(encoding='utf-8-sig')
            if path.suffix=='.lrc':
                from music_lyrics import plain
                value=plain({'format':'LRC','text':value})
            return value
        self.job(read,show,busy=False)

    def is_active(self):return self.process.state()!=QProcess.ProcessState.NotRunning or running()
    def busy(self):return self.closing or self.is_active() or any(self.jobs.values())
    def job(self,action,success,error=None,busy=True,message='Подождите…'):
        if self.closing:return
        task=Job(action,self);self.jobs[task]=busy
        if busy:self.task_message=message
        task.result.connect(lambda result:success(result) if not self.closing else None);task.error.connect(error or self.show_error)
        def done():
            self.jobs.pop(task,None);task.deleteLater();self.refresh()
            if self.closing:self.finish_close()
        task.finished.connect(done);task.start();self.refresh();return task
    def request_snapshot(self):
        if self.closing:return
        if self.snapshot_pending:self.snapshot_again=True;return
        self.snapshot_pending=True
        def received(value):
            if self.closing:return
            rows,meta=value;self.meta=meta;signature=tuple(tuple(r.items()) for r in rows)
            if signature!=self.rows_signature:self.rows_signature=signature;self.rows=rows;self.apply_filter(preserve_scroll=True)
        task=Job(library.snapshot,self);task.result.connect(received);task.error.connect(lambda _:setattr(self,'snapshot_pending',False))
        def done():
            self.snapshot_jobs.discard(task);task.deleteLater();self.snapshot_pending=False
            if self.snapshot_again:self.snapshot_again=False;self.request_snapshot()
        task.finished.connect(done);self.snapshot_jobs.add(task);task.start()
    def refresh(self):
        if self.closing:self.finish_close();return
        self.request_snapshot();active=self.is_active();locked=active or any(self.jobs.values());self.sync_button.setEnabled(not locked)
        for control in (self.choose_button,self.retry_button,self.login_button,self.token_button,self.lyrics_switch,self.archive_clear):control.setEnabled(not locked)
        self.destination.setText(str(settings.destination()));cfg=settings.load();self.interval.setEnabled(cfg['auto_sync']);self.wifi_switch.setEnabled(cfg['auto_sync']);self.last_status=self.read_status();data=self.last_status;state=data.get('state','ready');missing=sum(r['liked'] and r['status']!='downloaded' for r in self.rows)
        if state=='needs_login':self.account_status.setText('Нужен повторный вход')
        key=f"{state}:{data.get('updated',0)}:{missing}";self.notice_key=key
        attention=not locked and (state in ('failed','needs_login') or state in ('paused','done') and missing>0) and key!=cfg.get('dismissed_banner_key')
        self.notice.setVisible(locked or attention);self.notice.dismissible=attention;self.dismiss_button.setVisible(attention);self.notice_action.setVisible(active or attention);self.progress.setVisible(locked);self.notice_title.setStyleSheet('color:'+self.theme.error+';' if attention else '')
        if locked:
            self.notice_title.setText(PHASES.get(state,'Синхронизация') if active else self.task_message);self.notice_detail.setText(data.get('message','') if active else '');self.notice_detail.setVisible(active and bool(data.get('message')));total=int(data.get('work_total') or 0) if active else 0;self.progress.setRange(0,total);self.progress.setValue(min(total,int(data.get('work_completed') or 0)));self.notice_count.setText(f"{data.get('work_completed',0)} / {total}" if total else '');self.notice_action.setIcon(icon('stop',self.theme.muted));self.notice_action.setAccessibleName('Остановить синхронизацию')
        elif attention:self.notice_title.setText(PHASES[state] if state in ('failed','needs_login') else 'Не скачано: '+library.tracks(missing));self.notice_detail.hide();self.notice_count.clear();self.notice_action.setIcon(icon('account' if state=='needs_login' else 'sync',self.theme.muted));self.notice_action.setAccessibleName('Войти заново' if state=='needs_login' else 'Повторить синхронизацию')
        if getattr(self,'tray',None):self.tray.setToolTip(('Моя музыка\n'+PHASES.get(state,'Синхронизация')+(' · '+self.notice_count.text() if self.notice_count.text() else '')) if active else 'Моя музыка')
    def read_status(self):
        try:return json.loads(m.STATUS.read_text(encoding='utf-8')) if m.STATUS.exists() else {}
        except (OSError,ValueError):return self.last_status
    def dismiss_notice(self):
        if self.busy():return
        key=self.notice_key;settings.save({'dismissed_banner_key':key});self.refresh();self.snack('Уведомление скрыто',lambda:(settings.save({'dismissed_banner_key':''}),self.refresh()),'Вернуть')
    def notice_clicked(self):
        if self.is_active():self.stop()
        elif self.last_status.get('state')=='needs_login':self.nav_buttons[2].click()
        else:self.sync()
    def snack(self,text,undo=None,label='Отменить'):
        self.snack_label.setText(text);self.undo_action=undo;self.undo_button.setText(label);self.undo_button.setVisible(undo is not None);self.snackbar.show();self.snack_timer.start(7000);fade(self.snackbar)
    def undo(self):
        action=self.undo_action;self.undo_action=None;self.snackbar.hide()
        if action:action()
    def remove_archive(self,ids):
        if self.busy():self.snack('Дождись окончания синхронизации');return
        def done(changed):
            self.request_snapshot()
            if changed:self.snack('Убрано из архива. Файлы сохранены',lambda:self.job(lambda:library.restore_archive(changed),lambda _:self.request_snapshot(),message='Возвращаем в архив…'))
        self.job(lambda:library.hide_archive(ids),done,message='Обновляем архив…')
    def remove_selected_archive(self):
        if self.pages.currentIndex()==0 and self.selected_row and not self.selected_row['liked']:self.remove_archive([self.selected_row['id']])

    def sync(self,automatic=False):
        if self.busy():return
        if not auth.AUTH.exists() or self.last_status.get('state')=='needs_login':
            if not automatic:self.nav_buttons[2].click();self.snack('Войди в музыкальный аккаунт')
            return
        if settings.MOVE.exists():self.nav_buttons[1].click();self.snack('Заверши перенос в выбранную папку');return
        self.automatic_run=bool(automatic);self.sync_started=time.time();m.STOP.unlink(missing_ok=True);program,args=sync_worker_command(gui=True);self.process.setWorkingDirectory(str(auth.ROOT));self.process.start(program,args);self.refresh()
    def stop(self):m.STOP.touch();self.notice_title.setText('Останавливаем…');self.notice_action.setEnabled(False)
    def worker_finished(self,*_):
        self.notice_action.setEnabled(True);self.request_snapshot();self.refresh();QTimer.singleShot(200,self.notify_result)
        if self.closing:self.finish_close()
    def worker_error(self,_):
        if not self.closing:self.show_error('Не удалось запустить синхронизацию. Проверь журнал приложения')
    def retry_extras(self):
        if self.busy():return
        def reset():
            with m.db() as c:c.execute("UPDATE tracks SET lyrics_status='pending',lyrics_error=NULL WHERE lyrics_status IN ('unavailable','failed')");c.execute("UPDATE tracks SET cover_status='pending',cover_error=NULL WHERE cover_status IN ('unavailable','failed')")
        task=self.job(reset,lambda _:None,message='Обновляем обложки и тексты…');task.finished.connect(lambda:QTimer.singleShot(0,self.sync))
    def open_folder(self):path=settings.destination();path.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def ask_folder_action(self):
        dialog=QMessageBox(self);dialog.setWindowTitle('Папка сохранения');dialog.setText('Перенести скачанные песни в новую папку?');move=dialog.addButton('Перенести',QMessageBox.ButtonRole.AcceptRole);new=dialog.addButton('Только новые',QMessageBox.ButtonRole.ActionRole);dialog.addButton('Отмена',QMessageBox.ButtonRole.RejectRole);dialog.exec();return 'move' if dialog.clickedButton()==move else 'new' if dialog.clickedButton()==new else 'cancel'
    def choose_folder(self):
        if self.busy():return
        initial=str(settings.destination())
        if settings.MOVE.exists():initial=json.loads(settings.MOVE.read_text(encoding='utf-8'))['new']
        folder=QFileDialog.getExistingDirectory(self,'Папка сохранения',initial)
        if not folder or Path(folder).resolve()==settings.destination().resolve() and not settings.MOVE.exists():return
        if Path(folder).resolve()==Path(Path(folder).resolve().anchor):self.snack('Выбери папку для музыки');return
        action='move' if settings.MOVE.exists() else self.ask_folder_action() if int(self.meta.get('downloaded_total',0))>0 or any(r['status']=='downloaded' for r in self.rows) else 'new'
        if action=='cancel':return
        if action=='new':settings.save({'destination':str(Path(folder).resolve())});m.DEST=settings.destination();self.refresh();self.snack('Папка сохранена')
        else:self.job(lambda:settings.relocate(folder),lambda _:self.snack('Музыка перенесена'),message='Перенос музыки…')

    def auto_toggled(self,on):
        if on and not auth.AUTH.exists():self.auto_switch.setChecked(False);self.snack('Сначала войди в аккаунт');return
        settings.save({'auto_sync':on})
        if not on and self.automatic_run and self.is_active():self.stop()
        self.refresh()
    def auto_check(self):
        if self.closing or self.busy():return
        cfg=settings.load()
        if not cfg['auto_sync'] or self.login_pending or not auth.AUTH.exists() or self.last_status.get('state')=='needs_login':return
        last=max(float(self.meta.get('last_sync',0)),float(cfg.get('auto_checked_at',0)))
        if time.time()-last<int(cfg['auto_hours'])*3600:return
        if cfg['wifi_only']:
            from windows_support import wifi_connected
            if not wifi_connected():return
        settings.save({'auto_checked_at':time.time()});self.sync(automatic=True)

    def check_account(self):
        if self.closing or not auth.AUTH.exists():return
        def check():
            try:account=m.api('/account/status')['account']
            except auth.AuthRequired:m.status('Нужен повторный вход в Яндекс','needs_login');raise
            previous=auth.expected_uid()
            if previous and str(account['uid'])!=previous:raise RuntimeError('В токене другой аккаунт. Войди в прежний')
            return {'name':str(account.get('displayName') or 'Аккаунт Яндекса')}
        def checked(result):
            self.set_account(result);settings.save({'account_name':self.account_name.text()})
            if self.last_status.get('state')=='needs_login':m.status('Вход обновлён','ready')
        self.job(check,checked,self.account_error,busy=False)
    def set_account(self,account):
        name=account.get('name') or account.get('displayName') or 'Аккаунт Яндекса';self.account_name.setText(name);self.avatar.setProperty('emptyAvatar',False);self.avatar.setText(''.join(x[0] for x in name.split()[:2]).upper());self.account_status.setText('Подключён');self.login_button.setText('Обновить вход')
    def authorized(self,result):
        self.set_account(result.get('account',result));settings.save({'account_name':self.account_name.text()});self.login_pending=False;self.login_busy=False;self.login_timer.stop();self.code_card.hide()
        auth.DEVICE.unlink(missing_ok=True)
        if self.last_status.get('state')=='needs_login':m.status('Вход обновлён','ready')
    def restore_login(self):
        try:
            data=json.loads(auth.DEVICE.read_text(encoding='utf-8'))
            if data.get('expires_at',0)<=time.time():return
            self.code_label.setText(data['user_code']);self.code_url=data['verification_url'];self.login_pending=True;self.code_card.show();self.login_timer.start()
        except (OSError,ValueError,KeyError):pass
    def login(self):
        if self.busy():return
        self.login_pending=False;self.login_timer.stop();self.login_busy=True;self.job(auth.request_code,self.code_received,self.account_error,message='Получаем код входа…')
    def code_received(self,result):
        self.login_busy=False;self.login_pending=True;self.code_label.setText(result['user_code']);self.code_url=result['verification_url'];self.code_card.show();self.open_code_site();self.login_timer.start()
    def open_code_site(self):
        if self.code_url:QDesktopServices.openUrl(QUrl(self.code_url))
    def poll_login(self):
        if not self.login_pending or self.login_busy or self.closing:return
        self.login_busy=True
        def received(result):
            self.login_busy=False
            if result['state']=='authorized':self.authorized(result);self.snack('Аккаунт подключён')
            elif result['state'] in ('expired','error','idle'):self.login_pending=False;self.login_timer.stop();self.code_card.hide();self.account_status.setText('Код истёк — получи новый')
            elif result.get('interval'):self.login_timer.setInterval(int(result['interval'])*1000)
        self.job(auth.poll,received,self.account_error,busy=False)
    def account_error(self,text):self.login_busy=False;self.account_status.setText(text)
    def token_dialog(self):
        if self.busy():return
        dialog=QDialog(self);dialog.setWindowTitle('Вставить токен');dialog.setMinimumWidth(440);body=self.vbox(dialog,(24,24,24,24),16);body.addWidget(self.label('Вставить токен','songTitle'));entry=QLineEdit();entry.setEchoMode(QLineEdit.EchoMode.Password);entry.setPlaceholderText('Токен');entry.setAccessibleName('Токен');body.addWidget(entry);actions=QHBoxLayout();show=button('Показать',kind='textButton');show.setCheckable(True);show.toggled.connect(lambda on:entry.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password));actions.addWidget(show);actions.addStretch();cancel=button('Отмена');cancel.clicked.connect(dialog.reject);actions.addWidget(cancel);save=button('Сохранить',kind='primary');actions.addWidget(save);body.addLayout(actions)
        def accept():
            value=entry.text().strip();entry.clear()
            if not value:return
            dialog.accept();self.job(lambda:auth.save_token(value),lambda result:(self.authorized(result),self.snack('Аккаунт подключён')),self.account_error,message='Проверяем вход…')
        save.clicked.connect(accept);entry.returnPressed.connect(accept);dialog.exec()
    def show_error(self,text):
        if not self.closing:self.snack(text)

    def make_tray(self):
        self.tray=None
        if not QSystemTrayIcon.isSystemTrayAvailable():return
        self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip('Моя музыка');menu=QMenu(self)
        for title,callback in (('Открыть',self.raise_window),('Синхронизировать',self.sync),('Остановить',self.stop)):
            action=menu.addAction(title);action.triggered.connect(lambda checked=False,callback=callback:callback())
        self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.raise_window() if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,QSystemTrayIcon.ActivationReason.Trigger) else None);self.tray.messageClicked.connect(lambda:(self.raise_window(),self.nav_buttons[2 if self.last_status.get('state')=='needs_login' else 0].click()));self.tray.show()
    def raise_window(self):self.showNormal();self.activateWindow();self.raise_()
    def notify_result(self):
        if self.closing or not self.tray or not settings.load()['notify_results']:return
        data=self.read_status();state=data.get('state');added=int(self.meta.get('last_added',0));missing=sum(r['liked'] and r['status']!='downloaded' for r in self.rows)
        if state not in ('done','paused','failed','needs_login','stopped'):return
        if self.automatic_run and state=='done' and not added and not missing:settings.save({'last_auto_error':''});return
        text='Нужен повторный вход в Яндекс' if state=='needs_login' else 'Синхронизация не завершена' if state=='failed' else 'Синхронизация остановлена' if state=='stopped' else 'Добавлено: '+library.tracks(added)+(f'. Не скачано: {library.tracks(missing)}' if missing else '')
        signature=state+':'+str(data.get('message',text))
        if self.automatic_run and state in ('failed','needs_login') and settings.load().get('last_auto_error')==signature:return
        if self.automatic_run:settings.save({'last_auto_error':signature if state in ('failed','needs_login') else ''})
        self.last_notified=text;self.tray.showMessage('Моя музыка',text,self.windowIcon(),6000)
    def closeEvent(self,event):
        self.closing=True;self.timer.stop();self.login_timer.stop();self.auto_timer.stop();self.login_pending=False
        if self.jobs or self.process.state()!=QProcess.ProcessState.NotRunning or running() or self.snapshot_jobs:
            m.STOP.touch();self.notice.show();self.notice_title.setText('Сохраняем прогресс…');self.notice_detail.hide();event.ignore();self.close_timer.start()
        else:
            self.closed=True;self.close_timer.stop()
            self.artwork.close()
            if self.tray:self.tray.hide()
            event.accept()
    def finish_close(self):
        if not self.closing or self.closed:return
        if not self.jobs and self.process.state()==QProcess.ProcessState.NotRunning and not running() and not self.snapshot_jobs:self.close()

def main():
    from windows_support import app_identity
    app_identity();qt=QApplication(sys.argv);qt.setApplicationName('Моя музыка');qt.setApplicationVersion(VERSION);qt.setFont(QFont('Segoe UI',10));lock=QLockFile(str(auth.DATA/'app_instance.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(0):QMessageBox.information(None,'Моя музыка','Приложение уже открыто. Найди его на панели задач');return 0
    window=Window();window.show();return qt.exec()
if __name__=='__main__':raise SystemExit(main())
