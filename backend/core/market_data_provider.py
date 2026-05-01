"""Поставщик рыночных данных: безрисковая ставка (RUONIA), индекс рынка (IMOEX).

Контракт — см. docs/SPEC_DATA_PROVIDERS.md.
"""
from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'stocks')
RUONIA_PATH = os.path.join(_DATA_DIR, 'RUONIA_RC_F11_01_2010_T13_03_2026.xlsx')
IMOEX_PATH = os.path.join(_DATA_DIR, 'IMOEX_Индекс_МосБиржи_1day_01032000_17032026.txt')


class MarketDataProvider:
    """Поставщик данных рынка: индекс IMOEX и безрисковая ставка RUONIA.

    Параметры:
        max_date: последняя видимая дата (включительно). По умолчанию None — без ограничений.
                  Любой ряд обрезается так, чтобы значения с датой больше max_date не попадали.
    """

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date) if max_date is not None else None

    # ---- безрисковая ставка ------------------------------------------------

    def load_annual_risk_free_rate(
            self,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> pd.Series:
        """RUONIA в годовых процентах (как в исходнике ЦБ)."""
        return self._load_ruonia(start_date, end_date)

    def load_daily_risk_free_rate(
            self,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> pd.Series:
        """RUONIA, пересчитанная в дневную долю: ruo / 100 / 252."""
        return self._load_ruonia(start_date, end_date) / 100.0 / 252.0

    # ---- индекс рынка ------------------------------------------------------

    def load_market_index_prices(
            self,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        """Сырые дневные цены закрытия IMOEX."""
        return self._load_imoex_close(start_date, end_date)

    def load_market_index_log_returns(
            self,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        """Дневные логарифмические доходности IMOEX."""
        prices = self._load_imoex_close(start_date, end_date)
        log_returns = np.log(prices / prices.shift(1)).dropna()
        log_returns.index.name = "date"
        return log_returns

    # ---- внутренние загрузчики --------------------------------------------

    def _load_ruonia(self, start_date, end_date) -> pd.Series:
        """Сырая ставка RUONIA из xlsx ЦБ РФ — % годовых, индексированная датой."""
        df = pd.read_excel(RUONIA_PATH, sheet_name="RC", usecols=["DT", "ruo"])
        df["DT"] = pd.to_datetime(df["DT"])
        df = df.sort_values("DT").set_index("DT")
        if start_date is not None:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date is not None:
            df = df[df.index <= pd.Timestamp(end_date)]
        if self._max_date is not None:
            df = df[df.index <= self._max_date]
        series = df["ruo"]
        series.index.name = "date"
        return series

    def _load_imoex_close(self, start_date, end_date) -> pd.Series:
        """Сырые цены закрытия IMOEX из txt-выгрузки, индексированные датой."""
        df = pd.read_csv(IMOEX_PATH, sep=";", header=0, encoding="utf-8")
        df.columns = (
            df.columns
            .str.strip()
            .str.replace(r"[<>]", "", regex=True)
            .str.upper()
        )
        df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
        df = df[["DATE", "CLOSE"]].dropna().sort_values("DATE")
        if start_date:
            df = df[df["DATE"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["DATE"] <= pd.Timestamp(end_date)]
        if self._max_date is not None:
            df = df[df["DATE"] <= self._max_date]
        prices = df.set_index("DATE")["CLOSE"]
        prices.index.name = "date"
        return prices
