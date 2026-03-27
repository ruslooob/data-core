"""
Загрузчики входных данных для событийного анализа.

Функции:
    load_events(path)          — список Event из dividends_all.csv
    load_rf(path, start, end)  — pd.Series дневных ставок RUONIA
    load_prices(stocks_dir)    — dict {ticker: pd.Series} логдоходностей
"""
from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd

from .study import Event

# ---------------------------------------------------------------------------
# Дивидендные события
# ---------------------------------------------------------------------------

def load_events(path: str) -> list[Event]:
    """
    Загружает дивидендные события из CSV.

    Ожидаемые колонки: ticker, announcement_date, dividend_per_share, year.
    """
    df = pd.read_csv(path)
    df["announcement_date"] = pd.to_datetime(df["announcement_date"], dayfirst=True)
    events: list[Event] = []
    for _, row in df.iterrows():
        events.append(Event(
            ticker=str(row["ticker"]).upper(),
            event_date=row["announcement_date"].date(),
            dividend=float(row["dividend_per_share"]),
            year=int(row["year"]),
        ))
    return events


# ---------------------------------------------------------------------------
# Безрисковая ставка RUONIA
# ---------------------------------------------------------------------------

def load_rf(path: str, start: date, end: date) -> pd.Series:
    """
    Загружает дневные безрисковые ставки RUONIA из файла .xlsx (ЦБ РФ).

    Формат файла: лист RC, колонки DT (дата) и ruo (% годовых).
    Возвращает pd.Series[float] с индексом pd.DatetimeIndex, значения —
    дневная ставка: ruo / 100 / 252.

    Пропущенные торговые дни (выходные, праздники) заполняются
    методом forward-fill.
    """
    df = pd.read_excel(path, sheet_name="RC", usecols=["DT", "ruo"])
    df["DT"] = pd.to_datetime(df["DT"])
    df = df.sort_values("DT").set_index("DT")
    df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    rf = df["ruo"] / 100.0 / 252.0
    rf.index.name = "date"
    return rf


# ---------------------------------------------------------------------------
# Котировки акций
# ---------------------------------------------------------------------------

def _load_single_file(path: str) -> pd.DataFrame:
    """Загружает один .txt файл котировок mfd.ru."""
    df = pd.read_csv(path, sep=";", header=0, encoding="utf-8")
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r"[<>]", "", regex=True)
        .str.upper()
    )
    df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    df = df[["DATE", "CLOSE"]].dropna()
    return df.sort_values("DATE").reset_index(drop=True)


def _log_returns(prices: pd.Series) -> pd.Series:
    """Вычисляет дневные логарифмические доходности."""
    return np.log(prices / prices.shift(1)).dropna()


def load_prices(
    stocks_dir: str,
    tickers: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, pd.Series]:
    """
    Загружает котировки из директории и возвращает
    словарь {ticker: pd.Series} дневных логдоходностей.

    Каждый тикер — один .txt файл. Имя файла начинается с тикера (до первого '_').

    Параметры:
        stocks_dir:  путь к директории с .txt файлами
        tickers:     список тикеров (None = все файлы)
        start_date:  нижняя граница фильтра дат (включительно)
        end_date:    верхняя граница фильтра дат (включительно)

    Возвращает:
        dict {ticker: pd.Series} где index — pd.DatetimeIndex,
        значения — логдоходности.
    """
    result: dict[str, pd.Series] = {}
    for fname in sorted(os.listdir(stocks_dir)):
        if not fname.endswith(".txt"):
            continue
        ticker = fname.split("_")[0].upper()
        if tickers is not None and ticker not in tickers:
            continue
        if ticker in result:
            continue

        df = _load_single_file(os.path.join(stocks_dir, fname))

        if start_date:
            df = df[df["DATE"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["DATE"] <= pd.Timestamp(end_date)]

        prices = df.set_index("DATE")["CLOSE"]
        log_ret = _log_returns(prices)
        log_ret.index.name = "date"
        result[ticker] = log_ret

    return result
