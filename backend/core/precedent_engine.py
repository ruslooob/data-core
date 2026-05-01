"""Движок языка поиска прецедентов (Precedent Query Language, PQL).

Открывает соединение с единой DuckDB-базой проекта (data/db/data-core.duckdb),
в которой персистентно лежат таблицы events / tags / event_tags / precedent_queries
и представление tagged_events.

Дополнительно регистрирует SQL-функцию car() — обёртку над EventStudy.analyze.
UDF и макросы DuckDB существуют только в рамках сессии, поэтому регистрируются
при каждом открытии соединения.
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
APP_DB_PATH = os.path.abspath(os.path.join(_DB_DIR, 'data-core.duckdb'))


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
# Регистрация UDF и макроса
# ---------------------------------------------------------------------------

def _register_car(con: duckdb.DuckDBPyConnection) -> None:
    """Регистрирует UDF _car_impl и удобный макрос car() с дефолтными параметрами.

    Несколько одновременно открытых соединений к одному файлу разделяют каталог
    функций. Если функция уже зарегистрирована другим соединением — это не
    ошибка, продолжаем.
    """
    try:
        con.create_function(
            '_car_impl',
            _car_impl,
            ['VARCHAR', 'DATE', 'VARCHAR', 'INTEGER', 'INTEGER', 'INTEGER', 'DOUBLE'],
            'DOUBLE',
            null_handling='special',
        )
    except duckdb.CatalogException:
        pass
    con.execute("""
        CREATE OR REPLACE TEMP MACRO car(
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


# ---------------------------------------------------------------------------
# Открытие соединения
# ---------------------------------------------------------------------------

def create_engine(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Открывает соединение с DuckDB-файлом проекта и регистрирует UDF + макрос car().

    Если файл не существует — кидает FileNotFoundError с подсказкой о миграции.
    """
    path = db_path or APP_DB_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'DuckDB-файл не найден: {path}. '
            'Запустите scripts/migrate_csv_to_duckdb.py для первичной миграции.'
        )
    con = duckdb.connect(path)
    _register_car(con)
    return con
