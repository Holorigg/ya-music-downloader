"""Visible library and reversible archive operations; never delete music files."""
import music_export as m

def snapshot():
    with m.db() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM tracks WHERE liked=1 OR archive_hidden=0 ORDER BY liked DESC,position')]
        meta=dict(c.execute('SELECT key,value FROM meta'))
        meta['downloaded_total']=str(c.execute("SELECT COUNT(*) FROM tracks WHERE status='downloaded'").fetchone()[0])
    return rows,meta

def hide_archive(ids=None):
    with m.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if ids is None:ids=[r[0] for r in c.execute('SELECT id FROM tracks WHERE liked=0 AND archive_hidden=0')]
        changed=[]
        for ident in ids:
            if c.execute('UPDATE tracks SET archive_hidden=1 WHERE id=? AND liked=0 AND archive_hidden=0',(ident,)).rowcount:changed.append(ident)
    return changed

def restore_archive(ids):
    with m.db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.executemany('UPDATE tracks SET archive_hidden=0 WHERE id=? AND liked=0',[(ident,) for ident in ids])

def filtered(rows,scope,query=''):
    query=query.strip().casefold()
    return [r for r in rows if (not bool(r['liked']))==(scope=='archive')
            and (scope!='downloaded' or r['status']=='downloaded')
            and (scope!='missing' or r['status']!='downloaded')
            and query in ' '.join(str(r.get(k) or '') for k in ('title','artist','album')).casefold()]

def tracks(count):
    suffix='трек' if count%10==1 and count%100!=11 else 'трека' if 2<=count%10<=4 and not 12<=count%100<=14 else 'треков'
    return f'{count} {suffix}'
