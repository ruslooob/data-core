"""Поставщик дивидендных событий.

Контракт — см. docs/SPEC_DATA_PROVIDERS.md.
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd

from core.models import DividendEvent

DIVIDENDS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'stocks', 'dividends_all.csv')


class DividendDataProvider:
    """Поставщик дивидендных событий из CSV.

    Параметры:
        max_date: последняя видимая дата (включительно). По умолчанию None — без ограничений.
                  События с announcement_date > max_date отбрасываются.
    """

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date) if max_date is not None else None

    def load_dividends(self) -> list[DividendEvent]:
        """Загружает дивидендные события: ticker, announcement_date, dividend_per_share, year."""
        df = pd.read_csv(DIVIDENDS_PATH)
        df["announcement_date"] = pd.to_datetime(df["announcement_date"], dayfirst=True)
        if self._max_date is not None:
            df = df[df["announcement_date"] <= self._max_date]
        events: list[DividendEvent] = []
        for _, row in df.iterrows():
            events.append(DividendEvent(
                ticker=str(row["ticker"]).upper(),
                event_date=row["announcement_date"].date(),
                dividend=float(row["dividend_per_share"]),
                year=int(row["year"]),
            ))
        return events

    def load_payments_by_date(self) -> dict[tuple[date, str], float]:
        """Карта `(payment_date, ticker) → dividend_per_share`.

        Используется бэктест-движком: на каждом тике он смотрит, есть ли
        в этой карте записи с `payment_date == :tick` для тикеров в портфеле,
        и автоматически начисляет выплату. См. Часть 3.3 драфта бэктеста.
        """
        df = pd.read_csv(DIVIDENDS_PATH)
        df["payment_date"] = pd.to_datetime(df["payment_date"], dayfirst=True)
        if self._max_date is not None:
            df = df[df["payment_date"] <= self._max_date]
        result: dict[tuple[date, str], float] = {}
        for _, row in df.iterrows():
            key = (row["payment_date"].date(), str(row["ticker"]).upper())
            # При коллизии (две выплаты в один день для одного тикера, что редкость)
            # — суммируем, иначе вторая теряется молча.
            result[key] = result.get(key, 0.0) + float(row["dividend_per_share"])
        return result
