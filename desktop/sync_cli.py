"""Optional foreground CLI: sync, status, folder, and interactive token login."""
import argparse
import getpass
import json
import threading
import signal
import auth
import settings
import music_export as m


def main():
    parser=argparse.ArgumentParser(description='Избранное Яндекс Музыки: локальная синхронизация')
    parser.add_argument('command',choices=('sync','status','folder','token','login','poll'))
    parser.add_argument('path',nargs='?');args=parser.parse_args()
    m.initialize()
    if args.command=='sync':
        signal.signal(signal.SIGINT,lambda *_:m.STOP.touch())
        with m.worker_lock():m.run()
    elif args.command=='folder':
        if not args.path:print(settings.destination())
        else:print('Перенесено:',settings.relocate(args.path))
    elif args.command=='token':
        auth.save_token(getpass.getpass('Токен (ввод скрыт): '));print('Вход сохранён.')
    elif args.command=='login':
        result=auth.request_code();print('Открой',result['verification_url'],'и введи код',result['user_code'])
    elif args.command=='poll':print(auth.poll()['state'])
    else:
        with m.db() as c:groups=[dict(r) for r in c.execute('SELECT status,COUNT(*) AS count FROM tracks GROUP BY status')]
        print(json.dumps({'destination':str(settings.destination()),'tracks':groups},ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:print(m.safe_error(exc));raise SystemExit(1)
