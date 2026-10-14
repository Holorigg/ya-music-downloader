"""Install a checksum-pinned FFmpeg build for offline Windows CI checks."""
from pathlib import Path
import hashlib
import os
import tempfile
import time
from urllib.request import urlopen
import zipfile

URL = ('https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/'
       'ffmpeg-9.0.2-essentials_build.zip')
SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'


def main(target=None):
    target = Path(target) if target is not None else Path(__file__).resolve().parent.parent / 'desktop/tools'
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='music-ci-ffmpeg-') as directory:
        archive = Path(directory) / 'ffmpeg.zip'
        for attempt in range(3):
            try:
                with urlopen(URL, timeout=45) as response, archive.open('wb') as output:
                    while chunk := response.read(1024*1024):
                        output.write(chunk)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != SHA256:
                raise RuntimeError('FFmpeg download checksum mismatch')
        with zipfile.ZipFile(archive) as package:
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                matches = [item for item in package.namelist() if item.endswith('/bin/' + name)]
                if len(matches) != 1:
                    raise RuntimeError('Unexpected FFmpeg archive layout')
                data = package.read(matches[0])
                temporary = target / (name + '.tmp')
                temporary.write_bytes(data)
                os.replace(temporary, target/name)
    print('FFmpeg 9.0.2 and FFprobe installed; archive checksum verified.')


if __name__ == '__main__':
    main()
