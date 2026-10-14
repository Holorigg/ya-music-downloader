"""Double-click entry point with a visible error instead of a vanishing console."""
import ctypes
import os
import sys


def main():
    from runtime_paths import ROOT,DATA
    os.chdir(ROOT)
    with (DATA/'app.log').open('a',encoding='utf-8',buffering=1) as log:
        sys.stdout=log;sys.stderr=log
        try:
            from app import main as app_main
            code=app_main()
        except Exception as exc:
            # Do not include exception messages that could contain signed URLs.
            print('Application startup error:',type(exc).__name__,flush=True)
            ctypes.windll.user32.MessageBoxW(None,'Не удалось открыть приложение: '+type(exc).__name__+'\nЖурнал: '+str(DATA/'app.log'),'Музыка',0x10)
            code=1
    return code


if __name__=='__main__':raise SystemExit(main())
