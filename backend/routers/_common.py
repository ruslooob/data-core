"""Общие хелперы и singleton-провайдеры для роутеров API."""
from __future__ import annotations

from datetime import date as _date, datetime, timezone
from decimal import Decimal

import psycopg
from fastapi import HTTPException

from core.dividend_data_provider import DividendDataProvider
from core.market_data_provider import MarketDataProvider
from core.postgres_db import PG_DSN
from core.stock_data_provider import StockDataProvider

# Дефолтные провайдеры, где режим отсутствия подглядывания в будущее не требуется.
stocks = StockDataProvider()
market = MarketDataProvider()
dividends = DividendDataProvider()

DEFAULT_RESEARCH_ID = '00000000-0000-0000-0000-000000000001'

_PG_TYPE_NAMES = {
    23: 'INTEGER', 20: 'BIGINT', 21: 'SMALLINT',
    700: 'REAL', 701: 'DOUBLE',
    1700: 'NUMERIC',
    25: 'TEXT', 1043: 'VARCHAR',
    16: 'BOOLEAN',
    1082: 'DATE', 1114: 'TIMESTAMP', 1184: 'TIMESTAMPTZ',
    114: 'JSON', 3802: 'JSONB',
}


def get_pg():
    """Открывает psycopg-коннект для одного HTTP-запроса.

    autocommit=True снимает необходимость явного commit() для
    INSERT/UPDATE/DELETE. Коннект закрывается автоматически по выходу
    из scope handler-функции (CPython ref-counting).
    """
    return psycopg.connect(PG_DSN, autocommit=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail='Имя не может быть пустым')
    return name


def pg_type_name(type_code: int) -> str:
    """Сопоставление OID типа Postgres → читаемое имя."""
    return _PG_TYPE_NAMES.get(type_code, f'OID:{type_code}')


def fetch_research(con, research_id: str):
    """Возвращает строку исследования или None. Используется и роутером research,
    и роутерами стратегий/правил/окружений для валидации существования."""
    return con.execute(
        'SELECT id, name, description, conclusion, created_at '
        'FROM research WHERE id = %s', [research_id],
    ).fetchone()


def validate_research_scope_target(con, new_research_id: str | None) -> None:
    if new_research_id is not None and fetch_research(con, new_research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')


def to_json_safe(value):
    """Конвертирует значение из БД в JSON-сериализуемое."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
