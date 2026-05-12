"""DTO для рыночных данных: цены, индексы, дивидендные события."""
from schemas._common import CamelModel


class Candle(CamelModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class SeriesPoint(CamelModel):
    date: str
    value: float


class DividendEventOut(CamelModel):
    id: str
    ticker: str
    event_date: str
    dividend: float
    year: int
