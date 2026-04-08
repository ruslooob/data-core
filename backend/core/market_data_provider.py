"""Загрузка рыночных данных: безрисковая ставка (RUONIA) и рыночный индекс (IMOEX)."""
from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'stocks')
RUONIA_PATH = os.path.join(_DATA_DIR, 'RUONIA_RC_F11_01_2010_T13_03_2026.xlsx')
IMOEX_PATH = os.path.join(_DATA_DIR, 'IMOEX_Индекс_МосБиржи_1day_01032000_17032026.txt')


# ---------------------------------------------------------------------------
# Низкоуровневые загрузчики сырых рядов из файлов источников.
# Каждая публичная функция (load_*) — это тонкая обёртка над одним из них
# с финальным преобразованием единиц измерения.
# ---------------------------------------------------------------------------

def _load_ruonia_annual_percent(
        path: str,
        start_date: date | None,
        end_date: date | None,
) -> pd.Series:
    """Сырая ставка RUONIA из xlsx ЦБ РФ — % годовых, индексированная датой."""
    df = pd.read_excel(path, sheet_name="RC", usecols=["DT", "ruo"])
    df["DT"] = pd.to_datetime(df["DT"])
    df = df.sort_values("DT").set_index("DT")
    if start_date is not None:
        df = df[df.index >= pd.Timestamp(start_date)]
    if end_date is not None:
        df = df[df.index <= pd.Timestamp(end_date)]
    series = df["ruo"]
    series.index.name = "date"
    return series


def _load_imoex_close_prices(
        path: str,
        start_date: str | None,
        end_date: str | None,
) -> pd.Series:
    """Сырые цены закрытия индекса IMOEX из txt-выгрузки, индексированные датой."""
    df = pd.read_csv(path, sep=";", header=0, encoding="utf-8")
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
    prices = df.set_index("DATE")["CLOSE"]
    prices.index.name = "date"
    return prices


# ---------------------------------------------------------------------------
# Публичные функции
# ---------------------------------------------------------------------------

def load_annual_risk_free_rate(
        path: str = RUONIA_PATH,
        start_date: date | None = None,
        end_date: date | None = None,
) -> pd.Series:
    """RUONIA в годовых процентах (как в исходнике ЦБ)."""
    return _load_ruonia_annual_percent(path, start_date, end_date)


def load_daily_risk_free_rate(
        path: str = RUONIA_PATH,
        start_date: date | None = None,
        end_date: date | None = None,
) -> pd.Series:
    """RUONIA пересчитанная в дневную долю: ruo / 100 / 252."""
    return _load_ruonia_annual_percent(path, start_date, end_date) / 100.0 / 252.0


def load_market_index_prices(
        path: str = IMOEX_PATH,
        start_date: str | None = None,
        end_date: str | None = None,
) -> pd.Series:
    """Сырые дневные цены закрытия индекса IMOEX."""
    return _load_imoex_close_prices(path, start_date, end_date)


def load_market_index_log_returns(
        path: str = IMOEX_PATH,
        start_date: str | None = None,
        end_date: str | None = None,
) -> pd.Series:
    """Дневные логарифмические доходности индекса IMOEX."""
    prices = _load_imoex_close_prices(path, start_date, end_date)
    log_returns = np.log(prices / prices.shift(1)).dropna()
    log_returns.index.name = "date"
    return log_returns
