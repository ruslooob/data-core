"""FastAPI backend для data-core."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from datetime import date

from core.dividend_data_provider import load_dividends
from core.event_study import EventStudy
from core.market_data_provider import (
    load_market_index,
    load_market_index_prices,
    load_risk_free_rate,
    load_risk_free_rate_annual,
)
from core.stock_data_provider import get_candles, get_log_returns, list_tickers

# Служебные файлы, которые не являются тикерами акций
_NON_TICKER_FILES = {"DIVIDENDS", "IMOEX", "RUONIA", "SPLITS"}

app = FastAPI(title="data-core API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tickers")
def get_tickers() -> list[str]:
    """Возвращает список доступных тикеров акций (без служебных файлов)."""
    return [t for t in list_tickers() if t not in _NON_TICKER_FILES]


class Candle(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@app.get("/api/prices/{ticker}")
def get_prices(
        ticker: str,
        start: str | None = None,
        end: str | None = None,
) -> list[Candle]:
    """Возвращает OHLCV-котировки для тикера."""
    df = get_candles(ticker, normalized=True, start_date=start, end_date=end)
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


class SeriesPoint(BaseModel):
    date: str
    value: float


_SERIES_LOADERS = {
    "IMOEX": load_market_index_prices,
    "RUONIA": load_risk_free_rate_annual,
}


@app.get("/api/series/{name}")
def get_series(name: str) -> list[SeriesPoint]:
    """Возвращает временной ряд индекса/ставки: [{date, value}]."""
    key = name.upper()
    loader = _SERIES_LOADERS.get(key)
    if loader is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown series: {name}")
    series = loader()
    return [
        SeriesPoint(date=ts.strftime("%Y-%m-%d"), value=float(val))
        for ts, val in series.items()
    ]


class DividendEventOut(BaseModel):
    id: str
    ticker: str
    event_date: str
    dividend: float
    year: int


@app.get("/api/events")
def get_events(
        ticker: str | None = None,
        start: str | None = None,
        end: str | None = None,
) -> list[DividendEventOut]:
    """Возвращает список дивидендных событий с опциональной фильтрацией."""
    import pandas as pd

    events = load_dividends()
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None

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


class EventStudyRequest(BaseModel):
    ticker: str
    event_date: str  # ISO format: YYYY-MM-DD
    model: str  # 'mean_adjusted', 'market_model', 'capm'
    event_window: tuple[int, int]  # (-10, 10)
    estimation_window: int  # 200


class EventStudyResponse(BaseModel):
    event_date: str
    ar: list[float]
    car: float
    n_days: int
    estimation_std: float


@app.post("/api/event-study")
def run_event_study(req: EventStudyRequest) -> EventStudyResponse:
    """Рассчитывает AR и CAR для одного события."""
    stock_log_returns = get_log_returns(req.ticker)
    market = load_market_index()
    rf = load_risk_free_rate()

    study = EventStudy(stock_log_returns=stock_log_returns)
    result = study.analyze(
        event_date=date.fromisoformat(req.event_date),
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market,
        rf=rf,
    )

    return EventStudyResponse(
        event_date=result.event_date.isoformat(),
        ar=result.ar,
        car=result.car,
        n_days=result.n_days,
        estimation_std=result.estimation_std,
    )
