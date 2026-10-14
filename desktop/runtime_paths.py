"""Separate installable source assets from per-user Windows runtime data."""
from pathlib import Path
import os,shutil,sys

def resource_root(*,frozen=None,module_file=None,bundle_dir=None):
    if frozen is None:frozen=bool(getattr(sys,'frozen',False))
    if frozen:
        root=bundle_dir if bundle_dir is not None else getattr(sys,'_MEIPASS',None)
        if root is None:raise RuntimeError('Frozen application resource directory is unavailable.')
        return Path(root).resolve()
    return Path(module_file or __file__).resolve().parent

ROOT=resource_root()
DATA=Path(os.environ.get('MUSIC_DATA_DIR') or str(Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'YaMusicDownloader')).expanduser().resolve()
DATA.mkdir(parents=True,exist_ok=True)

def sync_worker_command(*,gui=False,executable=None,frozen=None,root=None):
    executable=Path(executable or sys.executable)
    if frozen is None:frozen=bool(getattr(sys,'frozen',False))
    if frozen:return str(executable),(['--sync-worker']+(['--gui'] if gui else []))
    python=executable.with_name('python.exe') if executable.name.casefold()=='pythonw.exe' else executable
    script=Path(root or ROOT)/'run_standalone.py'
    return str(python),(['-X','utf8',str(script)]+(['--gui'] if gui else []))

def media_tool(name):
    configured=os.environ.get('MUSIC_FFMPEG_DIR')
    for directory in ([Path(configured)] if configured else [])+[ROOT/'tools']:
        path=directory/(name+'.exe')
        if path.is_file():return str(path.resolve())
    found=shutil.which(name)
    if found:return found
    raise RuntimeError('Установи FFmpeg и FFprobe в PATH или укажи MUSIC_FFMPEG_DIR. См. desktop/README.md.')
