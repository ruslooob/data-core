"""Загрузка дивидендных событий."""
from __future__ import annotations

import os

import pandas as pd

from core.nirs.study import DividendEvent

DIVIDENDS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'stocks', 'dividends_all.csv')


def load_dividends(path: str = DIVIDENDS_PATH) -> list[DividendEvent]:
    """
    Загружает дивидендные события из CSV.

    Ожидаемые колонки: ticker, announcement_date, dividend_per_share, year.
    """
    df = pd.read_csv(path)
    df["announcement_date"] = pd.to_datetime(df["announcement_date"], dayfirst=True)
    events: list[DividendEvent] = []
    for _, row in df.iterrows():
        events.append(DividendEvent(
            ticker=str(row["ticker"]).upper(),
            event_date=row["announcement_date"].date(),
            dividend=float(row["dividend_per_share"]),
            year=int(row["year"]),
        ))
    return events
