"""Поставщик данных по акциям: котировки, сплиты, дневные доходности.

Контракт — см. docs/SPEC_DATA_PROVIDERS.md.
"""
from __future__ import annotations

import json
import os
from datetime import date

import numpy as np
import pandas as pd

STOCKS_FOLDER = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'stocks')
_SPLITS_PATH = os.path.join(STOCKS_FOLDER, 'splits.json')


class StockDataProvider:
    """Поставщик котировок акций.

    Параметры:
        max_date: последняя видимая дата (включительно). По умолчанию None — без ограничений.
                  Любой запрос за дату строго больше max_date обрезается; ряд тоже обрезается.
    """

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date) if max_date is not None else None

    # ---- публичные методы ---------------------------------------------------

    def list_tickers(self) -> list[str]:
        """Возвращает список доступных тикеров на основе файлов в STOCKS_FOLDER."""
        tickers = []
        for filename in os.listdir(STOCKS_FOLDER):
            name, _ = os.path.splitext(filename)
            ticker = name.split('_')[0].upper()
            tickers.append(ticker)
        return sorted(tickers)

    def get_ticker_splits(self, ticker: str) -> list[dict]:
        """Возвращает список сплитов по тикеру из splits.json."""
        with open(_SPLITS_PATH, "r", encoding="utf-8") as f:
            splits = json.load(f)
        return splits.get(ticker, [])

    def get_candles(
            self,
            ticker: str,
            normalized: bool = True,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.DataFrame:
        """Возвращает DataFrame с котировками для указанного тикера.

        Параметры:
            ticker:     тикер акции (например, 'LKOH')
            normalized: учитывать сплиты и обратные сплиты
            start_date: фильтр с даты включительно (например, '2020-01-01')
            end_date:   фильтр по дату включительно (например, '2022-12-31')

        Поведение `max_date` поставщика: применяется как дополнительный потолок
        к end_date. Если переданный end_date больше max_date или не задан —
        эффективная верхняя граница = max_date.

        Исключения:
            ValueError: если тикер не найден, даты невалидны или start_date > end_date.
        """
        start_ts = _parse_date(start_date, "start_date")
        end_ts = _parse_date(end_date, "end_date")

        if start_ts is not None and end_ts is not None and start_ts > end_ts:
            raise ValueError(
                f"start_date ({start_date}) позже end_date ({end_date})"
            )

        ticker = ticker.upper()
        file_path = _find_candles_file(ticker)

        df = _load_normalized_candles(ticker, file_path) if normalized else _load_candles(file_path)

        if start_ts is not None:
            df = df[df['DATE'] >= start_ts]
        if end_ts is not None:
            df = df[df['DATE'] <= end_ts]
        if self._max_date is not None:
            df = df[df['DATE'] <= self._max_date]

        return df.reset_index(drop=True)

    def get_log_returns(
            self,
            ticker: str,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        """Дневные логарифмические доходности для тикера. Учитывает сплиты."""
        df = self.get_candles(ticker, normalized=True, start_date=start_date, end_date=end_date)
        prices = df.set_index('DATE')['CLOSE']
        log_ret = np.log(prices / prices.shift(1)).dropna()
        log_ret.index.name = 'date'
        return log_ret

    def get_ticker_info(
            self,
            ticker: str,
            normalized: bool = True,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> dict:
        """Метаинформация о тикере: диапазон дат, число торговых дней, сплиты."""
        ticker = ticker.upper()
        df = self.get_candles(ticker, normalized=normalized, start_date=start_date, end_date=end_date)
        splits = self.get_ticker_splits(ticker)

        return {
            "ticker": ticker,
            "date_from": df['DATE'].min().date() if not df.empty else None,
            "date_to": df['DATE'].max().date() if not df.empty else None,
            "trading_days": len(df),
            "has_splits": len(splits) > 0,
            "splits": splits,
        }


# ---------------------------------------------------------------------------
# Внутренние функции — без знания о max_date; работают с сырыми файлами.
# ---------------------------------------------------------------------------

def _load_candles(csv_path: str) -> pd.DataFrame:
    """Загружает котировки из CSV формата <TICKER>;<PER>;<DATE>;<TIME>;<O>;<H>;<L>;<C>;<V>."""
    dtypes = {
        "TICKER": "string",
        "PER": "string",
        "OPEN": "float64",
        "HIGH": "float64",
        "LOW": "float64",
        "CLOSE": "float64",
        "VOL": "float64",
        "OPENINT": "float64",
    }
    df = pd.read_csv(csv_path, sep=";", header=0, dtype=dtypes, encoding="utf-8")
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r"[<>]", "", regex=True)
        .str.upper()
    )
    df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    df["TIME"] = pd.to_datetime(df["TIME"].astype(str).str.zfill(6), format="%H%M%S").dt.time
    return df[['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL']]


def _load_normalized_candles(ticker: str, csv_path: str) -> pd.DataFrame:
    """Котировки с поправкой на сплиты."""
    df = _load_candles(csv_path)

    with open(_SPLITS_PATH, "r", encoding="utf-8") as f:
        all_splits = json.load(f)
    splits = all_splits.get(ticker, [])

    df["ADJ_FACTOR"] = 1.0

    if splits:
        events = sorted(splits, key=lambda e: e["split_date"])
        for event in events:
            split_date = pd.to_datetime(event["split_date"])
            ratio = event["ratio"]
            df.loc[df["DATE"] < split_date, "ADJ_FACTOR"] *= ratio

    for col in ["OPEN", "HIGH", "LOW", "CLOSE"]:
        df[col] = df[col] / df["ADJ_FACTOR"]
    df["VOL"] = df["VOL"] * df["ADJ_FACTOR"]

    return df.drop('ADJ_FACTOR', axis=1)


def _find_candles_file(ticker: str) -> str:
    """Возвращает путь к файлу котировок по тикеру или бросает ValueError."""
    for filename in os.listdir(STOCKS_FOLDER):
        if filename.startswith(ticker):
            return os.path.join(STOCKS_FOLDER, filename)
    available = sorted({n.split('_')[0].upper() for n in os.listdir(STOCKS_FOLDER)})
    raise ValueError(
        f"Тикер '{ticker}' не найден. Доступные: {', '.join(available)}"
    )


def _parse_date(value: str | None, field_name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Невалидное значение {field_name}='{value}': {e}") from e
