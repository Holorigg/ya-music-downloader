"""Windows GUI, sync worker, and isolated bundle diagnostics entry point."""
from __future__ import annotations

import sys


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if args and args[0]=='--sync-worker':
        from run_standalone import main as worker_main
        return worker_main()
    if args and args[0]=='--bundle-self-test':
        if len(args)!=2:return 64
        from bundle_self_test import main as self_test
        return self_test(args[1])
    if args:return 64
    from gui_launcher import main as gui_main
    return gui_main()


if __name__=='__main__':raise SystemExit(main())
