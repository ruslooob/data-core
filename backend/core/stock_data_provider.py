"""Поставщик данных по акциям: котировки, сплиты, дневные доходности.

Источник — Postgres-таблицы `stock_candles` (нормализованные по сплитам),
`stocks` (реестр) и `events` (тег `STOCK_SPLIT` — сплиты как обычные
события). Загружается через psycopg-pool из `core.postgres_db`. Контракт
публичных методов сохранён по сравнению с CSV-версией: код выше по
стеку (event_study, backtest_engine, API) не должен заметить переезд.

Параметр `max_date` ограничивает видимый ряд верхней границей
включительно — нужен бэктесту для no-lookahead.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from core.postgres_db import get_pool


class StockDataProvider:
    """Поставщик котировок акций из Postgres."""

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date) if max_date is not None else None
        self._full_candles_cache: dict[str, pd.DataFrame] = {}
        self._full_log_returns_cache: dict[str, pd.Series] = {}

    # ---- публичные методы ---------------------------------------------------

    def list_tickers(self) -> list[str]:
        with get_pool().connection() as con:
            rows = con.execute('SELECT ticker FROM stocks ORDER BY ticker').fetchall()
        return [r[0] for r in rows]

    def get_ticker_splits(self, ticker: str) -> list[dict]:
        """Список сплитов по тикеру из событий `STOCK_SPLIT` в `events`.

        Формат элемента — `{'split_date': 'YYYY-MM-DD', 'ratio': float}`,
        совместимый с прежним JSONB-полем `stocks.splits` (теперь дропнуто).
        """
        with get_pool().connection() as con:
            rows = con.execute(
                "SELECT e.date_start, (e.payload->>'ratio')::float "
                "FROM events e "
                "JOIN event_tags et ON et.event_id = e.id "
                "WHERE et.tag_code = 'STOCK_SPLIT' "
                "  AND e.payload->>'ticker' = %s "
                "ORDER BY e.date_start",
                [ticker.upper()],
            ).fetchall()
        return [{'split_date': d.isoformat(), 'ratio': float(r)} for d, r in rows]

    def get_candles(
            self,
            ticker: str,
            normalized: bool = True,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.DataFrame:
        """Возвращает DataFrame с котировками: DATE/OPEN/HIGH/LOW/CLOSE/VOL.

        В Postgres-БД котировки уже нормализованы по сплитам, поэтому
        параметр `normalized` сейчас игнорируется (всегда normalized).
        Сырые значения восстановимы через `get_ticker_splits()` (события
        `STOCK_SPLIT`), если потребуется — пока такая необходимость не
        возникала.

        Поведение `max_date` поставщика: применяется как дополнительный
        потолок к `end_date`.
        """
        del normalized  # см. docstring
        start_ts = _parse_date(start_date, 'start_date')
        end_ts = _parse_date(end_date, 'end_date')
        if start_ts is not None and end_ts is not None and start_ts > end_ts:
            raise ValueError(
                f"start_date ({start_date}) позже end_date ({end_date})",
            )

        ticker_u = ticker.upper()
        no_filters = start_ts is None and end_ts is None

        if no_filters and self._max_date is None and ticker_u in self._full_candles_cache:
            return self._full_candles_cache[ticker_u]

        sql = (
            'SELECT candle_date, open, high, low, close, volume '
            'FROM stock_candles WHERE ticker = %s'
        )
        params: list = [ticker_u]
        if start_ts is not None:
            sql += ' AND candle_date >= %s'
            params.append(start_ts.date())
        if end_ts is not None:
            sql += ' AND candle_date <= %s'
            params.append(end_ts.date())
        if self._max_date is not None:
            sql += ' AND candle_date <= %s'
            params.append(self._max_date.date())
        sql += ' ORDER BY candle_date'

        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()

        if not rows:
            # Тикер существует в `stocks`, но за заданное окно нет данных —
            # возвращаем пустой DataFrame с правильными колонками.
            with get_pool().connection() as con:
                exists = con.execute(
                    'SELECT 1 FROM stocks WHERE ticker = %s', [ticker_u],
                ).fetchone()
            if not exists:
                with get_pool().connection() as con:
                    available = [r[0] for r in con.execute(
                        'SELECT ticker FROM stocks ORDER BY ticker',
                    ).fetchall()]
                raise ValueError(
                    f"Тикер '{ticker}' не найден. Доступные: {', '.join(available)}",
                )
            return pd.DataFrame(columns=['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL'])

        df = pd.DataFrame(rows, columns=['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL'])
        df['DATE'] = pd.to_datetime(df['DATE'])
        for col in ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        if no_filters and self._max_date is None:
            self._full_candles_cache[ticker_u] = df

        return df

    def get_log_returns(
            self,
            ticker: str,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> pd.Series:
        ticker_u = ticker.upper()
        no_filters = start_date is None and end_date is None
        if no_filters and self._max_date is None and ticker_u in self._full_log_returns_cache:
            return self._full_log_returns_cache[ticker_u]

        df = self.get_candles(ticker, start_date=start_date, end_date=end_date)
        prices = df.set_index('DATE')['CLOSE']
        log_ret = np.log(prices / prices.shift(1)).dropna()
        log_ret.index.name = 'date'

        if no_filters and self._max_date is None:
            self._full_log_returns_cache[ticker_u] = log_ret
        return log_ret

    def get_ticker_info(
            self,
            ticker: str,
            normalized: bool = True,
            start_date: str | None = None,
            end_date: str | None = None,
    ) -> dict:
        del normalized
        ticker_u = ticker.upper()
        df = self.get_candles(ticker, start_date=start_date, end_date=end_date)
        splits = self.get_ticker_splits(ticker_u)
        return {
            'ticker': ticker_u,
            'date_from': df['DATE'].min().date() if not df.empty else None,
            'date_to': df['DATE'].max().date() if not df.empty else None,
            'trading_days': len(df),
            'has_splits': len(splits) > 0,
            'splits': splits,
        }

    # ---- TA-функции для PQL: event-study-семантика (event_date исключается) ─

    def vol_ratio(
            self,
            ticker: str,
            event_date: date,
            window_before: int = 5,
            window_after: int = 5,
    ) -> float | None:
        if ticker is None or event_date is None:
            return None
        try:
            log_returns = self.get_log_returns(ticker)
        except ValueError:
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
        if ticker is None or event_date is None:
            return None
        try:
            candles = self.get_candles(ticker)
        except ValueError:
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
    """Возвращает позиции `(start, stop)` для окон до/после события.

    Сам день события исключается. Если данных не хватает — возвращает
    None для соответствующего окна.
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
