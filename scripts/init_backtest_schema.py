# -*- coding: utf-8 -*-
"""Идемпотентная инициализация таблиц бэктеста в data/db/data-core.duckdb.

Создаёт persistent-таблицы для хранения стратегий, правил, окружений и связей:
    - strategies         — сохранённые стратегии
    - rules              — сохранённые правила (переиспользуемые)
    - strategy_rules     — связь M2M «стратегия ↔ правило» с порядком
    - environments       — сохранённые окружения

Таблицы backtest_results и persistent trade_journal появятся отдельным скриптом
вместе с реализацией движка (этап B1+B2 полного плана).

Идемпотентность: использует CREATE TABLE IF NOT EXISTS. Повторный запуск
безопасен, существующие данные не трогаются.

Запуск: python scripts/init_backtest_schema.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import duckdb

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
DB_FILE = ROOT / 'data' / 'db' / 'data-core.duckdb'


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id         VARCHAR PRIMARY KEY,
            name       VARCHAR NOT NULL UNIQUE,
            created_at VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id                  VARCHAR PRIMARY KEY,
            name                VARCHAR NOT NULL UNIQUE,
            trigger_sql         TEXT    NOT NULL,
            action_type         VARCHAR NOT NULL CHECK (action_type IN ('buy', 'sell')),
            action_quantity_sql TEXT    NOT NULL,
            priority            INTEGER NOT NULL,
            created_at          VARCHAR NOT NULL
        )
    """)
    # FK без ON DELETE CASCADE — DuckDB не поддерживает referential actions.
    # Каскад при удалении стратегии реализуется в API: сначала удаляются связки
    # из strategy_rules, потом сама запись из strategies (одной транзакцией).
    con.execute("""
        CREATE TABLE IF NOT EXISTS strategy_rules (
            strategy_id VARCHAR NOT NULL REFERENCES strategies(id),
            rule_id     VARCHAR NOT NULL REFERENCES rules(id),
            position    INTEGER NOT NULL,
            PRIMARY KEY (strategy_id, rule_id),
            UNIQUE (strategy_id, position)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS environments (
            id               VARCHAR PRIMARY KEY,
            name             VARCHAR NOT NULL UNIQUE,
            date_start       DATE    NOT NULL,
            date_end         DATE    NOT NULL,
            starting_capital DOUBLE  NOT NULL,
            created_at       VARCHAR NOT NULL,
            CHECK (date_start <= date_end),
            CHECK (starting_capital > 0)
        )
    """)


def _list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    if not DB_FILE.exists():
        print(f'Ошибка: {DB_FILE} не найден. Сначала запустите миграцию основной схемы.')
        return 1

    print(f'Инициализация бэктест-схемы в {DB_FILE.relative_to(ROOT).as_posix()}')

    con = duckdb.connect(str(DB_FILE))
    try:
        before = set(_list_tables(con))
        _create_schema(con)
        after = set(_list_tables(con))
    finally:
        con.close()

    created = sorted(after - before)
    if created:
        print(f'Созданы таблицы: {", ".join(created)}')
    else:
        print('Все таблицы уже существуют — изменений не требуется.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
