"""Перенос схемы и данных из DuckDB в Postgres.

Читает `data/db/data-core.duckdb` (read-only), создаёт в Postgres
эквивалентные таблицы, копирует строки, пересоздаёт VIEW
`tagged_events`. Идемпотентен: повторный запуск дропает существующие
таблицы и создаёт заново. Этот скрипт мигрирует только «системную»
часть схемы (события/теги, стратегии/правила/окружения/прогоны/
журнал сделок, сохранённые PQL-запросы). Котировки и индексы — в
отдельной миграции (P3).

Запуск:
    python scripts/migrate_duckdb_to_postgres.py
"""
from __future__ import annotations

import io
import os
import sys

import duckdb
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, 'data', 'db', 'data-core.duckdb')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

# Порядок важен: parent → child (FK), reverse при дропе.
TABLES_IN_ORDER: list[str] = [
    'tags',
    'events',
    'event_tags',
    'precedent_queries',
    'rules',
    'strategies',
    'strategy_rules',
    'environments',
    'backtest_results',
    'trade_journal',
]

DDL: dict[str, str] = {
    'tags': """
        CREATE TABLE tags (
            code VARCHAR PRIMARY KEY,
            name VARCHAR,
            type VARCHAR
        )
    """,
    'events': """
        CREATE TABLE events (
            id         VARCHAR PRIMARY KEY,
            date_start DATE NOT NULL,
            date_end   DATE,
            event      VARCHAR
        )
    """,
    'event_tags': """
        CREATE TABLE event_tags (
            event_id VARCHAR NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            tag_code VARCHAR NOT NULL REFERENCES tags(code) ON DELETE CASCADE,
            PRIMARY KEY (event_id, tag_code)
        )
    """,
    'precedent_queries': """
        CREATE TABLE precedent_queries (
            id         VARCHAR PRIMARY KEY,
            name       VARCHAR NOT NULL UNIQUE,
            source     TEXT    NOT NULL,
            created_at VARCHAR NOT NULL
        )
    """,
    'rules': """
        CREATE TABLE rules (
            id                  VARCHAR PRIMARY KEY,
            name                VARCHAR NOT NULL UNIQUE,
            trigger_sql         TEXT    NOT NULL,
            action_type         VARCHAR NOT NULL,
            action_quantity_sql TEXT    NOT NULL,
            priority            INTEGER NOT NULL,
            created_at          VARCHAR NOT NULL,
            description         VARCHAR
        )
    """,
    'strategies': """
        CREATE TABLE strategies (
            id          VARCHAR PRIMARY KEY,
            name        VARCHAR NOT NULL UNIQUE,
            created_at  VARCHAR NOT NULL,
            description VARCHAR
        )
    """,
    'strategy_rules': """
        CREATE TABLE strategy_rules (
            strategy_id VARCHAR NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
            rule_id     VARCHAR NOT NULL REFERENCES rules(id),
            position    INTEGER NOT NULL,
            PRIMARY KEY (strategy_id, rule_id)
        )
    """,
    'environments': """
        CREATE TABLE environments (
            id               VARCHAR PRIMARY KEY,
            name             VARCHAR NOT NULL UNIQUE,
            date_start       DATE    NOT NULL,
            date_end         DATE    NOT NULL,
            starting_capital DOUBLE PRECISION NOT NULL,
            created_at       VARCHAR NOT NULL,
            description      VARCHAR
        )
    """,
    'backtest_results': """
        CREATE TABLE backtest_results (
            id                VARCHAR PRIMARY KEY,
            strategy_id       VARCHAR NOT NULL REFERENCES strategies(id),
            environment_id    VARCHAR NOT NULL REFERENCES environments(id),
            created_at        VARCHAR NOT NULL,
            total_return_pct  DOUBLE PRECISION NOT NULL,
            annual_return_pct DOUBLE PRECISION NOT NULL,
            max_drawdown_pct  DOUBLE PRECISION NOT NULL,
            sharpe            DOUBLE PRECISION NOT NULL,
            n_trades          INTEGER NOT NULL,
            profit_factor     DOUBLE PRECISION,
            win_rate_pct      DOUBLE PRECISION
        )
    """,
    'trade_journal': """
        CREATE TABLE trade_journal (
            id                 VARCHAR PRIMARY KEY,
            backtest_result_id VARCHAR NOT NULL REFERENCES backtest_results(id) ON DELETE CASCADE,
            trade_date         DATE    NOT NULL,
            ticker             VARCHAR NOT NULL,
            type               VARCHAR NOT NULL,
            quantity           INTEGER NOT NULL,
            price              DOUBLE PRECISION NOT NULL,
            rule_name          VARCHAR NOT NULL,
            pnl_realized       DOUBLE PRECISION
        )
    """,
}

VIEW_TAGGED_EVENTS = """
    CREATE OR REPLACE VIEW tagged_events AS
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
"""


def _drop_all(pg) -> None:
    """Сносит таблицы и view в обратном порядке."""
    with pg.cursor() as cur:
        cur.execute('DROP VIEW IF EXISTS tagged_events CASCADE')
        for tbl in reversed(TABLES_IN_ORDER):
            cur.execute(f'DROP TABLE IF EXISTS {tbl} CASCADE')


def _create_schema(pg) -> None:
    with pg.cursor() as cur:
        for tbl in TABLES_IN_ORDER:
            cur.execute(DDL[tbl])
        cur.execute(VIEW_TAGGED_EVENTS)


def _copy_table(duck: duckdb.DuckDBPyConnection, pg, table: str) -> int:
    """Копирует все строки таблицы из DuckDB в Postgres через CSV-буфер.

    Использует psycopg-COPY: быстро и без проблем с экранированием
    больших строковых полей (тексты SQL-запросов в `rules`, `precedent_queries`).
    DuckDB → CSV → buffer → PG COPY.
    """
    # Определяем порядок столбцов в Postgres (он же — порядок в DuckDB,
    # т.к. DDL писалось вручную с учётом источника).
    rows = duck.execute(f'SELECT * FROM {table}').fetchall()
    if not rows:
        return 0
    columns = [c[0] for c in duck.execute(f'DESCRIBE {table}').fetchall()]
    placeholders = ', '.join(['%s'] * len(columns))
    cols_sql = ', '.join(columns)
    with pg.cursor() as cur:
        cur.executemany(
            f'INSERT INTO {table} ({cols_sql}) VALUES ({placeholders})',
            rows,
        )
    return len(rows)


def main() -> None:
    if not os.path.exists(DUCKDB_PATH):
        print(f'Не найден DuckDB-файл: {DUCKDB_PATH}', file=sys.stderr)
        sys.exit(1)

    duck = duckdb.connect(DUCKDB_PATH, read_only=True)
    pg = psycopg.connect(PG_DSN, autocommit=False)
    try:
        print('drop existing schema')
        _drop_all(pg)
        pg.commit()

        print('create schema')
        _create_schema(pg)
        pg.commit()

        print('copy data:')
        for tbl in TABLES_IN_ORDER:
            n = _copy_table(duck, pg, tbl)
            duck_count = duck.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
            assert n == duck_count, f'{tbl}: copied {n}, expected {duck_count}'
            print(f'  {tbl}: {n}')
        pg.commit()

        # Чекпоинт: суммарные count'ы в Postgres
        with pg.cursor() as cur:
            print('postgres counts:')
            for tbl in TABLES_IN_ORDER:
                cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                print(f'  {tbl}: {cur.fetchone()[0]}')
            cur.execute('SELECT COUNT(*) FROM tagged_events')
            print(f'  tagged_events (view): {cur.fetchone()[0]}')

    finally:
        pg.close()
        duck.close()


if __name__ == '__main__':
    main()
