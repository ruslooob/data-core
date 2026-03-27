"""Загрузка рыночных данных: безрисковая ставка (RUONIA) и рыночный индекс (IMOEX)."""
from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'stocks')
RUONIA_PATH = os.path.join(_DATA_DIR, 'RUONIA_RC_F11_01_2010_T13_03_2026.xlsx')
IMOEX_PATH = os.path.join(_DATA_DIR, 'IMOEX_Индекс_МосБиржи_1day_01032000_17032026.txt')


def load_risk_free_rate(
        path: str = RUONIA_PATH,
        start: date | None = None,
        end: date | None = None,
) -> pd.Series:
    """
    Загружает дневные безрисковые ставки RUONIA из файла .xlsx (ЦБ РФ).

    Формат файла: лист RC, колонки DT (дата) и ruo (% годовых).
    Возвращает pd.Series[float] с индексом pd.DatetimeIndex, значения —
    дневная ставка: ruo / 100 / 252.
    """
    df = pd.read_excel(path, sheet_name="RC", usecols=["DT", "ruo"])
    df["DT"] = pd.to_datetime(df["DT"])
    df = df.sort_values("DT").set_index("DT")
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    rf = df["ruo"] / 100.0 / 252.0
    rf.index.name = "date"
    return rf


def load_market_index(
        path: str = IMOEX_PATH,
        start_date: str | None = None,
        end_date: str | None = None,
) -> pd.Series:
    """
    Загружает дневные логдоходности индекса IMOEX из .txt файла.

    Возвращает pd.Series[float] с индексом pd.DatetimeIndex.
    """
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
    log_ret = np.log(prices / prices.shift(1)).dropna()
    log_ret.index.name = "date"
    return log_ret
