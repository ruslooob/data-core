"""Поставщик рыночных данных: безрисковая ставка (RUONIA), индекс рынка (IMOEX).

Источники в Postgres:
- IMOEX — `stock_candles WHERE ticker = 'IMOEX'`.
- RUONIA — `risk_free_rate (rate_date, annual_rate_pct)`.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from core.postgres_db import get_pool


class MarketDataProvider:
    """Поставщик данных рынка: индекс IMOEX и безрисковая ставка RUONIA."""

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date) if max_date is not None else None

    # ---- безрисковая ставка ------------------------------------------------

    def load_annual_risk_free_rate(
            self,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> pd.Series:
        return self._load_ruonia(start_date, end_date)

    def load_daily_risk_free_rate(
            self,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> pd.Series:
        return self._load_ruonia(start_date, end_date) / 100.0 / 252.0

    # ---- индекс рынка ------------------------------------------------------

    def load_market_index_prices(
            self,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        return self._load_imoex_close(start_date, end_date)

    def load_market_index_log_returns(
            self,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        prices = self._load_imoex_close(start_date, end_date)
        log_returns = np.log(prices / prices.shift(1)).dropna()
        log_returns.index.name = 'date'
        return log_returns

    # ---- внутренние загрузчики --------------------------------------------

    def _load_ruonia(self, start_date, end_date) -> pd.Series:
        sql = 'SELECT rate_date, annual_rate_pct FROM risk_free_rate'
        params: list = []
        clauses: list[str] = []
        if start_date is not None:
            clauses.append('rate_date >= %s')
            params.append(pd.Timestamp(start_date).date())
        if end_date is not None:
            clauses.append('rate_date <= %s')
            params.append(pd.Timestamp(end_date).date())
        if self._max_date is not None:
            clauses.append('rate_date <= %s')
            params.append(self._max_date.date())
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY rate_date'
        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()
        if not rows:
            return pd.Series(dtype=float)
        idx = pd.DatetimeIndex([r[0] for r in rows])
        s = pd.Series([float(r[1]) for r in rows], index=idx, name='ruonia')
        s.index.name = 'date'
        return s

    def _load_imoex_close(self, start_date, end_date) -> pd.Series:
        sql = "SELECT candle_date, close FROM stock_candles WHERE ticker = 'IMOEX'"
        params: list = []
        if start_date is not None:
            sql += ' AND candle_date >= %s'
            params.append(pd.Timestamp(start_date).date())
        if end_date is not None:
            sql += ' AND candle_date <= %s'
            params.append(pd.Timestamp(end_date).date())
        if self._max_date is not None:
            sql += ' AND candle_date <= %s'
            params.append(self._max_date.date())
        sql += ' ORDER BY candle_date'
        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()
        if not rows:
            return pd.Series(dtype=float)
        idx = pd.DatetimeIndex([r[0] for r in rows])
        s = pd.Series([float(r[1]) for r in rows], index=idx, name='imoex')
        s.index.name = 'date'
        return s
