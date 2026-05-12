"""Удаляет orphan-логи бэктест-прогонов из data/logs/backtest/.

Orphan = файл `<uuid>.log` или `<uuid>.err`, для которого нет строки в
`backtest_results.id`. Логи, связанные с существующими прогонами,
не трогаются.

Запускать вручную — например, после массовых удалений прогонов из UI.
"""
from __future__ import annotations

from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / 'data' / 'logs' / 'backtest'
PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'


def main() -> None:
    if not LOG_DIR.exists():
        print(f'нет директории {LOG_DIR}')
        return

    with psycopg.connect(PG_DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute('SELECT id::text FROM backtest_results')
        db_ids = {row[0] for row in cur.fetchall()}

    files = [p for p in LOG_DIR.iterdir() if p.is_file()]
    # `<uuid>.log` / `<uuid>.err` → берём stem без последнего расширения
    by_stem: dict[str, list[Path]] = {}
    for p in files:
        stem = p.name.rsplit('.', 1)[0]
        by_stem.setdefault(stem, []).append(p)

    orphans = sorted(s for s in by_stem if s not in db_ids)
    linked = sorted(s for s in by_stem if s in db_ids)

    print(f'файлов всего: {len(files)}')
    print(f'связаны с БД: {len(linked)} прогонов')
    print(f'orphan: {len(orphans)} прогонов')

    if not orphans:
        return

    deleted = 0
    for stem in orphans:
        for p in by_stem[stem]:
            p.unlink()
            deleted += 1
            print(f'  удалён {p.name}')
    print(f'итого удалено файлов: {deleted}')


if __name__ == '__main__':
    main()
