"""Движок языка поиска прецедентов (Precedent Query Language, PQL).

Создаёт DuckDB-соединение и регистрирует видимую схему PQL:
    - таблицы events / tags / event_tags (загружаются из CSV);
    - представление tagged_events (events JOIN event_tags JOIN tags);
    - SQL-функцию car() — обёртка над EventStudy.analyze.

Промежуточный движок — DuckDB (in-memory). Никаких DuckDB-only расширений
не используем: всё, что в схеме и в SQL — стандартный SQL, переносимый
в Postgres при будущей миграции.
"""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

import duckdb
import pandas as pd

from core.event_study import EventStudy
from core.market_data_provider import (
    load_daily_risk_free_rate,
    load_market_index_log_returns,
)
from core.stock_data_provider import get_log_returns

_DB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'db')
EVENTS_PATH = os.path.join(_DB_DIR, 'events.csv')
TAGS_PATH = os.path.join(_DB_DIR, 'tags.csv')
EVENT_TAGS_PATH = os.path.join(_DB_DIR, 'event_tags.csv')


# ---------------------------------------------------------------------------
# Кеши данных для UDF car(): один раз загружаем ряды доходностей за процесс.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _stock_log_returns(ticker: str) -> pd.Series:
    return get_log_returns(ticker)


@lru_cache(maxsize=1)
def _market_log_returns() -> pd.Series:
    return load_market_index_log_returns()


@lru_cache(maxsize=1)
def _rf_log_returns() -> pd.Series:
    return load_daily_risk_free_rate()


# ---------------------------------------------------------------------------
# Реализация SQL-функции car()
# ---------------------------------------------------------------------------

def _car_impl(
        ticker: str,
        event_date: date,
        model: str,
        window_before: int,
        window_after: int,
        estimation: int,
        outlier_threshold: float | None,
) -> float | None:
    """
    Вычисляет CAR для пары (ticker, event_date) через EventStudy.analyze.
    Возвращает None при отсутствии данных по тикеру или нехватке истории.
    """
    if ticker is None or event_date is None:
        return None
    try:
        stock = _stock_log_returns(ticker.upper())
    except (ValueError, FileNotFoundError, OSError):
        return None

    market = _market_log_returns() if model in ('market_model', 'capm') else None
    rf = _rf_log_returns() if model == 'capm' else None

    es = EventStudy(stock_log_returns=stock)
    result = es.analyze(
        event_date=event_date,
        model=model,
        event_window=(-int(window_before), int(window_after)),
        estimation_window=int(estimation),
        market=market,
        rf=rf,
        outlier_threshold=outlier_threshold,
    )
    if result is None:
        return None
    return float(result.car)


# ---------------------------------------------------------------------------
# Создание движка и регистрация схемы
# ---------------------------------------------------------------------------

def create_engine(
        events_path: str = EVENTS_PATH,
        tags_path: str = TAGS_PATH,
        event_tags_path: str = EVENT_TAGS_PATH,
) -> duckdb.DuckDBPyConnection:
    """Создаёт DuckDB-соединение с зарегистрированной схемой PQL."""
    con = duckdb.connect(':memory:')

    events_df = pd.read_csv(events_path, parse_dates=['date_start', 'date_end'])
    tags_df = pd.read_csv(tags_path)
    event_tags_df = pd.read_csv(event_tags_path)

    con.register('_events_src', events_df)
    con.register('_tags_src', tags_df)
    con.register('_event_tags_src', event_tags_df)

    con.execute("CREATE TABLE events     AS SELECT * FROM _events_src")
    con.execute("CREATE TABLE tags       AS SELECT * FROM _tags_src")
    con.execute("CREATE TABLE event_tags AS SELECT * FROM _event_tags_src")

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

    # Регистрируем UDF под внутренним именем; пользовательский car() — макрос
    # с дефолтными значениями параметров (стандартный SQL-синтаксис).
    con.create_function(
        '_car_impl',
        _car_impl,
        ['VARCHAR', 'DATE', 'VARCHAR', 'INTEGER', 'INTEGER', 'INTEGER', 'DOUBLE'],
        'DOUBLE',
        null_handling='special',
    )

    con.execute("""
        CREATE MACRO car(
            ticker, event_date,
            model := 'market_model',
            window_before := 5,
            window_after := 5,
            estimation := 200,
            outlier_threshold := NULL
        ) AS _car_impl(
            ticker, event_date,
            model, window_before, window_after, estimation, outlier_threshold
        )
    """)

    return con
