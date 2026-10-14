"""Run the sync worker with persistent local logs."""
import os
import sys
from pathlib import Path

from runtime_paths import ROOT,DATA


def main():
    os.chdir(ROOT)
    with (DATA/'music.log').open('a',encoding='utf-8',buffering=1) as log:
        sys.stdout=log;sys.stderr=log
        import music_export as m
        m.initialize()
        try:
            with m.worker_lock():
                try:m.run(reset_stop='--gui' not in sys.argv)
                except Exception as exc:m.status(m.safe_error(exc),'needs_login' if isinstance(exc,m.AuthRequired) else 'failed');return 2
        except RuntimeError:return 3
    return 0


if __name__=='__main__':raise SystemExit(main())
