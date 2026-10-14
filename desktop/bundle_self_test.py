"""Offline checks for a packaged Windows bundle; never uses account data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def main(report_file):
    report_path=Path(report_file).expanduser().resolve()
    result={'format_version':1,'ok':False,'frozen':bool(getattr(sys,'frozen',False)),'checks':[]}
    original={key:os.environ.get(key) for key in ('MUSIC_DATA_DIR','MUSIC_FFMPEG_DIR','QT_QPA_PLATFORM')}
    temporary=None
    failures=[]

    def check(name,action):
        try:
            action()
        except Exception as exc:
            failures.append({'name':name,'error':type(exc).__name__})
            result['checks'].append({'name':name,'ok':False})
        else:
            result['checks'].append({'name':name,'ok':True})

    try:
        profile=original['MUSIC_DATA_DIR']
        if profile:
            data=Path(profile).expanduser().resolve()
            if not data.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise RuntimeError('MUSIC_DATA_DIR for the bundle test must be below the system temporary directory.')
            if data.exists() and any(data.iterdir()):
                raise RuntimeError('The supplied test profile must be empty.')
            data.mkdir(parents=True,exist_ok=True)
        else:
            temporary=tempfile.TemporaryDirectory(prefix='ya-music-bundle-check-')
            data=Path(temporary.name).resolve()/'data'
            data.mkdir()
        os.environ['MUSIC_DATA_DIR']=str(data)
        os.environ.pop('MUSIC_FFMPEG_DIR',None)
        os.environ['QT_QPA_PLATFORM']='offscreen'

        import runtime_paths as paths
        import settings
        import music_export as worker
        import auth
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QIcon
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QApplication

        import app
        result['application_version']=app.VERSION

        def check_runtime():
            if paths.DATA!=data:raise AssertionError
            expected=Path(sys._MEIPASS).resolve() if getattr(sys,'frozen',False) else Path(paths.__file__).resolve().parent
            if paths.ROOT!=expected:raise AssertionError
            if auth.AUTH!=data/'auth_private.json':raise AssertionError
        check('isolated-profile-and-bundle-roots',check_runtime)

        def check_qt_assets():
            qt=QApplication.instance() or QApplication([])
            qt.setQuitOnLastWindowClosed(False)
            if QIcon(str(paths.ROOT/'music.ico')).isNull():raise AssertionError
            assets=paths.ROOT/'assets'
            icons=sorted(assets.glob('ic_*.svg'))
            if not icons:raise AssertionError
            if any(not QSvgRenderer(str(icon)).isValid() for icon in icons):raise AssertionError
        check('qt-runtime-and-ui-assets',check_qt_assets)

        def check_settings_database():
            settings.save({'destination':str(data/'music')})
            if settings.load()['destination']!=str(data/'music'):raise AssertionError
            worker.initialize()
            with worker.db() as connection:
                if connection.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise AssertionError
                tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'meta','tracks'}<=tables:raise AssertionError
        check('settings-and-database',check_settings_database)

        def check_worker_launch():
            if auth.AUTH.exists():raise AssertionError
            program,args=paths.sync_worker_command(gui=True)
            if getattr(sys,'frozen',False):
                if Path(program).resolve()!=Path(sys.executable).resolve() or '--sync-worker' not in args:raise AssertionError
            elif not any(Path(arg).name.casefold()=='run_standalone.py' for arg in args):raise AssertionError
            child_env=os.environ.copy()
            child_env['MUSIC_DATA_DIR']=str(data)
            child_env.pop('MUSIC_FFMPEG_DIR',None)
            child_env['QT_QPA_PLATFORM']='offscreen'
            completed=subprocess.run([program,*args],cwd=paths.ROOT,env=child_env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
            if completed.returncode!=2:raise AssertionError
            if auth.AUTH.exists():raise AssertionError
            status=json.loads(worker.STATUS.read_text(encoding='utf-8'))
            if status.get('state')!='needs_login':raise AssertionError
        check('real-worker-launch-without-network-or-account',check_worker_launch)

        def check_media_tools():
            ffmpeg=Path(paths.media_tool('ffmpeg')).resolve()
            ffprobe=Path(paths.media_tool('ffprobe')).resolve()
            tool_dir=(paths.ROOT/'tools').resolve()
            if ffmpeg.parent!=tool_dir or ffprobe.parent!=tool_dir:raise AssertionError
            licenses=(paths.ROOT/'licenses' if getattr(sys,'frozen',False)
                      else paths.ROOT/'packaging'/'licenses')
            required=('SOURCES.md','LGPL-3.0.txt','GPL-2.0.txt','GPL-3.0.txt',
                      'FFmpeg-LGPL-3.0.txt','Mutagen-COPYING.txt','Python-PSF-2.0.txt',
                      'PyInstaller-COPYING.txt','Requests-LICENSE.txt',
                      'Material-Icons-Apache-2.0.txt')
            if not licenses.is_dir() or any(not (licenses/name).is_file() for name in required):raise AssertionError
            if not (licenses/'sources'/'mutagen-1.47.0.tar.gz').is_file():raise AssertionError
            sample=data/'synthetic.wav'
            with wave.open(str(sample),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(8000)
                output.writeframes(b'\x00\x00'*800)
            probe=subprocess.run([str(ffprobe),'-v','error','-show_format','-show_streams','-of','json',str(sample)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True,text=True,encoding='utf-8')
            metadata=json.loads(probe.stdout)
            if not any(stream.get('codec_type')=='audio' for stream in metadata.get('streams',[])):raise AssertionError
            decode=subprocess.run([str(ffmpeg),'-v','error','-xerror','-nostdin','-i',str(sample),'-map','0:a:0','-f','null','-'],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
            if decode.returncode!=0:raise AssertionError
        check('bundled-ffmpeg-ffprobe-and-license-assets',check_media_tools)
    except Exception as exc:
        failures.append({'name':'self-test-setup','error':type(exc).__name__,'detail':str(exc)[:400]})
    finally:
        for key,value in original.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        if temporary is not None:temporary.cleanup()

    result['ok']=not failures and all(item['ok'] for item in result['checks'])
    if failures:result['failures']=failures
    try:
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except OSError:
        return 1
    return 0 if result['ok'] else 1


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(64)
    raise SystemExit(main(sys.argv[1]))
