"""Поставщик данных по акциям: котировки, сплиты, дневные доходности.

Контракт — см. docs/SPEC_DATA_PROVIDERS.md.
"""
from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache

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
        # Кэши полного ряда (без фильтров start_date/end_date) per-instance.
        # Используются TA-методами (vol_ratio, volume_ratio) и публичными методами
        # без фильтров. С max_date взаимодействуют корректно: max_date применяется
        # один раз при первом построении кэша.
        self._full_candles_cache: dict[str, pd.DataFrame] = {}
        self._full_log_returns_cache: dict[str, pd.Series] = {}

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
        no_filters = start_ts is None and end_ts is None

        # Быстрый путь: нормализованные котировки без пользовательских фильтров —
        # отдаём из per-instance кэша (max_date уже применён при первом построении).
        if normalized and no_filters and ticker in self._full_candles_cache:
            return self._full_candles_cache[ticker]

        file_path = _find_candles_file(ticker)
        df = _load_normalized_candles(ticker, file_path) if normalized else _load_candles(file_path)

        if start_ts is not None:
            df = df[df['DATE'] >= start_ts]
        if end_ts is not None:
            df = df[df['DATE'] <= end_ts]
        if self._max_date is not None:
            df = df[df['DATE'] <= self._max_date]

        df = df.reset_index(drop=True)

        if normalized and no_filters:
            self._full_candles_cache[ticker] = df

        return df

    def get_log_returns(
            self,
            ticker: str,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        """Дневные логарифмические доходности для тикера. Учитывает сплиты."""
        ticker_upper = ticker.upper()
        no_filters = start_date is None and end_date is None

        if no_filters and ticker_upper in self._full_log_returns_cache:
            return self._full_log_returns_cache[ticker_upper]

        df = self.get_candles(ticker, normalized=True, start_date=start_date, end_date=end_date)
        prices = df.set_index('DATE')['CLOSE']
        log_ret = np.log(prices / prices.shift(1)).dropna()
        log_ret.index.name = 'date'

        if no_filters:
            self._full_log_returns_cache[ticker_upper] = log_ret

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

    # ---- TA-функции для PQL: event-study-семантика (event_date исключается) -

    def vol_ratio(
            self,
            ticker: str,
            event_date: date,
            window_before: int = 5,
            window_after: int = 5,
    ) -> float | None:
        """Отношение волатильности доходностей после события к волатильности до.

        Окно «до»  = `[event_date - window_before, event_date - 1]`.
        Окно «после» = `[event_date + 1, event_date + window_after]`.
        Сама дата события в окна не входит. Возвращает std(returns после) / std(returns до).

        Возвращает None, если данных недостаточно или знаменатель = 0.
        """
        if ticker is None or event_date is None:
            return None
        try:
            log_returns = self.get_log_returns(ticker)
        except (ValueError, FileNotFoundError, OSError):
            return None

        pre, post = _split_window(log_returns.index, event_date, int(window_before), int(window_after))
        if pre is None or post is None:
            return None
        pre_returns = log_returns.iloc[pre[0]:pre[1]]
        post_returns = log_returns.iloc[post[0]:post[1]]
        if len(pre_returns) < 2 or len(post_returns) < 2:
            return None

        pre_std = float(pre_returns.std(ddof=1))
        if pre_std == 0:
            return None
        return float(post_returns.std(ddof=1)) / pre_std

    def volume_ratio(
            self,
            ticker: str,
            event_date: date,
            window_before: int = 5,
            window_after: int = 5,
    ) -> float | None:
        """Отношение среднего объёма после события к среднему объёму до.

        Окно «до»  = `[event_date - window_before, event_date - 1]`.
        Окно «после» = `[event_date + 1, event_date + window_after]`.
        Сама дата события в окна не входит. Возвращает mean(volume после) / mean(volume до).

        Возвращает None, если данных недостаточно или средний объём «до» = 0.
        """
        if ticker is None or event_date is None:
            return None
        try:
            candles = self.get_candles(ticker, normalized=True)
        except (ValueError, FileNotFoundError, OSError):
            return None

        pre, post = _split_window(candles['DATE'], event_date, int(window_before), int(window_after))
        if pre is None or post is None:
            return None
        pre_vol = candles['VOL'].iloc[pre[0]:pre[1]]
        post_vol = candles['VOL'].iloc[post[0]:post[1]]
        if len(pre_vol) < 1 or len(post_vol) < 1:
            return None

        pre_mean = float(pre_vol.mean())
        if pre_mean == 0:
            return None
        return float(post_vol.mean()) / pre_mean


# ---------------------------------------------------------------------------
# Внутренние функции — без знания о max_date; работают с сырыми файлами.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
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


@lru_cache(maxsize=128)
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


def _split_window(
        dates,
        event_date: date,
        window_before: int,
        window_after: int,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Возвращает позиции `(start, stop)` для окна «до» и окна «после» события.

    `dates` — последовательность торговых дат (Series или DatetimeIndex), отсортированная.
    Сам день события исключается из обоих окон. Если нужного количества торговых
    дней до/после нет — возвращается None для соответствующего окна.
    """
    t0 = pd.Timestamp(event_date)
    if hasattr(dates, 'searchsorted'):
        idx0 = int(dates.searchsorted(t0, side='left'))
    else:
        idx0 = int(pd.Index(dates).searchsorted(t0, side='left'))

    n = len(dates)
    if idx0 >= n:
        return None, None

    pre_start = idx0 - window_before
    pre_stop = idx0
    post_start = idx0 + 1
    post_stop = idx0 + 1 + window_after

    pre = (pre_start, pre_stop) if pre_start >= 0 and pre_stop > pre_start else None
    post = (post_start, post_stop) if post_stop <= n and post_stop > post_start else None
    return pre, post
