"""Поставщик дивидендных событий из таблицы `events`.

Дивиденды живут в общей таблице `events` как два события на каждый
платёж: «Объявление дивидендов TICK: X.XX ₽ за YYYY год» (date_start =
announce_date = announcement_date) и «Выплата дивидендов TICK: ...»
(date_start = payment_date, announce_date = announcement_date).
Специфика (ticker, dividend_per_share, year) лежит в `events.payload`.

Контракт публичных методов сохранён по сравнению с CSV/dividends-версией.
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
                  без ограничений. События с announce_date > max_date
                  отбрасываются.
    """

    def __init__(self, max_date: date | None = None):
        self._max_date = pd.Timestamp(max_date).date() if max_date is not None else None

    def load_dividends(self) -> list[DividendEvent]:
        """Дивидендные события (объявление): ticker, announcement_date,
        dividend, year."""
        sql = (
            "SELECT payload->>'ticker' AS ticker, "
            "date_start, "
            "(payload->>'dividend_per_share')::float AS div, "
            "(payload->>'year')::int AS year "
            "FROM events "
            "WHERE event LIKE 'Объявление дивидендов %%'"
        )
        params: list = []
        if self._max_date is not None:
            sql += ' AND announce_date <= %s'
            params.append(self._max_date)
        sql += ' ORDER BY date_start'
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

        Использует payment_date (= date_start события «Выплата
        дивидендов»), не announcement_date. При коллизии (две выплаты
        в один день для одного тикера) суммируются.
        """
        sql = (
            "SELECT date_start AS payment_date, "
            "payload->>'ticker' AS ticker, "
            "(payload->>'dividend_per_share')::float AS div "
            "FROM events "
            "WHERE event LIKE 'Выплата дивидендов %%'"
        )
        params: list = []
        if self._max_date is not None:
            sql += ' AND date_start <= %s'
            params.append(self._max_date)
        with get_pool().connection() as con:
            rows = con.execute(sql, params).fetchall()
        result: dict[tuple[date, str], float] = {}
        for payment_date, ticker, div in rows:
            key = (payment_date, str(ticker).upper())
            result[key] = result.get(key, 0.0) + float(div)
        return result
