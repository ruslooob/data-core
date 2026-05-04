"""Подключение к Postgres-БД проекта.

Один глобальный pool на процесс. Все компоненты (PrecedentEngine,
StockDataProvider, MarketDataProvider, DividendDataProvider,
BacktestEngine) берут коннекты отсюда.

DSN зашит — локальная dev-БД из docker-compose. Для деплоя сделать
переопределение через env (когда дойдёт до прод-сборки; сейчас не
задача).
"""
from __future__ import annotations

import os

import psycopg
from psycopg_pool import ConnectionPool

PG_DSN = os.environ.get(
    'DATA_CORE_PG_DSN',
    'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres',
)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Ленивый singleton-pool psycopg-коннектов."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            PG_DSN,
            min_size=1,
            max_size=8,
            open=True,
            kwargs={'autocommit': False},
        )
    return _pool


def connect() -> psycopg.Connection:
    """Открывает одиночный коннект (минуя pool). Использовать когда нужен
    долго живущий коннект (например, в воркере бэктеста, где сессия PL/Python
    SD-кэша должна сохраняться от тика к тику)."""
    return psycopg.connect(PG_DSN, autocommit=False)
