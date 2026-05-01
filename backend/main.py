"""FastAPI backend для data-core."""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from datetime import date


class CamelModel(BaseModel):
    """Базовый Pydantic-класс с camelCase-сериализацией для JSON DTO.

    Поля внутри Python-класса остаются snake_case (Python-конвенция),
    а в JSON попадают как camelCase через alias_generator.
    populate_by_name=True позволяет принимать и snake_case, и camelCase на входе.
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

from core.anomaly_detector import detect_anomalies_batch, AnomalyResult as AnomalyResultCore
from core.dividend_data_provider import DividendDataProvider
from core.event_study import EventStudy, AggregateStudyResult
from core.market_data_provider import MarketDataProvider
from core.precedent_engine import PrecedentEngine
from core.stock_data_provider import StockDataProvider

# Дефолтные провайдеры без max_date — для эндпоинтов API, где режим
# отсутствия подглядывания в будущее не требуется.
_stocks = StockDataProvider()
_market = MarketDataProvider()
_dividends = DividendDataProvider()

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
    return [t for t in _stocks.list_tickers() if t not in _NON_TICKER_FILES]


# Все DTO-эндпоинты сериализуют JSON через by_alias=True (camelCase)


class Candle(CamelModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@app.get("/api/prices/{ticker}", response_model_by_alias=True)
def get_prices(
        ticker: str,
        start_date: str | None = Query(None, alias="startDate"),
        end_date: str | None = Query(None, alias="endDate"),
) -> list[Candle]:
    """Возвращает OHLCV-котировки для тикера."""
    df = _stocks.get_candles(ticker, normalized=True, start_date=start_date, end_date=end_date)
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


class SeriesPoint(CamelModel):
    date: str
    value: float


_SERIES_LOADERS = {
    "IMOEX": _market.load_market_index_prices,
    "RUONIA": _market.load_annual_risk_free_rate,
}


@app.get("/api/series/{name}", response_model_by_alias=True)
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


class DividendEventOut(CamelModel):
    id: str
    ticker: str
    event_date: str
    dividend: float
    year: int


@app.get("/api/events", response_model_by_alias=True)
def get_events(
        ticker: str | None = None,
        start_date: str | None = Query(None, alias="startDate"),
        end_date: str | None = Query(None, alias="endDate"),
) -> list[DividendEventOut]:
    """Возвращает список дивидендных событий с опциональной фильтрацией."""
    import pandas as pd

    events = _dividends.load_dividends()
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


class EventStudyRequest(CamelModel):
    ticker: str
    event_date: str  # ISO format: YYYY-MM-DD
    model: str  # 'mean_adjusted', 'market_model', 'capm'
    event_window: tuple[int, int]  # (-10, 10)
    estimation_window: int  # 200
    outlier_threshold: float | None = None  # σ-порог фильтрации выбросов


class EventStudyResponse(CamelModel):
    event_date: str
    ar: list[float]
    car: float
    n_days: int
    estimation_std: float
    outliers_removed: int


@app.post("/api/event-study", response_model_by_alias=True)
def run_event_study(req: EventStudyRequest) -> EventStudyResponse:
    """Рассчитывает AR и CAR для одного события."""
    stock_log_returns = _stocks.get_log_returns(req.ticker)
    market = _market.load_market_index_log_returns()
    rf = _market.load_daily_risk_free_rate()

    study = EventStudy(stock_log_returns=stock_log_returns)
    result = study.analyze(
        event_date=date.fromisoformat(req.event_date),
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market,
        rf=rf,
        outlier_threshold=req.outlier_threshold,
    )

    if result is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Недостаточно данных для анализа (слишком ранняя дата или короткая история котировок)",
        )

    return EventStudyResponse(
        event_date=result.event_date.isoformat(),
        ar=result.ar,
        car=result.car,
        n_days=result.n_days,
        estimation_std=result.estimation_std,
        outliers_removed=result.outliers_removed,
    )


# ── Агрегированный event study ──────────────────────────────────────────────

class AggregateStudyRequest(CamelModel):
    ticker: str
    model: str
    event_window: tuple[int, int]
    estimation_window: int
    outlier_threshold: float | None = None


class AggregateStudyResponse(CamelModel):
    n_events: int
    mean_car: list[float]
    cumulative_mean_car: float
    t_stat: float
    p_value: float
    individual_cars: list[float]
    event_dates: list[str]


@app.post("/api/event-study/aggregate", response_model_by_alias=True)
def run_aggregate_study(req: AggregateStudyRequest) -> AggregateStudyResponse:
    """Агрегированный event study: средний CAR по всем событиям тикера."""
    stock_log_returns = _stocks.get_log_returns(req.ticker)
    market = _market.load_market_index_log_returns()
    rf = _market.load_daily_risk_free_rate()

    events = _dividends.load_dividends()
    event_dates = [e.event_date for e in events if e.ticker == req.ticker.upper()]

    study = EventStudy(stock_log_returns=stock_log_returns)
    result = study.analyze_aggregate(
        event_dates=event_dates,
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market,
        rf=rf,
        outlier_threshold=req.outlier_threshold,
    )

    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Не удалось проанализировать ни одно событие")

    return AggregateStudyResponse(
        n_events=result.n_events,
        mean_car=result.mean_car,
        cumulative_mean_car=result.cumulative_mean_car,
        t_stat=result.t_stat,
        p_value=result.p_value,
        individual_cars=result.individual_cars,
        event_dates=result.event_dates,
    )


# ── Поиск аномалий ─────────────────────────────────────────────────────────

class AnomalyRequest(CamelModel):
    ticker: str
    model: str
    event_window: tuple[int, int]
    estimation_window: int
    outlier_threshold: float | None = None


class AnomalyFlagOut(CamelModel):
    code: str
    label: str
    severity: float
    detail: str


class AnomalyResultOut(CamelModel):
    event_date: str
    ticker: str
    flags: list[AnomalyFlagOut]
    car_pct: float
    vol_ratio: float
    volume_ratio: float
    anomaly_score: float


@app.post("/api/anomalies", response_model_by_alias=True)
def find_anomalies(req: AnomalyRequest) -> list[AnomalyResultOut]:
    """Батч-проверка всех событий тикера на аномалии."""
    stock_log_returns = _stocks.get_log_returns(req.ticker)
    market = _market.load_market_index_log_returns()
    rf = _market.load_daily_risk_free_rate()
    candles_df = _stocks.get_candles(req.ticker, normalized=True)

    events = _dividends.load_dividends()
    event_dates = [e.event_date for e in events if e.ticker == req.ticker.upper()]

    study = EventStudy(stock_log_returns=stock_log_returns)
    results = detect_anomalies_batch(
        ticker=req.ticker,
        event_dates=event_dates,
        candles=candles_df,
        study=study,
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market,
        rf=rf,
        outlier_threshold=req.outlier_threshold,
    )

    return [
        AnomalyResultOut(
            event_date=r.event_date,
            ticker=r.ticker,
            flags=[AnomalyFlagOut(code=f.code, label=f.label, severity=f.severity, detail=f.detail) for f in r.flags],
            car_pct=r.car_pct,
            vol_ratio=r.vol_ratio,
            volume_ratio=r.volume_ratio,
            anomaly_score=r.anomaly_score,
        )
        for r in results
    ]


# ── Глобальное сканирование аномалий (SSE-стриминг) ─────────────────────────

class AnomalyScanAllRequest(CamelModel):
    model: str
    event_window: tuple[int, int]
    estimation_window: int
    outlier_threshold: float | None = None


def _anomaly_result_to_dict(r) -> dict:
    return AnomalyResultOut(
        event_date=r.event_date,
        ticker=r.ticker,
        flags=[AnomalyFlagOut(code=f.code, label=f.label, severity=f.severity, detail=f.detail) for f in r.flags],
        car_pct=r.car_pct,
        vol_ratio=r.vol_ratio,
        volume_ratio=r.volume_ratio,
        anomaly_score=r.anomaly_score,
    ).model_dump(by_alias=True)


@app.post("/api/anomalies/scan-all")
def scan_all_anomalies(req: AnomalyScanAllRequest):
    """SSE-стриминг: сканирует все тикеры и отдаёт результаты по мере нахождения."""
    import json
    from fastapi.responses import StreamingResponse

    stock_tickers = [t for t in _stocks.list_tickers() if t not in _NON_TICKER_FILES]
    all_events = _dividends.load_dividends()
    market = _market.load_market_index_log_returns()
    rf = _market.load_daily_risk_free_rate()

    def generate():
        for ticker in stock_tickers:
            event_dates = [e.event_date for e in all_events if e.ticker == ticker]
            if not event_dates:
                continue
            try:
                stock_lr = _stocks.get_log_returns(ticker)
                candles_df = _stocks.get_candles(ticker, normalized=True)
                study = EventStudy(stock_log_returns=stock_lr)
                results = detect_anomalies_batch(
                    ticker=ticker,
                    event_dates=event_dates,
                    candles=candles_df,
                    study=study,
                    model=req.model,
                    event_window=req.event_window,
                    estimation_window=req.estimation_window,
                    market=market,
                    rf=rf,
                    outlier_threshold=req.outlier_threshold,
                )
                for r in results:
                    yield f"data: {json.dumps(_anomaly_result_to_dict(r))}\n\n"
            except Exception:
                continue
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Поиск прецедентов (PQL) ─────────────────────────────────────────────────

PRECEDENT_MAX_ROWS = 1000

_precedent_engine: PrecedentEngine | None = None


def _get_precedent_engine():
    """Ленивая инициализация DuckDB-соединения с видимой схемой PQL."""
    global _precedent_engine
    if _precedent_engine is None:
        _precedent_engine = PrecedentEngine(stocks=_stocks, market=_market)
    return _precedent_engine.con


def _to_json_safe(value):
    """Конвертирует значение из DuckDB в JSON-сериализуемое."""
    from datetime import date as _date, datetime as _dt
    from decimal import Decimal
    if value is None:
        return None
    if isinstance(value, _dt):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class PrecedentSearchRequest(CamelModel):
    source: str


class PrecedentColumn(CamelModel):
    name: str
    type: str


class PrecedentSearchStats(CamelModel):
    truncated: bool
    duration_ms: int


class PrecedentSearchResponse(CamelModel):
    columns: list[PrecedentColumn]
    rows: list[list]
    stats: PrecedentSearchStats


@app.post("/api/precedents/search", response_model_by_alias=True)
def search_precedents(req: PrecedentSearchRequest) -> PrecedentSearchResponse:
    """Исполняет PQL-запрос. Жёсткий потолок MAX_ROWS=1000."""
    import time
    import duckdb as duckdb_module
    from fastapi import HTTPException

    con = _get_precedent_engine()
    started_at = time.monotonic()

    try:
        cur = con.execute(req.source)
        description = cur.description or []
        rows = cur.fetchmany(PRECEDENT_MAX_ROWS + 1)
    except duckdb_module.Error as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "line": None, "column": None},
        )

    truncated = len(rows) > PRECEDENT_MAX_ROWS
    if truncated:
        rows = rows[:PRECEDENT_MAX_ROWS]

    duration_ms = int((time.monotonic() - started_at) * 1000)
    columns = [PrecedentColumn(name=col[0], type=str(col[1])) for col in description]
    rows_safe = [[_to_json_safe(v) for v in row] for row in rows]

    return PrecedentSearchResponse(
        columns=columns,
        rows=rows_safe,
        stats=PrecedentSearchStats(truncated=truncated, duration_ms=duration_ms),
    )


# ── Сохранённые прецедентные запросы ────────────────────────────────────────

class PrecedentQueryRecord(CamelModel):
    id: str
    name: str
    source: str
    created_at: str


class PrecedentQuerySaveRequest(CamelModel):
    name: str
    source: str


@app.get("/api/precedents/queries", response_model_by_alias=True)
def list_precedent_queries() -> list[PrecedentQueryRecord]:
    """Список сохранённых прецедентных запросов, отсортированный по дате создания (новые первыми)."""
    con = _get_precedent_engine()
    rows = con.execute("""
        SELECT id, name, source, created_at FROM precedent_queries
        ORDER BY created_at DESC
    """).fetchall()
    return [
        PrecedentQueryRecord(id=r[0], name=r[1], source=r[2], created_at=r[3])
        for r in rows
    ]


@app.post("/api/precedents/queries", response_model_by_alias=True, status_code=201)
def save_precedent_query(req: PrecedentQuerySaveRequest) -> PrecedentQueryRecord:
    """Сохраняет прецедентный запрос. Имя должно быть уникальным."""
    import uuid as _uuid
    from datetime import datetime, timezone
    from fastapi import HTTPException

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    source = req.source
    if not source.strip():
        raise HTTPException(status_code=400, detail="Текст запроса не может быть пустым")

    con = _get_precedent_engine()
    existing = con.execute(
        "SELECT 1 FROM precedent_queries WHERE name = ? LIMIT 1",
        [name],
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Запрос с таким именем уже существует")

    new_id = str(_uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    con.execute(
        "INSERT INTO precedent_queries VALUES (?, ?, ?, ?)",
        [new_id, name, source, created_at],
    )

    return PrecedentQueryRecord(id=new_id, name=name, source=source, created_at=created_at)
