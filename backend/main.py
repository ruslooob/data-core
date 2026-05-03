"""FastAPI backend для data-core."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from datetime import date, datetime, timezone
import uuid as _uuid


class CamelModel(BaseModel):
    """Базовый Pydantic-класс с camelCase-сериализацией для JSON DTO.

    Поля внутри Python-класса остаются snake_case (Python-конвенция),
    а в JSON попадают как camelCase через alias_generator.
    populate_by_name=True позволяет принимать и snake_case, и camelCase на входе.
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

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


# ── Поиск прецедентов (PQL) ─────────────────────────────────────────────────

PRECEDENT_MAX_ROWS = 1000

_precedent_engine: PrecedentEngine | None = None


def _get_precedent_engine():
    """Ленивая инициализация DuckDB-соединения с видимой схемой PQL.

    Возвращает **новый курсор** на каждый вызов: DuckDB-Python не потокобезопасен
    при шаре одного соединения между потоками FastAPI threadpool — concurrent
    execute() приводит к segfault. Курсор изолирует поток и при этом разделяет
    тот же буферный пул и кэш UDF.
    """
    global _precedent_engine
    if _precedent_engine is None:
        _precedent_engine = PrecedentEngine(stocks=_stocks, market=_market)
    return _precedent_engine.con.cursor()


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
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    if name.startswith('★'):
        raise HTTPException(status_code=400, detail="Имена с префиксом ★ зарезервированы за системными рецептами")
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


# ── Бэктест: стратегии, правила, окружения ─────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail='Имя не может быть пустым')
    return name


def _update_with_fk_workaround(
        con,
        parent_table: str,
        parent_id: str,
        column: str,
        new_value,
        child_fk_col: str,
) -> None:
    """Обновление колонки в parent_table в обход ограничения DuckDB.

    DuckDB переписывает любой UPDATE на родительской таблице в DELETE+INSERT
    и падает на FK-проверке от дочерних строк, даже когда меняется только
    скалярная колонка, не PK. Это «Over-Eager Constraint Checking in
    Foreign Keys» из документации DuckDB. Прямой UPDATE валится с
    ConstraintException, как только у записи есть хотя бы одна дочерняя
    ссылка.

    Обход: снять дочерние строки из strategy_rules, обновить колонку у
    родителя, вернуть дочерние строки на место. BEGIN/COMMIT не помогает:
    внутри одной транзакции DuckDB всё равно проверяет FK по
    pre-transaction-снапшоту и падает, как будто строки не удалены.
    Поэтому делаем три отдельных команды в режиме автокоммита.

    Параметры:
        parent_table:  'strategies' или 'rules'.
        parent_id:     id обновляемой записи.
        column:        имя колонки ('name' или 'description'). Не пользовательский
                       вход, прямой interpolation в SQL безопасен.
        new_value:     новое значение колонки.
        child_fk_col:  колонка в strategy_rules, ссылающаяся на parent_table.
                       'strategy_id' для strategies, 'rule_id' для rules.
    """
    backup = con.execute(
        f'SELECT strategy_id, rule_id, position FROM strategy_rules '
        f'WHERE {child_fk_col} = ?',
        [parent_id],
    ).fetchall()
    con.execute(
        f'DELETE FROM strategy_rules WHERE {child_fk_col} = ?', [parent_id],
    )
    try:
        con.execute(
            f'UPDATE {parent_table} SET {column} = ? WHERE id = ?',
            [new_value, parent_id],
        )
    except Exception:
        for s_id, r_id, position in backup:
            con.execute(
                'INSERT INTO strategy_rules VALUES (?, ?, ?)',
                [s_id, r_id, position],
            )
        raise
    for s_id, r_id, position in backup:
        con.execute(
            'INSERT INTO strategy_rules VALUES (?, ?, ?)',
            [s_id, r_id, position],
        )


def _rename_with_fk_workaround(con, parent_table, parent_id, new_name, child_fk_col):
    """Совместимая обёртка над `_update_with_fk_workaround` для кейса rename."""
    _update_with_fk_workaround(con, parent_table, parent_id, 'name', new_name, child_fk_col)


# ---- Rule ----

class RuleOut(CamelModel):
    id: str
    name: str
    trigger_sql: str
    action_type: str
    action_quantity_sql: str
    priority: int
    created_at: str
    description: str | None = None


class RuleCreate(CamelModel):
    name: str
    trigger_sql: str
    action_type: str
    action_quantity_sql: str
    priority: int
    description: str | None = None


class RenameRequest(CamelModel):
    name: str


class DescriptionRequest(CamelModel):
    description: str | None = None


def _row_to_rule(row) -> RuleOut:
    return RuleOut(
        id=row[0], name=row[1], trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7] if len(row) > 7 else None,
    )


@app.get('/api/rules', response_model_by_alias=True)
def list_rules() -> list[RuleOut]:
    con = _get_precedent_engine()
    rows = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description
        FROM rules ORDER BY created_at DESC
    """).fetchall()
    return [_row_to_rule(r) for r in rows]


@app.post('/api/rules', response_model_by_alias=True, status_code=201)
def create_rule(req: RuleCreate) -> RuleOut:
    name = _validate_name(req.name)
    if req.action_type not in ('buy', 'sell'):
        raise HTTPException(status_code=400, detail="action_type должен быть 'buy' или 'sell'")
    if not req.trigger_sql.strip():
        raise HTTPException(status_code=400, detail='trigger_sql не может быть пустым')
    if not req.action_quantity_sql.strip():
        raise HTTPException(status_code=400, detail='action_quantity_sql не может быть пустым')

    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM rules WHERE name = ? LIMIT 1', [name]).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Правило с именем "{name}" уже существует')

    rule_id = str(_uuid.uuid4())
    created_at = _now_iso()
    con.execute(
        'INSERT INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [rule_id, name, req.trigger_sql, req.action_type, req.action_quantity_sql,
         req.priority, created_at, req.description],
    )
    return RuleOut(
        id=rule_id, name=name, trigger_sql=req.trigger_sql, action_type=req.action_type,
        action_quantity_sql=req.action_quantity_sql, priority=req.priority,
        created_at=created_at, description=req.description,
    )


@app.patch('/api/rules/{rule_id}/description', response_model_by_alias=True)
def update_rule_description(rule_id: str, req: DescriptionRequest) -> RuleOut:
    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM rules WHERE id = ? LIMIT 1', [rule_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    _update_with_fk_workaround(con, 'rules', rule_id, 'description', req.description, 'rule_id')
    row = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description FROM rules WHERE id = ?
    """, [rule_id]).fetchone()
    return _row_to_rule(row)


@app.patch('/api/rules/{rule_id}', response_model_by_alias=True)
def rename_rule(rule_id: str, req: RenameRequest) -> RuleOut:
    name = _validate_name(req.name)
    con = _get_precedent_engine()
    row = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description
        FROM rules WHERE id = ?
    """, [rule_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    dup = con.execute('SELECT 1 FROM rules WHERE name = ? AND id <> ? LIMIT 1', [name, rule_id]).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Правило с именем "{name}" уже существует')
    _rename_with_fk_workaround(con, 'rules', rule_id, name, 'rule_id')
    return RuleOut(
        id=row[0], name=name, trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7],
    )


@app.delete('/api/rules/{rule_id}', status_code=204)
def delete_rule(rule_id: str) -> None:
    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM rules WHERE id = ? LIMIT 1', [rule_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    refs = con.execute("""
        SELECT s.name FROM strategy_rules sr
        JOIN strategies s ON s.id = sr.strategy_id
        WHERE sr.rule_id = ?
    """, [rule_id]).fetchall()
    if refs:
        names = ', '.join(f'"{r[0]}"' for r in refs)
        raise HTTPException(
            status_code=409,
            detail=f'Правило используется в стратегиях: {names}. Сначала удалите эти стратегии.',
        )
    con.execute('DELETE FROM rules WHERE id = ?', [rule_id])


# ---- Strategy ----

class StrategyOut(CamelModel):
    id: str
    name: str
    rule_ids: list[str]
    created_at: str
    description: str | None = None


class StrategyCreate(CamelModel):
    name: str
    rule_ids: list[str]
    description: str | None = None


def _strategy_rule_ids(con, strategy_id: str) -> list[str]:
    rows = con.execute(
        'SELECT rule_id FROM strategy_rules WHERE strategy_id = ? ORDER BY position',
        [strategy_id],
    ).fetchall()
    return [r[0] for r in rows]


@app.get('/api/strategies', response_model_by_alias=True)
def list_strategies() -> list[StrategyOut]:
    con = _get_precedent_engine()
    rows = con.execute(
        'SELECT id, name, created_at, description FROM strategies ORDER BY created_at DESC'
    ).fetchall()
    return [
        StrategyOut(
            id=r[0], name=r[1], rule_ids=_strategy_rule_ids(con, r[0]),
            created_at=r[2], description=r[3],
        )
        for r in rows
    ]


@app.patch('/api/strategies/{strategy_id}/description', response_model_by_alias=True)
def update_strategy_description(strategy_id: str, req: DescriptionRequest) -> StrategyOut:
    con = _get_precedent_engine()
    row = con.execute(
        'SELECT id, name, created_at FROM strategies WHERE id = ?', [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    _update_with_fk_workaround(con, 'strategies', strategy_id, 'description', req.description, 'strategy_id')
    return StrategyOut(
        id=row[0], name=row[1],
        rule_ids=_strategy_rule_ids(con, row[0]),
        created_at=row[2], description=req.description,
    )


@app.post('/api/strategies', response_model_by_alias=True, status_code=201)
def create_strategy(req: StrategyCreate) -> StrategyOut:
    name = _validate_name(req.name)
    if not req.rule_ids:
        raise HTTPException(status_code=400, detail='Стратегия должна содержать минимум одно правило')
    if len(set(req.rule_ids)) != len(req.rule_ids):
        raise HTTPException(status_code=400, detail='Правила в стратегии должны быть уникальными')

    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM strategies WHERE name = ? LIMIT 1', [name]).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Стратегия с именем "{name}" уже существует')

    placeholders = ','.join(['?'] * len(req.rule_ids))
    found = con.execute(
        f'SELECT id FROM rules WHERE id IN ({placeholders})', list(req.rule_ids),
    ).fetchall()
    found_ids = {r[0] for r in found}
    missing = [rid for rid in req.rule_ids if rid not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f'Правила не найдены: {", ".join(missing)}')

    strategy_id = str(_uuid.uuid4())
    created_at = _now_iso()
    con.execute(
        'INSERT INTO strategies VALUES (?, ?, ?, ?)',
        [strategy_id, name, created_at, req.description],
    )
    for position, rule_id in enumerate(req.rule_ids):
        con.execute(
            'INSERT INTO strategy_rules VALUES (?, ?, ?)',
            [strategy_id, rule_id, position],
        )
    return StrategyOut(
        id=strategy_id, name=name, rule_ids=list(req.rule_ids),
        created_at=created_at, description=req.description,
    )


@app.patch('/api/strategies/{strategy_id}', response_model_by_alias=True)
def rename_strategy(strategy_id: str, req: RenameRequest) -> StrategyOut:
    name = _validate_name(req.name)
    con = _get_precedent_engine()
    row = con.execute(
        'SELECT id, name, created_at, description FROM strategies WHERE id = ?', [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    dup = con.execute(
        'SELECT 1 FROM strategies WHERE name = ? AND id <> ? LIMIT 1', [name, strategy_id],
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Стратегия с именем "{name}" уже существует')
    _rename_with_fk_workaround(con, 'strategies', strategy_id, name, 'strategy_id')
    return StrategyOut(
        id=row[0], name=name, rule_ids=_strategy_rule_ids(con, row[0]),
        created_at=row[2], description=row[3],
    )


@app.delete('/api/strategies/{strategy_id}', status_code=204)
def delete_strategy(strategy_id: str) -> None:
    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM strategies WHERE id = ? LIMIT 1', [strategy_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    # Каскад: связки strategy_rules + все backtest_results (и их trade_journal),
    # потом сама стратегия. DuckDB не поддерживает ON DELETE CASCADE на FK,
    # поэтому чистим в коде в правильном порядке.
    con.execute("""
        DELETE FROM trade_journal
        WHERE backtest_result_id IN (
            SELECT id FROM backtest_results WHERE strategy_id = ?
        )
    """, [strategy_id])
    con.execute('DELETE FROM backtest_results WHERE strategy_id = ?', [strategy_id])
    con.execute('DELETE FROM strategy_rules WHERE strategy_id = ?', [strategy_id])
    con.execute('DELETE FROM strategies WHERE id = ?', [strategy_id])


# ---- Environment ----

class EnvironmentOut(CamelModel):
    id: str
    name: str
    date_start: str
    date_end: str
    starting_capital: float
    created_at: str
    description: str | None = None


class EnvironmentCreate(CamelModel):
    name: str
    date_start: str
    date_end: str
    starting_capital: float
    description: str | None = None


def _row_to_env(row) -> EnvironmentOut:
    return EnvironmentOut(
        id=row[0], name=row[1],
        date_start=row[2].isoformat() if hasattr(row[2], 'isoformat') else str(row[2]),
        date_end=row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]),
        starting_capital=float(row[4]), created_at=row[5],
        description=row[6] if len(row) > 6 else None,
    )


@app.get('/api/environments', response_model_by_alias=True)
def list_environments() -> list[EnvironmentOut]:
    con = _get_precedent_engine()
    rows = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description
        FROM environments ORDER BY created_at DESC
    """).fetchall()
    return [_row_to_env(r) for r in rows]


@app.patch('/api/environments/{env_id}/description', response_model_by_alias=True)
def update_environment_description(env_id: str, req: DescriptionRequest) -> EnvironmentOut:
    con = _get_precedent_engine()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description
        FROM environments WHERE id = ?
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    # У environments нет дочерних строк в strategy_rules, FK-проблема DuckDB
    # к нему не относится — обычный UPDATE работает.
    con.execute('UPDATE environments SET description = ? WHERE id = ?', [req.description, env_id])
    return _row_to_env((row[0], row[1], row[2], row[3], row[4], row[5], req.description))


@app.post('/api/environments', response_model_by_alias=True, status_code=201)
def create_environment(req: EnvironmentCreate) -> EnvironmentOut:
    name = _validate_name(req.name)
    try:
        ds = date.fromisoformat(req.date_start)
        de = date.fromisoformat(req.date_end)
    except ValueError:
        raise HTTPException(status_code=400, detail='Даты должны быть в формате YYYY-MM-DD')
    if ds > de:
        raise HTTPException(status_code=400, detail='date_start должен быть не позже date_end')
    if req.starting_capital <= 0:
        raise HTTPException(status_code=400, detail='starting_capital должен быть положительным')

    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM environments WHERE name = ? LIMIT 1', [name]).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')

    env_id = str(_uuid.uuid4())
    created_at = _now_iso()
    con.execute(
        'INSERT INTO environments VALUES (?, ?, ?, ?, ?, ?, ?)',
        [env_id, name, ds, de, req.starting_capital, created_at, req.description],
    )
    return EnvironmentOut(
        id=env_id, name=name, date_start=ds.isoformat(), date_end=de.isoformat(),
        starting_capital=req.starting_capital, created_at=created_at,
        description=req.description,
    )


@app.patch('/api/environments/{env_id}', response_model_by_alias=True)
def rename_environment(env_id: str, req: RenameRequest) -> EnvironmentOut:
    name = _validate_name(req.name)
    con = _get_precedent_engine()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description
        FROM environments WHERE id = ?
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    dup = con.execute(
        'SELECT 1 FROM environments WHERE name = ? AND id <> ? LIMIT 1', [name, env_id],
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')
    con.execute('UPDATE environments SET name = ? WHERE id = ?', [name, env_id])
    return _row_to_env((row[0], name, row[2], row[3], row[4], row[5], row[6]))


@app.delete('/api/environments/{env_id}', status_code=204)
def delete_environment(env_id: str) -> None:
    con = _get_precedent_engine()
    if con.execute('SELECT 1 FROM environments WHERE id = ? LIMIT 1', [env_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    refs = con.execute(
        'SELECT COUNT(*) FROM backtest_results WHERE environment_id = ?', [env_id],
    ).fetchone()[0]
    if refs > 0:
        raise HTTPException(
            status_code=409,
            detail=f'Окружение использовано в {refs} прогонах. Сначала удалите эти прогоны.',
        )
    con.execute('DELETE FROM environments WHERE id = ?', [env_id])


# ── Бэктест: запуск прогона и результаты ───────────────────────────────────

class BacktestRunRequest(CamelModel):
    strategy_id: str
    environment_id: str


class TradeRecordOut(CamelModel):
    trade_date: str
    ticker: str
    type: str
    quantity: int
    price: float
    rule_name: str
    pnl_realized: float | None


class BacktestResultOut(CamelModel):
    id: str
    strategy_id: str
    environment_id: str
    created_at: str
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    n_trades: int
    profit_factor: float | None
    win_rate_pct: float | None


class BacktestResultDetailOut(BacktestResultOut):
    trades: list[TradeRecordOut]
    equity_curve: list[dict]  # [{ date, equity }]
    strategy: StrategyOut | None = None
    environment: EnvironmentOut | None = None


class BacktestRunStartedOut(CamelModel):
    run_id: str
    status: str  # 'running'


class BacktestProgressOut(CamelModel):
    run_id: str
    strategy_id: str
    environment_id: str
    status: str  # 'running' | 'done' | 'error' | 'cancelled'
    progress: float  # 0..1
    current_date: str | None
    current_equity: float | None
    n_trades_so_far: int
    done: bool
    result_id: str | None  # появляется при status='done'
    error_message: str | None


# Singleton runner. Создаём лениво при первом обращении (после загрузки всех модулей).
_backtest_runner = None


def _persist_result_callback(result):
    from core.backtest_engine import persist_backtest_result
    return persist_backtest_result(_get_precedent_engine(), result)


def _get_backtest_runner():
    global _backtest_runner
    if _backtest_runner is None:
        from core.backtest_runner import BacktestRunner
        _backtest_runner = BacktestRunner(persist_callback=_persist_result_callback)
    return _backtest_runner


@app.post('/api/backtest/run', response_model_by_alias=True, status_code=202)
def run_backtest(req: BacktestRunRequest) -> BacktestRunStartedOut:
    """Запускает прогон в дочернем процессе. Возвращает сразу — без ожидания.
    Прогресс читается через GET /api/backtest/runs/{run_id}/progress."""
    from core.backtest_engine import load_environment_spec, load_strategy_spec

    con = _get_precedent_engine()
    try:
        strategy = load_strategy_spec(con, req.strategy_id)
        environment = load_environment_spec(con, req.environment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = _get_backtest_runner()
    run_id = runner.start_run(strategy, environment)
    return BacktestRunStartedOut(run_id=run_id, status='running')


@app.get('/api/backtest/runs/{run_id}/progress', response_model_by_alias=True)
def get_run_progress(run_id: str) -> BacktestProgressOut:
    runner = _get_backtest_runner()
    p = runner.get_progress(run_id)
    if p is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    return BacktestProgressOut(**p)


@app.post('/api/backtest/runs/{run_id}/cancel', status_code=204)
def cancel_run(run_id: str) -> None:
    runner = _get_backtest_runner()
    if not runner.cancel(run_id):
        raise HTTPException(
            status_code=404,
            detail='Прогон не найден или уже завершён',
        )


@app.get('/api/backtest/runs/{run_id}/log')
def get_run_log(run_id: str, after_byte: int = 0) -> dict:
    """Возвращает хвост лог-файла прогона начиная с байта `after_byte`.
    Драфт 6.4: используется виджетом для live-tail во время прогона
    и для просмотра целиком после завершения."""
    from core.backtest_logger import log_path_for
    path = log_path_for(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail='Лог-файл не найден')
    with open(path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        if after_byte >= size:
            return {'content': '', 'next_byte': size}
        f.seek(after_byte)
        chunk = f.read()
    try:
        text = chunk.decode('utf-8')
    except UnicodeDecodeError:
        text = chunk.decode('utf-8', errors='replace')
    return {'content': text, 'next_byte': size}


@app.get('/api/backtest/results', response_model_by_alias=True)
def list_backtest_results() -> list[BacktestResultOut]:
    con = _get_precedent_engine()
    rows = con.execute("""
        SELECT id, strategy_id, environment_id, created_at,
               total_return_pct, annual_return_pct, max_drawdown_pct, sharpe,
               n_trades, profit_factor, win_rate_pct
        FROM backtest_results ORDER BY created_at DESC
    """).fetchall()
    return [
        BacktestResultOut(
            id=r[0], strategy_id=r[1], environment_id=r[2], created_at=r[3],
            total_return_pct=float(r[4]), annual_return_pct=float(r[5]),
            max_drawdown_pct=float(r[6]), sharpe=float(r[7]),
            n_trades=int(r[8]),
            profit_factor=float(r[9]) if r[9] is not None else None,
            win_rate_pct=float(r[10]) if r[10] is not None else None,
        )
        for r in rows
    ]


@app.get('/api/backtest/results/{result_id}', response_model_by_alias=True)
def get_backtest_result(result_id: str) -> BacktestResultDetailOut:
    con = _get_precedent_engine()
    row = con.execute("""
        SELECT id, strategy_id, environment_id, created_at,
               total_return_pct, annual_return_pct, max_drawdown_pct, sharpe,
               n_trades, profit_factor, win_rate_pct
        FROM backtest_results WHERE id = ?
    """, [result_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')

    trade_rows = con.execute("""
        SELECT trade_date, ticker, type, quantity, price, rule_name, pnl_realized
        FROM trade_journal WHERE backtest_result_id = ?
        ORDER BY trade_date, rowid
    """, [result_id]).fetchall()
    trades = [
        TradeRecordOut(
            trade_date=t[0].isoformat() if hasattr(t[0], 'isoformat') else str(t[0]),
            ticker=t[1], type=t[2], quantity=int(t[3]), price=float(t[4]),
            rule_name=t[5],
            pnl_realized=float(t[6]) if t[6] is not None else None,
        )
        for t in trade_rows
    ]

    from core.backtest_engine import reconstruct_equity_curve
    curve = reconstruct_equity_curve(con, result_id)
    equity_curve: list[dict] = [
        {
            'date': d.isoformat() if hasattr(d, 'isoformat') else str(d),
            'equity': float(eq),
        }
        for d, eq in curve
    ]

    # Подгружаем имя стратегии и окружения, чтобы UI показывал контекст
    # прогона без отдельных запросов.
    strategy_row = con.execute(
        'SELECT id, name, created_at, description FROM strategies WHERE id = ?',
        [row[1]],
    ).fetchone()
    strategy_out = None
    if strategy_row is not None:
        strategy_out = StrategyOut(
            id=strategy_row[0], name=strategy_row[1],
            rule_ids=_strategy_rule_ids(con, strategy_row[0]),
            created_at=strategy_row[2], description=strategy_row[3],
        )
    env_row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description
        FROM environments WHERE id = ?
    """, [row[2]]).fetchone()
    env_out = _row_to_env(env_row) if env_row is not None else None

    return BacktestResultDetailOut(
        id=row[0], strategy_id=row[1], environment_id=row[2], created_at=row[3],
        total_return_pct=float(row[4]), annual_return_pct=float(row[5]),
        max_drawdown_pct=float(row[6]), sharpe=float(row[7]),
        n_trades=int(row[8]),
        profit_factor=float(row[9]) if row[9] is not None else None,
        win_rate_pct=float(row[10]) if row[10] is not None else None,
        trades=trades,
        equity_curve=equity_curve,
        strategy=strategy_out,
        environment=env_out,
    )


@app.delete('/api/backtest/results/{result_id}', status_code=204)
def delete_backtest_result(result_id: str) -> None:
    con = _get_precedent_engine()
    if con.execute(
        'SELECT 1 FROM backtest_results WHERE id = ? LIMIT 1', [result_id],
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    # FK trade_journal → backtest_results. Сначала чистим детей, потом родителя.
    con.execute('DELETE FROM trade_journal WHERE backtest_result_id = ?', [result_id])
    con.execute('DELETE FROM backtest_results WHERE id = ?', [result_id])
    # Лог-файл хранится по run_id, который у нас сейчас не сохраняется в
    # persistent (RunHandle живёт в памяти). Здесь чистить нечего, но если
    # поле появится — добавить unlink. Для текущего MVP лог-файлы остаются
    # в data/logs/backtest/ и убираются вручную.
