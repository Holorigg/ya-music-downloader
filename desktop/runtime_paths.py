"""Separate installable source assets from per-user Windows runtime data."""
from pathlib import Path
import os,shutil

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('MUSIC_DATA_DIR') or str(Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'YaMusicDownloader')).expanduser().resolve()
DATA.mkdir(parents=True,exist_ok=True)

def media_tool(name):
    configured=os.environ.get('MUSIC_FFMPEG_DIR')
    for directory in ([Path(configured)] if configured else [])+[ROOT/'tools']:
        path=directory/(name+'.exe')
        if path.is_file():return str(path.resolve())
    found=shutil.which(name)
    if found:return found
    raise RuntimeError('Установи FFmpeg и FFprobe в PATH или укажи MUSIC_FFMPEG_DIR. См. desktop/README.md.')
