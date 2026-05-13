"""Разовая миграция: переименовывает все файлы котировок
`<prefix>_1day_<from>_<till>.txt` → `<prefix>_1day.txt`.

После прогона скрипт удаляется отдельным коммитом. См. docs/SPEC_LOADERS.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DIRS_TO_SCAN = [
    REPO_ROOT / 'data' / 'stocks',
    REPO_ROOT / 'backend' / 'tests' / 'fixtures' / 'stocks',
]


def main() -> None:
    renamed = 0
    skipped = 0
    for base_dir in DIRS_TO_SCAN:
        if not base_dir.exists():
            continue
        for path in base_dir.glob('*_1day_*.txt'):
            stem = path.stem  # без .txt
            prefix = stem.split('_1day_', 1)[0]
            new_name = f'{prefix}_1day.txt'
            new_path = path.with_name(new_name)
            if new_path.exists():
                print(f'  SKIP {path.name}: {new_name} уже существует', file=sys.stderr)
                skipped += 1
                continue
            path.rename(new_path)
            print(f'  {path.name} -> {new_name}')
            renamed += 1
    print()
    print(f'renamed: {renamed}')
    print(f'skipped: {skipped}')
    if skipped:
        sys.exit(1)


if __name__ == '__main__':
    main()
