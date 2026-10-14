"""Check credential boundaries, no-overwrite and truncated-response handling."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import music_export as m


class Response:
    status_code=200
    headers={'Content-Length':'12'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield b'abc'


for url in ('http://storage.mds.yandex.net/x','https://yandex.net.evil.example/x','https://example.com/x','https://user:password@storage.mds.yandex.net/x','https://storage.mds.yandex.net:444/x'):
    with patch.object(m.requests,'get') as get:
        try:m.public_get(url);raise AssertionError('Unsafe URL accepted')
        except RuntimeError:pass
        assert not get.called
with patch.object(m.requests,'get',return_value=Response()) as get:
    m.public_get('https://storage.mds.yandex.net/x',stream=True)
    assert not get.call_args.kwargs['allow_redirects']
    assert 'Authorization' not in get.call_args.kwargs['headers']

with tempfile.TemporaryDirectory() as d:
    root=Path(d).resolve()
    with patch.object(m,'DB',root/'state.db'),patch.object(m,'DEST',root/'music'),patch.object(m,'STOP',root/'STOP'):
        m.initialize()
        with m.db() as c:
            c.execute("INSERT INTO meta VALUES ('uid','42')")
            c.execute("INSERT INTO tracks(id,position,title,artist,album,year,duration_ms,available) VALUES ('1',0,'Title','Artist','Album','2026',120000,1)")
            row=dict(c.execute('SELECT * FROM tracks').fetchone())
        with patch.object(m,'api',return_value=[{'codec':'mp3','preview':False,'bitrateInKbps':320}]),patch.object(m,'direct',return_value='https://storage.mds.yandex.net/x'),patch.object(m,'public_get',return_value=Response()),patch.object(m,'validate') as validate:
            try:m.download(row);raise AssertionError('Truncated audio accepted')
            except RuntimeError as exc:assert 'не полностью' in str(exc)
            assert not validate.called
        assert not list((root/'music').rglob('*.part'))
        target=root/'music'/'account_42'/m.name(row);target.write_bytes(b'previous file')
        with patch.object(m,'api') as api:
            try:m.download(row);raise AssertionError('Existing file overwritten')
            except RuntimeError:pass
            assert target.read_bytes()==b'previous file' and not api.called
        with m.db() as c:assert c.execute('SELECT status FROM tracks').fetchone()[0]=='pending'
print('PASS: HTTPS/host restrictions, no credentials on media requests, truncated response refused, existing file preserved')
