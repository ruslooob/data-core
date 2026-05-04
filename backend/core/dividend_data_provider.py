"""Поставщик дивидендных событий из Postgres-таблицы `dividends`.

Контракт публичных методов сохранён по сравнению с CSV-версией.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from core.models import DividendEvent
from core.postgres_db import get_pool


class DividendDataProvider:
    """Поставщик дивидендных событий.

    Параметры:
        max_date: последняя видимая дата (включительно). По умолчанию None —
                  без ограничений. События с announcement_date > max_date
                  отбрасываются.
    """

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date).date() if max_date is not None else None

    def load_dividends(self) -> list[DividendEvent]:
        """Дивидендные события: ticker, announcement_date, dividend, year."""
        sql = (
            'SELECT ticker, announcement_date, dividend_per_share, year '
            'FROM dividends'
        )
        params: list = []
        if self._max_date is not None:
            sql += ' WHERE announcement_date <= %s'
            params.append(self._max_date)
        sql += ' ORDER BY announcement_date'
        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()
        return [
            DividendEvent(
                ticker=str(r[0]).upper(),
                event_date=r[1],
                dividend=float(r[2]),
                year=int(r[3]),
            )
            for r in rows
        ]

    def load_payments_by_date(self) -> dict[tuple[date, str], float]:
        """Карта `(payment_date, ticker) → dividend_per_share`.

        Использует payment_date (не announcement_date). Записи без
        payment_date пропускаются. При коллизии (две выплаты в один день
        для одного тикера) суммируются.
        """
        sql = (
            'SELECT payment_date, ticker, dividend_per_share '
            'FROM dividends WHERE payment_date IS NOT NULL'
        )
        params: list = []
        if self._max_date is not None:
            sql += ' AND payment_date <= %s'
            params.append(self._max_date)
        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()
        result: dict[tuple[date, str], float] = {}
        for payment_date, ticker, div in rows:
            key = (payment_date, str(ticker).upper())
            result[key] = result.get(key, 0.0) + float(div)
        return result
