"""Material-inspired native Qt widgets, palette, list and local artwork cache."""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from collections import OrderedDict
import hashlib,weakref
from PySide6.QtCore import (Qt,QSize,QRect,QRectF,QPoint,QObject,Signal,QAbstractListModel,QModelIndex,
    QThreadPool,QRunnable,QPropertyAnimation,QEasingCurve,Property,QTimer,QEvent)
from PySide6.QtGui import (QColor,QPainter,QPainterPath,QFont,QPixmap,QImage,QIcon,QPalette,QPen)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication,QWidget,QFrame,QLabel,QAbstractButton,QListView,
    QStyledItemDelegate,QStyle,QGraphicsOpacityEffect,QPushButton,QHBoxLayout)

ASSETS=Path(__file__).resolve().parent/'assets'
ROLE=Qt.ItemDataRole.UserRole

def blend(a,b,amount):
    x,y=QColor(a),QColor(b)
    return QColor(round(x.red()*(1-amount)+y.red()*amount),round(x.green()*(1-amount)+y.green()*amount),round(x.blue()*(1-amount)+y.blue()*amount)).name()

@dataclass
class Theme:
    dark:bool;surface:str;low:str;container:str;high:str;text:str;muted:str;outline:str;primary:str;primary_container:str;on_primary_container:str;error:str
    @classmethod
    def from_mode(cls,mode,system_palette=None):
        qt=QApplication.instance();dark=mode=='dark' or mode=='system' and qt.styleHints().colorScheme()==Qt.ColorScheme.Dark
        if dark:t=cls(True,'#121212','#1A1A1A','#222222','#2C2C2C','#E6E6E6','#B6B6B6','#454545','#ABC7FF','#294778','#D8E2FF','#FFB4AA')
        else:t=cls(False,'#FAFAFA','#F4F4F4','#EEEEEE','#E7E7E7','#1B1B1B','#5C5C5C','#D0D0D0','#315DA8','#D8E2FF','#102E60','#A43830')
        if mode=='system':
            accent=(system_palette or qt.palette()).color(QPalette.ColorRole.Accent).name()
            t.primary=blend(accent,'#FFFFFF',.20) if dark else blend(accent,'#000000',.28)
            t.primary_container=blend(accent,t.surface,.66 if dark else .78)
            t.on_primary_container=t.text
        return t
    def css(self):
        return f'''
        QWidget {{color:{self.text};font-family:"Segoe UI";font-size:14px;}}
        QMainWindow,QWidget#root,QWidget#page,QDialog {{background:{self.surface};}}
        QWidget#rail,QFrame#card,QFrame#detail,QFrame#snackbar {{background:{self.low};border-radius:20px;}}
        QWidget#rail {{border-radius:0;}}
        QLabel {{background:transparent;border:0;}}
        QLabel#heading {{font-size:30px;font-weight:600;}}
        QLabel#section {{font-size:13px;color:{self.muted};font-weight:600;}}
        QLabel#muted {{color:{self.muted};font-size:13px;}}
        QLabel#songTitle {{font-size:22px;font-weight:600;}}
        QLabel#error {{color:{self.error};}}
        QLabel#avatar {{background:{self.primary_container};color:{self.on_primary_container};border-radius:44px;font-size:30px;font-weight:600;}}
        QPushButton {{background:transparent;border:1px solid {self.outline};border-radius:22px;padding:10px 18px;min-height:22px;}}
        QPushButton:hover {{background:{self.high};}}
        QPushButton:pressed {{background:{self.container};}}
        QPushButton:disabled {{color:{self.muted};border-color:{self.container};}}
        QPushButton#primary {{background:{self.primary_container};color:{self.on_primary_container};border:0;}}
        QPushButton#primary:hover {{background:{blend(self.primary_container,self.primary,.12)};}}
        QPushButton#icon {{border:0;padding:0;border-radius:24px;min-height:48px;}}
        QPushButton#icon:hover {{background:{self.container};}}
        QPushButton#nav {{border:0;padding:0;border-radius:22px;font-size:12px;min-height:76px;max-height:76px;}}
        QPushButton#nav:checked {{background:{self.primary_container};color:{self.on_primary_container};}}
        QPushButton#chip {{padding:6px 15px;min-height:20px;border-radius:12px;font-size:13px;}}
        QPushButton#chip:checked {{background:{self.primary_container};color:{self.on_primary_container};border-color:transparent;}}
        QPushButton#textButton {{border:0;color:{self.primary};}}
        QLineEdit {{background:{self.container};border:0;border-radius:20px;padding:14px 16px;selection-background-color:{self.primary_container};}}
        QLineEdit#search {{background:transparent;border:0;padding:0;font-size:16px;}}
        QFrame#searchBox {{background:{self.container};border-radius:28px;}}
        QComboBox {{background:{self.container};border:0;border-radius:12px;padding:10px 14px;min-width:130px;}}
        QComboBox::drop-down {{border:0;width:24px;}}
        QComboBox QAbstractItemView {{background:{self.low};selection-background-color:{self.primary_container};border:1px solid {self.outline};padding:8px;}}
        QListView {{background:transparent;border:0;outline:0;}}
        QScrollArea,QScrollArea>QWidget>QWidget {{background:transparent;border:0;}}
        QScrollBar:vertical {{background:transparent;width:8px;margin:4px 0;}}
        QScrollBar::handle:vertical {{background:{self.outline};border-radius:4px;min-height:36px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
        QProgressBar {{background:{self.outline};border:0;border-radius:2px;max-height:4px;}}
        QProgressBar::chunk {{background:{self.primary};border-radius:2px;}}
        QTextBrowser {{background:transparent;border:0;font-size:16px;selection-background-color:{self.primary_container};}}
        QToolTip {{background:{self.high};color:{self.text};border:0;padding:8px;border-radius:8px;}}
        '''

_icons={}
def icon(name,color,size=24):
    key=(name,color,size)
    if key not in _icons:
        path=ASSETS/('ic_'+name+'.svg');pix=QPixmap(size*2,size*2);pix.fill(Qt.GlobalColor.transparent)
        if path.exists():
            svg=path.read_bytes().replace(b'currentColor',color.encode());p=QPainter(pix);QSvgRenderer(svg).render(p);p.end()
        pix.setDevicePixelRatio(2);_icons[key]=QIcon(pix)
    return _icons[key]

def button(text='',name=None,kind='',tip=''):
    b=QPushButton(text);b.setObjectName(kind or 'button');b.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:b.setProperty('iconName',name);b.setIconSize(QSize(24,24))
    if tip:b.setToolTip(tip);b.setAccessibleName(tip)
    if kind=='icon':b.setFixedSize(48,48)
    return b

class Switch(QAbstractButton):
    def __init__(self,label,parent=None):
        super().__init__(parent);self.setCheckable(True);self.setAccessibleName(label);self.setToolTip(label);self.setFixedSize(52,40);self.setCursor(Qt.CursorShape.PointingHandCursor);self._position=0.;self.theme=Theme.from_mode('system');self.animation=QPropertyAnimation(self,b'position');self.animation.setDuration(160);self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic);self.toggled.connect(self._move)
    def _get(self):return self._position
    def _set(self,value):self._position=value;self.update()
    position=Property(float,_get,_set)
    def _move(self,checked):self.animation.stop();self.animation.setStartValue(self._position);self.animation.setEndValue(1. if checked else 0.);self.animation.start()
    def paintEvent(self,event):
        t=self.theme;p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():p.setOpacity(.4)
        p.setPen(QPen(QColor(t.outline),2) if not self.isChecked() else Qt.PenStyle.NoPen);p.setBrush(QColor(t.primary_container if self.isChecked() else t.container));p.drawRoundedRect(QRectF(1,4,50,32),16,16)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(t.on_primary_container if self.isChecked() else t.muted));r=10+2*self._position;x=16+20*self._position;p.drawEllipse(QPoint(int(x),20),int(r),int(r));p.end()

class NavButton(QPushButton):
    def __init__(self,title,name,parent=None):
        super().__init__(title,parent);self.name=name;self.theme=Theme.from_mode('system');self.keyboard_focus=False;self.setObjectName('nav');self.setCheckable(True);self.setAccessibleName(title);self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFixedHeight(76)
    def focusInEvent(self,event):self.keyboard_focus=event.reason() in (Qt.FocusReason.TabFocusReason,Qt.FocusReason.BacktabFocusReason,Qt.FocusReason.ShortcutFocusReason);super().focusInEvent(event)
    def mousePressEvent(self,event):self.keyboard_focus=False;super().mousePressEvent(event)
    def paintEvent(self,event):
        t=self.theme;p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        if self.isChecked() or self.underMouse():p.setBrush(QColor(t.primary_container if self.isChecked() else t.container));p.drawRoundedRect(QRectF(10,8,self.width()-20,32),16,16)
        icon(self.name,t.on_primary_container if self.isChecked() else t.muted).paint(p,QRect((self.width()-24)//2,12,24,24));font=QFont('Segoe UI');font.setPixelSize(12);font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal);p.setFont(font);p.setPen(QColor(t.text if self.isChecked() else t.muted));p.drawText(QRect(0,46,self.width(),22),Qt.AlignmentFlag.AlignCenter,self.text())
        if self.hasFocus() and self.keyboard_focus:p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(t.primary),1));p.drawRoundedRect(QRectF(2,2,self.width()-4,self.height()-4),14,14)
        p.end()

class RoundedArt(QLabel):
    def __init__(self,size=56,radius=12,parent=None):super().__init__(parent);self.setFixedSize(size,size);self.image=QImage();self.radius=radius;self.theme=Theme.from_mode('system')
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);path=QPainterPath();path.addRoundedRect(QRectF(self.rect()),self.radius,self.radius);p.setClipPath(path);p.fillRect(self.rect(),QColor(self.theme.container))
        if not self.image.isNull():
            scaled=self.image.scaled(self.size()*2,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation);side=min(scaled.width(),scaled.height());p.drawImage(self.rect(),scaled,QRect((scaled.width()-side)//2,(scaled.height()-side)//2,side,side))
        else:icon('note',self.theme.muted,24).paint(p,QRect((self.width()-24)//2,(self.height()-24)//2,24,24))
        p.end()

class Artwork(QObject):
    loaded=Signal(str,QImage)
    def __init__(self,parent=None):
        super().__init__(parent);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(2);self.images=OrderedDict();self.pending=set();self.closed=False;self.loaded.connect(self._ready)
    def key(self,row):return str(row['id'])+':'+str(row.get('path') or '')+':'+str(row.get('sha256') or row.get('cover_uri') or '')
    def get(self,row):
        key=self.key(row)
        if key in self.images:self.images.move_to_end(key);return self.images[key]
        if key not in self.pending and not self.closed:self.pending.add(key);self.pool.start(_LoadCover(self,row,key))
        return QImage()
    def _ready(self,key,image):
        self.pending.discard(key)
        if self.closed:return
        self.images[key]=image
        while len(self.images)>160:self.images.popitem(last=False)
    def close(self):self.closed=True;self.pool.clear();self.pool.waitForDone(3000)

class _LoadCover(QRunnable):
    def __init__(self,owner,row,key):super().__init__();self.owner=weakref.ref(owner);self.row=dict(row);self.key=key
    def run(self):
        image=QImage()
        try:
            import auth
            uri=self.row.get('cover_uri')
            if uri:
                url=(uri if uri.startswith('https://') else 'https://'+uri).replace('%%','400x400');path=auth.DATA/'cover_cache'/(hashlib.sha256(url.encode()).hexdigest()+'.image')
                if path.is_file():image.load(str(path))
            if image.isNull() and self.row.get('path'):
                from mutagen.id3 import ID3
                pictures=ID3(self.row['path']).getall('APIC')
                if pictures:image.loadFromData(pictures[0].data)
            if not image.isNull():image=image.scaled(400,400,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        except (OSError,ValueError):pass
        except Exception:pass
        owner=self.owner()
        if owner is not None and not owner.closed:owner.loaded.emit(self.key,image)

class MusicModel(QAbstractListModel):
    def __init__(self,parent=None):super().__init__(parent);self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        r=self.rows[index.row()]
        if role==ROLE:return r
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.AccessibleTextRole):return (r.get('title') or '')+' — '+(r.get('artist') or '')
        if role==Qt.ItemDataRole.ToolTipRole:return '\n'.join(x for x in (r.get('title'),r.get('artist'),r.get('album')) if x)
    def replace(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()

class MusicList(QListView):
    actionRequested=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMouseTracking(True);self.setUniformItemSizes(True);self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.setSpacing(2);self.setAccessibleName('Библиотека музыки');self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.scroll_animation=QPropertyAnimation(self.verticalScrollBar(),b'value',self);self.scroll_animation.setDuration(180);self.scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic);self._pressed_action=None
    def wheelEvent(self,event):
        bar=self.verticalScrollBar()
        if not event.pixelDelta().isNull():bar.setValue(bar.value()-event.pixelDelta().y());event.accept();return
        target=self.scroll_animation.endValue() if self.scroll_animation.state()==QPropertyAnimation.State.Running else bar.value();target=max(bar.minimum(),min(bar.maximum(),int(target or 0)-round(event.angleDelta().y()*1.1)));self.scroll_animation.stop();self.scroll_animation.setStartValue(bar.value());self.scroll_animation.setEndValue(target);self.scroll_animation.start();event.accept()
    def action_rect(self,rect):return QRect(rect.right()-52,rect.top()+16,48,48)
    def mousePressEvent(self,event):
        index=self.indexAt(event.position().toPoint());self._pressed_action=None
        if event.button()==Qt.MouseButton.LeftButton and index.isValid() and self.action_rect(self.visualRect(index)).contains(event.position().toPoint()):self._pressed_action=index.data(ROLE);event.accept();return
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        if self._pressed_action is not None:
            row=self._pressed_action;self._pressed_action=None
            if event.button()==Qt.MouseButton.LeftButton and index.isValid() and index.data(ROLE)['id']==row['id'] and self.action_rect(self.visualRect(index)).contains(event.position().toPoint()):self.actionRequested.emit(row)
            event.accept();return
        super().mouseReleaseEvent(event)
    def keyPressEvent(self,event):
        if self.currentIndex().isValid() and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space):self.actionRequested.emit(self.currentIndex().data(ROLE));event.accept();return
        super().keyPressEvent(event)

class SongDelegate(QStyledItemDelegate):
    def __init__(self,view,artwork):super().__init__(view);self.view=view;self.artwork=artwork;self.theme=Theme.from_mode('system')
    def sizeHint(self,option,index):return QSize(320,80)
    def paint(self,painter,option,index):
        r=index.data(ROLE)
        if not r:return
        t=self.theme;rect=option.rect;p=painter;p.save();p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        selected=bool(option.state&QStyle.StateFlag.State_Selected);hover=bool(option.state&QStyle.StateFlag.State_MouseOver)
        if selected or hover:p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(t.container if selected else t.low));p.drawRoundedRect(rect.adjusted(0,1,-1,-1),16,16)
        box=QRect(rect.left()+8,rect.top()+12,56,56);image=self.artwork.get(r);path=QPainterPath();path.addRoundedRect(QRectF(box),12,12);p.save();p.setClipPath(path);p.fillRect(box,QColor(t.container))
        if not image.isNull():p.drawImage(box,image,QRect((image.width()-min(image.size().width(),image.size().height()))//2,(image.height()-min(image.size().width(),image.size().height()))//2,min(image.width(),image.height()),min(image.width(),image.height())))
        else:icon('note',t.muted).paint(p,QRect(box.x()+16,box.y()+16,24,24))
        p.restore();x=box.right()+16;width=rect.right()-x-66;title=QFont('Segoe UI');title.setPixelSize(16);title.setWeight(QFont.Weight.DemiBold);p.setFont(title);p.setPen(QColor(t.text));p.drawText(QRect(x,rect.top()+14,width,23),Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(r.get('title') or '',Qt.TextElideMode.ElideRight,width));font=QFont('Segoe UI');font.setPixelSize(13);p.setFont(font);p.setPen(QColor(t.muted));p.drawText(QRect(x,rect.top()+39,width,20),Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(r.get('artist') or '',Qt.TextElideMode.ElideRight,width))
        archived=not r['liked'];state=r['status'];note=('На компьютере' if state=='downloaded' else 'Не скачано') if archived else {'failed':'Не скачалось','unavailable':'Недоступен','pending':'В очереди'}.get(state,'')
        if note:
            # Move both main lines up to give the status its own baseline.
            p.fillRect(QRect(x,rect.top()+12,width,58),QColor(t.container if selected else t.low if hover else t.surface));p.setFont(title);p.setPen(QColor(t.text));p.drawText(QRect(x,rect.top()+8,width,22),Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(r.get('title') or '',Qt.TextElideMode.ElideRight,width));p.setFont(font);p.setPen(QColor(t.muted));p.drawText(QRect(x,rect.top()+32,width,18),Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(r.get('artist') or '',Qt.TextElideMode.ElideRight,width));small=QFont(font);small.setPixelSize(11);p.setFont(small);p.setPen(QColor(t.error if state=='failed' and not archived else t.muted));p.drawText(QRect(x,rect.top()+54,width,17),Qt.AlignmentFlag.AlignVCenter,note)
        name='close' if archived else 'play' if state=='downloaded' else 'sync' if state=='failed' else 'download';icon(name,t.muted).paint(p,self.view.action_rect(rect).adjusted(12,12,-12,-12));p.restore()

class SwipeCard(QFrame):
    dismissed=Signal()
    def __init__(self,parent=None):super().__init__(parent);self.setObjectName('card');self.dismissible=False;self.start=None
    def mousePressEvent(self,event):
        if self.dismissible and event.button()==Qt.MouseButton.LeftButton:self.start=event.position().toPoint();event.accept()
        else:super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        if self.start is not None:
            delta=event.position().toPoint()-self.start;self.start=None
            if isinstance(self.graphicsEffect(),QGraphicsOpacityEffect):self.graphicsEffect().setOpacity(1.)
            if abs(delta.x())>min(120,self.width()*.3) and abs(delta.x())>abs(delta.y()):self.dismissed.emit()
            event.accept()
        else:super().mouseReleaseEvent(event)
    def mouseMoveEvent(self,event):
        if self.start is not None:
            effect=self.graphicsEffect()
            if not isinstance(effect,QGraphicsOpacityEffect):effect=QGraphicsOpacityEffect(self);self.setGraphicsEffect(effect)
            effect.setOpacity(max(.4,1-abs(event.position().x()-self.start.x())/max(1,self.width())*1.8));event.accept()
        else:super().mouseMoveEvent(event)

def fade(widget,duration=150):
    old=getattr(widget,'_fade',None)
    if old:old.stop();old.deleteLater()
    parent=widget.parentWidget()
    while parent is not None:
        if isinstance(parent.graphicsEffect(),QGraphicsOpacityEffect):return
        parent=parent.parentWidget()
    # Qt can render nested effects as an empty surface; keep one transition per branch.
    for child in widget.findChildren(QWidget):
        child_animation=getattr(child,'_fade',None)
        if child_animation:child_animation.stop();child_animation.deleteLater();child._fade=None;child.setGraphicsEffect(None)
    effect=widget.graphicsEffect()
    if not isinstance(effect,QGraphicsOpacityEffect):effect=QGraphicsOpacityEffect(widget);widget.setGraphicsEffect(effect)
    animation=QPropertyAnimation(effect,b'opacity',widget);animation.setDuration(duration);animation.setStartValue(.3);animation.setEndValue(1.);animation.setEasingCurve(QEasingCurve.Type.OutCubic);widget._fade=animation
    def finished():
        if getattr(widget,'_fade',None)==animation:widget._fade=None;widget.setGraphicsEffect(None)
        animation.deleteLater()
    animation.finished.connect(finished);animation.start()
