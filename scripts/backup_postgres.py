"""Снимает дамп Postgres из docker-контейнера в `data/db/backup_<ts>/full.dump`.

После успешного дампа удаляет папки `backup_*`, которые старше
RETENTION_DAYS (по timestamp в имени, не по mtime).

Запуск:
    python scripts/backup_postgres.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

CONTAINER = 'data-core-postgres'
DB_USER = 'postgres'
DB_NAME = 'postgres'
RETENTION_DAYS = 7
DUMP_FILENAME = 'full.dump'

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_ROOT = REPO_ROOT / 'data' / 'db'

_DIR_NAME_RE = re.compile(r'^backup_(\d{8}_\d{6})$')
_TS_FORMAT = '%Y%m%d_%H%M%S'


class CommandError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    """Запускает команду, прокидывая stdout/stderr; кидает CommandError на ненулевом коде."""
    print('$ ' + ' '.join(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise CommandError(f'command failed with code {result.returncode}: {cmd[0]}')


def _create_dump(target_dir: Path) -> None:
    tmp_path_in_container = f'/tmp/{DUMP_FILENAME}'
    # Сначала дамп внутри контейнера — если упадёт, локальная папка не создаётся.
    _run([
        'docker', 'exec', CONTAINER,
        'pg_dump', '-U', DB_USER, '-d', DB_NAME,
        '--format=custom', f'--file={tmp_path_in_container}',
    ])
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        _run([
            'docker', 'cp',
            f'{CONTAINER}:{tmp_path_in_container}',
            str(target_dir / DUMP_FILENAME),
        ])
    except CommandError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    finally:
        # rm в контейнере — best-effort, не валим бэкап если /tmp не чистится.
        subprocess.run(['docker', 'exec', CONTAINER, 'rm', '-f', tmp_path_in_container])


def _rotate(now: datetime) -> None:
    """Удаляет папки backup_<ts>, чей ts старше now - RETENTION_DAYS."""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    for entry in BACKUP_ROOT.iterdir():
        if not entry.is_dir():
            continue
        match = _DIR_NAME_RE.match(entry.name)
        if not match:
            continue
        try:
            ts = datetime.strptime(match.group(1), _TS_FORMAT)
        except ValueError:
            continue
        if ts < cutoff:
            print(f'removing old backup: {entry.name}', flush=True)
            shutil.rmtree(entry)


def main() -> None:
    now = datetime.now()
    target = BACKUP_ROOT / f'backup_{now.strftime(_TS_FORMAT)}'
    print(f'creating backup at {target}', flush=True)
    _create_dump(target)
    _rotate(now)
    print('done', flush=True)


if __name__ == '__main__':
    main()
