"""Run offline regression checks with a fresh per-user data root."""
from pathlib import Path
import os,subprocess,sys,tempfile

root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ya-music-tests-') as directory:
    env={**os.environ,'MUSIC_DATA_DIR':directory,'PYTHONUTF8':'1'}
    for name in ('verify_export.py','verify_app.py','verify_covers.py','verify_existing.py','verify_desktop.py','verify_ui.py'):
        print('Checking '+name,flush=True)
        result=subprocess.run([sys.executable,'-X','utf8',str(root/name)],cwd=root,env=env,timeout=240)
        if result.returncode:raise SystemExit(result.returncode)
print('All offline desktop checks passed')
