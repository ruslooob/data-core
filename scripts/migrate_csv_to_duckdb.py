# -*- coding: utf-8 -*-
"""Одноразовая миграция CSV-файлов из data/db/ в единую DuckDB-базу data/db/data-core.duckdb.

Что делает:
    1. Бэкапит data/db/*.csv в data/db/backup_<timestamp>/.
    2. Создаёт data/db/data-core.duckdb со схемой:
         - events       (PK id)
         - tags         (PK code)
         - event_tags   (PK (event_id, tag_code), FK на events и tags)
         - precedent_queries (PK id, UNIQUE name)
         - tagged_events VIEW поверх трёх таблиц
    3. Заливает данные через COPY ... FROM '<csv>' (FORMAT CSV, HEADER).
    4. Удаляет битые связи event_tags, у которых event_id отсутствует в events
       (выводит количество и id-шники в лог).
    5. Проверяет совпадение количества строк CSV ↔ DuckDB.
    6. После успеха — переносит CSV в data/db/archive_csv/.

Идемпотентен только в смысле «не запускать дважды»: если data-core.duckdb уже
существует — скрипт падает с ошибкой и не трогает данные. Чтобы перезапустить
миграцию — удалить data-core.duckdb вручную (бэкап CSV всегда остаётся).

Запуск: python scripts/migrate_csv_to_duckdb.py
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb

# Windows-консоль может быть в cp1251 — заворачиваем stdout/stderr в utf-8.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / 'data' / 'db'
DB_FILE = DB_DIR / 'data-core.duckdb'

EVENTS_CSV = DB_DIR / 'events.csv'
TAGS_CSV = DB_DIR / 'tags.csv'
EVENT_TAGS_CSV = DB_DIR / 'event_tags.csv'
PRECEDENT_QUERIES_CSV = DB_DIR / 'precedent_queries.csv'

CSV_FILES = [EVENTS_CSV, TAGS_CSV, EVENT_TAGS_CSV, PRECEDENT_QUERIES_CSV]


def _csv_row_count(path: Path) -> int:
    """Количество CSV-записей (без заголовка). Учитывает переносы внутри ячеек.
    Возвращает 0 если файла нет."""
    if not path.exists():
        return 0
    import csv
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        next(reader, None)  # пропустить заголовок
        return sum(1 for _ in reader)


def _backup_csvs() -> Path:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = DB_DIR / f'backup_{timestamp}'
    backup_dir.mkdir(parents=True, exist_ok=False)
    for csv in CSV_FILES:
        if csv.exists():
            shutil.copy2(csv, backup_dir / csv.name)
    return backup_dir


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE events (
            id         VARCHAR PRIMARY KEY,
            date_start DATE NOT NULL,
            date_end   DATE,
            event      TEXT
        )
    """)
    con.execute("""
        CREATE TABLE tags (
            code VARCHAR PRIMARY KEY,
            name VARCHAR,
            type VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE event_tags (
            event_id VARCHAR NOT NULL REFERENCES events(id),
            tag_code VARCHAR NOT NULL REFERENCES tags(code),
            PRIMARY KEY (event_id, tag_code)
        )
    """)
    con.execute("""
        CREATE TABLE precedent_queries (
            id         VARCHAR PRIMARY KEY,
            name       VARCHAR NOT NULL UNIQUE,
            source     TEXT    NOT NULL,
            created_at VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE VIEW tagged_events AS
        SELECT
            e.id         AS event_id,
            e.date_start,
            e.date_end,
            e.event,
            t.code       AS tag,
            t.name       AS tag_name,
            t.type       AS tag_type
        FROM events     e
        JOIN event_tags et ON et.event_id = e.id
        JOIN tags       t  ON t.code      = et.tag_code
    """)


def _load_csvs(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Заливает данные из CSV; возвращает список id-шников отброшенных битых связей."""
    con.execute(f"COPY tags FROM '{TAGS_CSV.as_posix()}' (FORMAT CSV, HEADER)")
    con.execute(f"COPY events FROM '{EVENTS_CSV.as_posix()}' (FORMAT CSV, HEADER)")

    # event_tags: грузим во временную таблицу, отсеиваем сирот, переносим в основную.
    con.execute("""
        CREATE TEMP TABLE _event_tags_raw (
            event_id VARCHAR,
            tag_code VARCHAR
        )
    """)
    con.execute(f"COPY _event_tags_raw FROM '{EVENT_TAGS_CSV.as_posix()}' (FORMAT CSV, HEADER)")

    orphan_ids = [
        r[0] for r in con.execute("""
            SELECT DISTINCT event_id FROM _event_tags_raw
            WHERE event_id NOT IN (SELECT id FROM events)
        """).fetchall()
    ]
    con.execute("""
        INSERT INTO event_tags (event_id, tag_code)
        SELECT event_id, tag_code FROM _event_tags_raw
        WHERE event_id IN (SELECT id FROM events)
    """)
    con.execute("DROP TABLE _event_tags_raw")

    if PRECEDENT_QUERIES_CSV.exists() and _csv_row_count(PRECEDENT_QUERIES_CSV) > 0:
        con.execute(
            f"COPY precedent_queries FROM '{PRECEDENT_QUERIES_CSV.as_posix()}' "
            "(FORMAT CSV, HEADER)"
        )

    return orphan_ids


def _verify_counts(con: duckdb.DuckDBPyConnection, orphan_count: int) -> None:
    expected = {
        'events': _csv_row_count(EVENTS_CSV),
        'tags': _csv_row_count(TAGS_CSV),
        'event_tags': _csv_row_count(EVENT_TAGS_CSV) - orphan_count,
        'precedent_queries': _csv_row_count(PRECEDENT_QUERIES_CSV),
    }
    actual = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in expected
    }
    print()
    print('Сверка количества строк (CSV → DuckDB):')
    all_ok = True
    for table, exp_n in expected.items():
        act_n = actual[table]
        mark = 'OK' if act_n == exp_n else 'FAIL'
        if act_n != exp_n:
            all_ok = False
        print(f'  {table:20s} {exp_n:6d} → {act_n:6d}  [{mark}]')
    if not all_ok:
        raise RuntimeError('Количество строк после миграции не совпадает с CSV — миграция отменена')


def _archive_csvs() -> Path:
    archive_dir = DB_DIR / 'archive_csv'
    archive_dir.mkdir(exist_ok=True)
    for csv in CSV_FILES:
        if csv.exists():
            shutil.move(str(csv), str(archive_dir / csv.name))
    return archive_dir


def main() -> int:
    if DB_FILE.exists():
        print(f'Ошибка: {DB_FILE} уже существует. Удалите файл вручную для повторной миграции.')
        return 1

    if not EVENTS_CSV.exists() or not TAGS_CSV.exists() or not EVENT_TAGS_CSV.exists():
        print('Ошибка: не найдены ключевые CSV-файлы в data/db/. Миграция невозможна.')
        return 1

    print(f'Миграция CSV → {DB_FILE.name}')
    print()

    backup_dir = _backup_csvs()
    print(f'Бэкап CSV: {backup_dir.relative_to(ROOT).as_posix()}')

    con = duckdb.connect(str(DB_FILE))
    try:
        _create_schema(con)
        orphans = _load_csvs(con)
        if orphans:
            print()
            print(f'Удалено битых связей event_tags: {len(orphans)}')
            print('event_id с отсутствующим событием (бэкап CSV сохранён):')
            for oid in sorted(orphans):
                print(f'  {oid}')
        _verify_counts(con, orphan_count=len(orphans))
    except Exception:
        con.close()
        DB_FILE.unlink(missing_ok=True)
        raise
    con.close()

    archive_dir = _archive_csvs()
    print()
    print(f'CSV перенесены в архив: {archive_dir.relative_to(ROOT).as_posix()}')
    print()
    print(f'Готово: {DB_FILE.relative_to(ROOT).as_posix()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
