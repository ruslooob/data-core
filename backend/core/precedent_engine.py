"""Движок языка поиска прецедентов (Precedent Query Language, PQL).

Открывает соединение с единой DuckDB-базой проекта (data/db/data-core.duckdb),
регистрирует SQL-функцию car() — обёртку над EventStudy.analyze.

Поставщики данных (StockDataProvider, MarketDataProvider) передаются
в конструктор: редактор PQL создаёт их без max_date, бэктест — с max_date,
равным предыдущему торговому дню. Это автоматически распространяется на
car(), потому что метод car_impl читает данные через self._stocks / self._market.
"""
from __future__ import annotations

import os
from datetime import date

import duckdb
import pandas as pd

from core.event_study import EventStudy
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider

_DB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'db')
APP_DB_PATH = os.path.abspath(os.path.join(_DB_DIR, 'data-core.duckdb'))


class PrecedentEngine:
    """Соединение с DuckDB-базой проекта + UDF и макрос car().

    Поставщики данных принимаются в конструкторе. Это делает движок
    одинаково пригодным для редактора PQL (поставщики без max_date,
    весь исторический интервал виден) и для бэктеста (поставщики с
    max_date текущего тика, будущие данные физически не доступны).

    Параметры:
        stocks:   поставщик котировок и log-доходностей по тикерам.
        market:   поставщик индекса рынка и безрисковой ставки.
        db_path:  путь к DuckDB-файлу. По умолчанию APP_DB_PATH.
                  Если файл не существует — FileNotFoundError с подсказкой.
    """

    def __init__(
            self,
            stocks: StockDataProvider,
            market: MarketDataProvider,
            db_path: str | None = None,
    ):
        path = db_path or APP_DB_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(
                f'DuckDB-файл не найден: {path}. '
                'Запустите scripts/migrate_csv_to_duckdb.py для первичной миграции.'
            )
        self._stocks = stocks
        self._market = market
        self.con: duckdb.DuckDBPyConnection = duckdb.connect(path)
        self._stock_log_returns_cache: dict[str, pd.Series] = {}
        self._market_log_returns: pd.Series | None = None
        self._rf_log_returns: pd.Series | None = None
        self._register_car()

    # ---- публичные методы --------------------------------------------------

    def close(self) -> None:
        """Закрыть DuckDB-соединение."""
        self.con.close()

    # ---- кэшированные ряды (per-instance, чтобы уважать max_date) ----------

    def _get_stock_log_returns(self, ticker: str) -> pd.Series:
        ticker = ticker.upper()
        if ticker not in self._stock_log_returns_cache:
            self._stock_log_returns_cache[ticker] = self._stocks.get_log_returns(ticker)
        return self._stock_log_returns_cache[ticker]

    def _get_market_log_returns(self) -> pd.Series:
        if self._market_log_returns is None:
            self._market_log_returns = self._market.load_market_index_log_returns()
        return self._market_log_returns

    def _get_rf_log_returns(self) -> pd.Series:
        if self._rf_log_returns is None:
            self._rf_log_returns = self._market.load_daily_risk_free_rate()
        return self._rf_log_returns

    # ---- car() реализация и регистрация ------------------------------------

    def _car_impl(
            self,
            ticker: str,
            event_date: date,
            model: str,
            window_before: int,
            window_after: int,
            estimation: int,
            outlier_threshold: float | None,
    ) -> float | None:
        """Вычисляет CAR через EventStudy.analyze. Возвращает None, если данных не хватает."""
        if ticker is None or event_date is None:
            return None
        try:
            stock = self._get_stock_log_returns(ticker)
        except (ValueError, FileNotFoundError, OSError):
            return None

        market = self._get_market_log_returns() if model in ('market_model', 'capm') else None
        rf = self._get_rf_log_returns() if model == 'capm' else None

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

    def _register_car(self) -> None:
        """Регистрирует UDF _car_impl и макрос car() с дефолтными параметрами.

        DuckDB шарит каталог функций между одновременно открытыми соединениями
        к одному файлу. Если функция уже зарегистрирована — это не ошибка.
        """
        try:
            self.con.create_function(
                '_car_impl',
                self._car_impl,
                ['VARCHAR', 'DATE', 'VARCHAR', 'INTEGER', 'INTEGER', 'INTEGER', 'DOUBLE'],
                'DOUBLE',
                null_handling='special',
            )
        except duckdb.CatalogException:
            pass

        self.con.execute("""
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
