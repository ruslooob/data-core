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
import uuid
from datetime import date, datetime, timezone

import duckdb
import pandas as pd

from core.event_study import EventStudy
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider

_DB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'db')
APP_DB_PATH = os.path.abspath(os.path.join(_DB_DIR, 'data-core.duckdb'))

# Стабильный namespace для UUID5-идентификаторов системных рецептов.
_SYSTEM_RECIPES_NAMESPACE = uuid.UUID('a1b2c3d4-e5f6-4789-9abc-1234567890ab')

# Системные рецепты-шаблоны, засеиваются при первом старте PrecedentEngine.
# Имена начинаются с ★ — это маркер защиты от перезаписи (UNIQUE на имя плюс
# проверка префикса в эндпоинте сохранения). Идемпотентность достигается
# проверкой на наличие записи с таким же именем перед INSERT.
_SYSTEM_RECIPES: list[tuple[str, str]] = [
    (
        '★ Объём: всплеск > 1.5×',
        """SELECT te.date_start, te.event, te.tag AS ticker,
       volume_ratio(te.tag, te.date_start) AS vol_x
FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE volume_ratio(te.tag, te.date_start) > 1.5
ORDER BY vol_x DESC
LIMIT 30;""",
    ),
    (
        '★ Волатильность: рост > 2×',
        """SELECT te.date_start, te.event, te.tag AS ticker,
       vol_ratio(te.tag, te.date_start) AS vola_x
FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE vol_ratio(te.tag, te.date_start) > 2.0
ORDER BY vola_x DESC
LIMIT 30;""",
    ),
    (
        '★ Возможный инсайд (CAR до t=0)',
        """SELECT te.date_start, te.event, te.tag AS ticker,
       car(te.tag, te.date_start, window_after => -1) AS car_pre
FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE ABS(car(te.tag, te.date_start, window_after => -1)) > 0.03
ORDER BY ABS(car_pre) DESC
LIMIT 30;""",
    ),
    (
        '★ Дивиденды LKOH: реакция цены',
        """SELECT te.date_start, te.event,
       car('LKOH', te.date_start) AS car
FROM tagged_events te
JOIN tagged_events te2 ON te2.event_id = te.event_id
WHERE te.tag = 'LKOH'
  AND te2.tag = 'DIVIDEND_ANNOUNCEMENT'
ORDER BY te.date_start DESC
LIMIT 30;""",
    ),
    (
        '★ Многофакторная оценка аномальности',
        """WITH scored AS (
  SELECT te.date_start, te.event, te.tag AS ticker,
         CASE WHEN ABS(car(te.tag, te.date_start)) > 0.05 THEN 1 ELSE 0 END
       + CASE WHEN volume_ratio(te.tag, te.date_start) > 2.0 THEN 1 ELSE 0 END
       + CASE WHEN vol_ratio(te.tag, te.date_start) > 2.0 THEN 1 ELSE 0 END
         AS score
  FROM tagged_events te
  JOIN tags t ON t.code = te.tag AND t.type = 'company'
)
SELECT date_start, event, ticker, score
FROM scored
WHERE score >= 2
ORDER BY score DESC, date_start DESC
LIMIT 20;""",
    ),
]


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
        self._seed_system_recipes()

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
        """Регистрирует UDF и макросы для PQL: car, vol_ratio, volume_ratio.

        DuckDB шарит каталог функций между одновременно открытыми соединениями
        к одному файлу. Если функция уже зарегистрирована — это не ошибка.
        """
        self._safe_create_function(
            '_car_impl',
            self._car_impl,
            ['VARCHAR', 'DATE', 'VARCHAR', 'INTEGER', 'INTEGER', 'INTEGER', 'DOUBLE'],
        )
        self._safe_create_function(
            '_vol_ratio_impl',
            self._stocks.vol_ratio,
            ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER'],
        )
        self._safe_create_function(
            '_volume_ratio_impl',
            self._stocks.volume_ratio,
            ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER'],
        )

        self.con.execute("""
            CREATE OR REPLACE MACRO car(
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
        self.con.execute("""
            CREATE OR REPLACE MACRO vol_ratio(
                ticker, event_date,
                window_before := 5,
                window_after := 5
            ) AS _vol_ratio_impl(ticker, event_date, window_before, window_after)
        """)
        self.con.execute("""
            CREATE OR REPLACE MACRO volume_ratio(
                ticker, event_date,
                window_before := 5,
                window_after := 5
            ) AS _volume_ratio_impl(ticker, event_date, window_before, window_after)
        """)

    def _safe_create_function(self, name: str, fn, argtypes: list[str]) -> None:
        """create_function с проглатыванием CatalogException (функция уже есть в каталоге)."""
        try:
            self.con.create_function(
                name, fn, argtypes, 'DOUBLE', null_handling='special',
            )
        except duckdb.CatalogException:
            pass

    # ---- системные рецепты-шаблоны -----------------------------------------

    def _seed_system_recipes(self) -> None:
        """Идемпотентная вставка системных рецептов в таблицу precedent_queries.

        Выполняется при создании движка. Каждый рецепт получает стабильный
        UUID5-идентификатор от своего имени, поэтому повторный запуск не
        плодит дубликатов даже если строка случайно потерялась. Если запись
        с таким именем уже есть — INSERT пропускается.

        Если в БД нет таблицы precedent_queries (например, fresh DB без
        прошедшей миграции) — метод тихо завершается без ошибок: системные
        рецепты неактуальны до инициализации остальной схемы.
        """
        try:
            self.con.execute("SELECT 1 FROM precedent_queries LIMIT 1")
        except duckdb.CatalogException:
            return

        for name, source in _SYSTEM_RECIPES:
            recipe_id = str(uuid.uuid5(_SYSTEM_RECIPES_NAMESPACE, name))
            created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            self.con.execute(
                """
                INSERT INTO precedent_queries (id, name, source, created_at)
                SELECT ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM precedent_queries WHERE name = ?
                )
                """,
                [recipe_id, name, source, created_at, name],
            )
