"""Generate original test audio and a tiny cover; never read a user's library."""
from pathlib import Path
import base64
from mutagen.id3 import ID3,TIT2,TPE1,TALB,APIC
from runtime_paths import media_tool
import music_export as m

# One authored 1x1 PNG, used only as test metadata, not as an album cover.
COVER=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')

def create_mp3(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    m.command([media_tool('ffmpeg'),'-v','error','-nostdin','-y','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','libmp3lame','-b:a','128k',str(path)])
    tags=ID3(path);tags.add(TIT2(encoding=3,text=['Test track']));tags.add(TPE1(encoding=3,text=['Test artist']));tags.add(TALB(encoding=3,text=['Test album']));tags.add(APIC(encoding=3,mime='image/png',type=3,desc='Test cover',data=COVER));tags.save(path,v2_version=3)
    return path
