"""Эндпоинты рыночных данных: health, тикеры, котировки, индексы, дивиденды."""
from fastapi import APIRouter, HTTPException, Query

from routers._common import dividends, market, stocks
from schemas.market import Candle, DividendEventOut, SeriesPoint

router = APIRouter()

# Служебные тикеры/пути, которые не являются акциями
_NON_TICKER_FILES = {"DIVIDENDS", "IMOEX", "RUONIA", "SPLITS"}

_SERIES_LOADERS = {
    "IMOEX": market.load_market_index_prices,
    "RUONIA": market.load_annual_risk_free_rate,
}


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/tickers")
def get_tickers() -> list[str]:
    """Возвращает список доступных тикеров акций (без служебных файлов)."""
    return [t for t in stocks.list_tickers() if t not in _NON_TICKER_FILES]


@router.get("/api/prices/{ticker}", response_model_by_alias=True)
def get_prices(
        ticker: str,
        start_date: str | None = Query(None, alias="startDate"),
        end_date: str | None = Query(None, alias="endDate"),
) -> list[Candle]:
    """Возвращает OHLCV-котировки для тикера."""
    df = stocks.get_candles(ticker, normalized=True, start_date=start_date, end_date=end_date)
    return [
        Candle(
            date=row.DATE.strftime("%Y-%m-%d"),
            open=row.OPEN,
            high=row.HIGH,
            low=row.LOW,
            close=row.CLOSE,
            volume=row.VOL,
        )
        for row in df.itertuples()
    ]


@router.get("/api/series/{name}", response_model_by_alias=True)
def get_series(name: str) -> list[SeriesPoint]:
    """Возвращает временной ряд индекса/ставки: [{date, value}]."""
    key = name.upper()
    loader = _SERIES_LOADERS.get(key)
    if loader is None:
        raise HTTPException(status_code=404, detail=f"Unknown series: {name}")
    series = loader()
    return [
        SeriesPoint(date=ts.strftime("%Y-%m-%d"), value=float(val))
        for ts, val in series.items()
    ]


@router.get("/api/events", response_model_by_alias=True)
def get_events(
        ticker: str | None = None,
        start_date: str | None = Query(None, alias="startDate"),
        end_date: str | None = Query(None, alias="endDate"),
) -> list[DividendEventOut]:
    """Возвращает список дивидендных событий с опциональной фильтрацией."""
    import pandas as pd

    events = dividends.load_dividends()
    start_ts = pd.Timestamp(start_date) if start_date else None
    end_ts = pd.Timestamp(end_date) if end_date else None

    result = []
    for ev in events:
        if ticker and ev.ticker != ticker.upper():
            continue
        ev_ts = pd.Timestamp(ev.event_date)
        if start_ts and ev_ts < start_ts:
            continue
        if end_ts and ev_ts > end_ts:
            continue
        result.append(DividendEventOut(
            id=f"{ev.ticker}_{ev.event_date.isoformat()}",
            ticker=ev.ticker,
            event_date=ev.event_date.isoformat(),
            dividend=ev.dividend,
            year=ev.year,
        ))
    return result
