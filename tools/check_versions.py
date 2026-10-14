"""Keep Windows, Android and release tags on the same version."""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(desktop: str, android: str, tag: str | None = None) -> str:
    assignments = [node for node in ast.parse(desktop).body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'VERSION'
                           for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError('Windows must declare one VERSION constant.')
    version = ast.literal_eval(assignments[0].value)
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a major.minor.patch version for Windows.')
    names = re.findall(r"^\s*versionName\s+['\"]([^'\"]+)['\"]", android, re.MULTILINE)
    codes = re.findall(r'^\s*versionCode\s+(\d+)\s*$', android, re.MULTILINE)
    if names != [version]:
        raise ValueError('Windows VERSION and Android versionName must match.')
    if len(codes) != 1 or int(codes[0]) <= 0:
        raise ValueError('Android must declare one positive versionCode.')
    if tag is not None and tag != 'v' + version:
        raise ValueError('Release tag must be v' + version + '.')
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', help='Also validate a proposed release tag.')
    args = parser.parse_args()
    try:
        version = check((ROOT / 'desktop/app.py').read_text(encoding='utf-8'),
                        (ROOT / 'android/android-app/build.gradle').read_text(encoding='utf-8'),
                        args.tag)
    except (OSError, ValueError, SyntaxError) as exc:
        print('Version check failed:', exc)
        return 1
    print('Windows and Android:', version)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
