"""Build the portable Windows GUI in onedir and/or onefile form."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from check_versions import check

REPO_ROOT=Path(__file__).resolve().parent.parent
DESKTOP=REPO_ROOT/'desktop'
TOOLS=DESKTOP/'tools'
LICENSES=DESKTOP/'packaging'/'licenses'
BUILD=DESKTOP/'build'/'pyinstaller'
DIST=DESKTOP/'dist'
PYINSTALLER_VERSION='6.22.3'
EXCLUDED_MODULES=(
    'demo_data','render_demo','sync_cli','run_checks','test_media','verify_app','verify_covers',
    'verify_desktop','verify_existing','verify_export','verify_ui','verify_packaging',
)


def version_string():
    return check((DESKTOP/'app.py').read_text(encoding='utf-8'),
                 (REPO_ROOT/'android'/'android-app'/'build.gradle').read_text(encoding='utf-8'))


def version_resource(version: str) -> str:
    parts=tuple(int(part) for part in version.split('.'))+(0,)
    numeric=', '.join(str(part) for part in parts)
    return f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numeric}), prodvers=({numeric}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', 'Ya Music Downloader'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'MyMusic'),
        StringStruct('OriginalFilename', 'MyMusic.exe'),
        StringStruct('ProductName', 'Ya Music Downloader'),
        StringStruct('ProductVersion', '{version}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)\n'''


def ensure_inputs():
    if sys.platform!='win32':raise RuntimeError('Windows bundles must be built on Windows.')
    if sys.version_info[:2]!=(3,12):raise RuntimeError('Build with Python 3.12.')
    if struct.calcsize('P')!=8:raise RuntimeError('Build with 64-bit Python.')
    if not (DESKTOP/'music.ico').is_file():raise RuntimeError('desktop/music.ico is missing.')
    if not (DESKTOP/'assets').is_dir() or not any((DESKTOP/'assets').glob('ic_*.svg')):
        raise RuntimeError('The desktop SVG icon assets are missing.')
    for name in ('ffmpeg.exe','ffprobe.exe'):
        if not (TOOLS/name).is_file():raise RuntimeError(f'desktop/tools/{name} is required.')
    libraries=sorted(TOOLS.rglob('*.dll'))
    if not libraries:raise RuntimeError('The shared FFmpeg bundle DLLs are required under desktop/tools.')
    names=[path.name.casefold() for path in libraries]
    if len(names)!=len(set(names)):
        raise RuntimeError('FFmpeg DLL basenames must be unique when collected into the tools directory.')
    if not LICENSES.is_dir() or not any(path.is_file() for path in LICENSES.rglob('*')):
        raise RuntimeError('desktop/packaging/licenses must contain release notices and license files.')
    try:
        from PyInstaller import __version__
    except ImportError as exc:
        raise RuntimeError('Install desktop/build-requirements.txt in the build environment.') from exc
    if __version__!=PYINSTALLER_VERSION:
        raise RuntimeError(f'PyInstaller {PYINSTALLER_VERSION} is required; found {__version__}.')
    return version_string()


def remove_output(path: Path, parent: Path):
    resolved=path.resolve();base=parent.resolve()
    if not resolved.is_relative_to(base):raise RuntimeError('Refusing to remove output outside desktop/dist.')
    if resolved.is_dir():shutil.rmtree(resolved)
    elif resolved.exists():resolved.unlink()


def build(mode: str, version: str):
    output_dir=DIST/mode
    product_dir=output_dir/'MyMusic'
    target=product_dir if mode=='onedir' else output_dir/'MyMusic.exe'
    remove_output(target,DIST)
    output_dir.mkdir(parents=True,exist_ok=True)
    mode_build=BUILD/mode
    mode_build.mkdir(parents=True,exist_ok=True)
    version_file=mode_build/'version_info.txt'
    version_file.write_text(version_resource(version),encoding='utf-8')

    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed',
             '--name','MyMusic','--icon',str(DESKTOP/'music.ico'),
             '--distpath',str(output_dir),'--workpath',str(mode_build/'work'),
             '--specpath',str(mode_build),'--version-file',str(version_file)]
    command.append('--onedir' if mode=='onedir' else '--onefile')
    if mode=='onedir':command.extend(['--contents-directory','_internal'])
    command.extend(['--add-data',f"{DESKTOP/'assets'};assets",
                    '--add-data',f"{DESKTOP/'music.ico'};.",
                    '--add-data',f"{LICENSES};licenses"])
    for path in (TOOLS/'ffmpeg.exe',TOOLS/'ffprobe.exe',*sorted(TOOLS.rglob('*.dll'))):
        command.extend(['--add-binary',f'{path};tools'])
    for name in EXCLUDED_MODULES:command.extend(['--exclude-module',name])
    command.append(str(DESKTOP/'entrypoint.py'))
    subprocess.run(command,cwd=DESKTOP,check=True)
    if not target.is_file() and not target.is_dir():raise RuntimeError(f'PyInstaller did not produce {target}.')
    print(f'Built {mode} {version}: {target}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('onedir','onefile','both'),default='both')
    args=parser.parse_args()
    version=ensure_inputs()
    modes=('onedir','onefile') if args.mode=='both' else (args.mode,)
    for mode in modes:build(mode,version)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('Windows bundle build failed:',type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
