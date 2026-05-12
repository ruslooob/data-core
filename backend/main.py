"""FastAPI backend для data-core."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from datetime import date, datetime, timezone
import uuid as _uuid

from core.postgres_db import get_pool
from routers import (
    environments as environments_router,
    event_study as event_study_router,
    market as market_router,
    precedents as precedents_router,
    research as research_router,
    rules as rules_router,
    strategies as strategies_router,
)
from routers.environments import row_to_env as _row_to_env
from routers.strategies import strategy_rule_ids as _strategy_rule_ids
from routers._common import (
    DEFAULT_RESEARCH_ID,
    dividends as _dividends,
    fetch_research as _fetch_research,
    get_pg as _pg,
    market as _market,
    now_iso as _now_iso,
    pg_type_name as _pg_type_name,
    stocks as _stocks,
    to_json_safe as _to_json_safe,
    validate_name as _validate_name,
)
from schemas._common import (
    CamelModel,
    DescriptionRequest,
    RenameRequest,
    ResearchScopeRequest,
)
from schemas.environments import EnvironmentOut
from schemas.rules import RuleOut
from schemas.strategies import StrategyOut

app = FastAPI(title="data-core API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router.router)
app.include_router(event_study_router.router)
app.include_router(precedents_router.router)
app.include_router(research_router.router)
app.include_router(rules_router.router)
app.include_router(strategies_router.router)
app.include_router(environments_router.router)


# ── Бэктест: стратегии, правила, окружения ─────────────────────────────────


# ── Бэктест: запуск прогона и результаты ───────────────────────────────────

class BacktestRunRequest(CamelModel):
    strategy_id: str
    environment_id: str
    research_id: str


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


def _persist_result_callback(result, research_id: str):
    from core.backtest_engine import persist_backtest_result
    return persist_backtest_result(_pg(), result, research_id)


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

    con = _pg()
    if _fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    try:
        strategy = load_strategy_spec(con, req.strategy_id)
        environment = load_environment_spec(con, req.environment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = _get_backtest_runner()
    run_id = runner.start_run(strategy, environment, req.research_id)
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
def list_backtest_results(
        research_id: str = Query(..., alias='researchId'),
) -> list[BacktestResultOut]:
    con = _pg()
    rows = con.execute("""
        SELECT id, strategy_id, environment_id, created_at,
               total_return_pct, annual_return_pct, max_drawdown_pct, sharpe,
               n_trades, profit_factor, win_rate_pct
        FROM backtest_results
        WHERE research_id = %s
        ORDER BY created_at DESC
    """, [research_id]).fetchall()
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
    con = _pg()
    row = con.execute("""
        SELECT id, strategy_id, environment_id, created_at,
               total_return_pct, annual_return_pct, max_drawdown_pct, sharpe,
               n_trades, profit_factor, win_rate_pct
        FROM backtest_results WHERE id = %s
    """, [result_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')

    trade_rows = con.execute("""
        SELECT trade_date, ticker, type, quantity, price, rule_name, pnl_realized
        FROM trade_journal WHERE backtest_result_id = %s
        ORDER BY trade_date, id
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
        'SELECT id, name, created_at, description, research_id FROM strategies WHERE id = %s',
        [row[1]],
    ).fetchone()
    strategy_out = None
    if strategy_row is not None:
        strategy_out = StrategyOut(
            id=strategy_row[0], name=strategy_row[1],
            rule_ids=_strategy_rule_ids(con, strategy_row[0]),
            created_at=strategy_row[2], description=strategy_row[3],
            research_id=strategy_row[4],
        )
    env_row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
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
    con = _pg()
    if con.execute(
        'SELECT 1 FROM backtest_results WHERE id = %s LIMIT 1', [result_id],
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    # FK trade_journal → backtest_results. Сначала чистим детей, потом родителя.
    con.execute('DELETE FROM trade_journal WHERE backtest_result_id = %s', [result_id])
    con.execute('DELETE FROM backtest_results WHERE id = %s', [result_id])
    # Лог-файл хранится по run_id, который у нас сейчас не сохраняется в
    # persistent (RunHandle живёт в памяти). Здесь чистить нечего, но если
    # поле появится — добавить unlink. Для текущего MVP лог-файлы остаются
    # в data/logs/backtest/ и убираются вручную.


@app.post('/api/backtest/results/{result_id}/recompute', response_model_by_alias=True)
def recompute_backtest_result(result_id: str) -> BacktestResultDetailOut:
    """Пересчитывает все 7 метрик прогона из persistent trade_journal +
    актуальных цен/R_f. Применять после изменения формул метрик
    (Sharpe → R_f) или цен в `stock_candles`, когда сделки прежнего
    прогона остаются валидными."""
    con = _pg()
    if con.execute(
        'SELECT 1 FROM backtest_results WHERE id = %s LIMIT 1', [result_id],
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    from core.backtest_engine import recompute_metrics
    recompute_metrics(con, result_id)
    return get_backtest_result(result_id)


# ---- Перевод между общей/приватной (Research scope) ----

def _conflicting_runs_for_strategy(con, strategy_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'WHERE br.strategy_id = %s AND br.research_id <> %s LIMIT 1',
        [strategy_id, new_research_id],
    ).fetchone()


def _conflicting_runs_for_environment(con, env_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'WHERE br.environment_id = %s AND br.research_id <> %s LIMIT 1',
        [env_id, new_research_id],
    ).fetchone()


def _conflicting_runs_for_rule(con, rule_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'JOIN strategy_rules sr ON sr.strategy_id = br.strategy_id '
        'WHERE sr.rule_id = %s AND br.research_id <> %s LIMIT 1',
        [rule_id, new_research_id],
    ).fetchone()


def _validate_research_scope_target(con, new_research_id: str | None) -> None:
    if new_research_id is not None and _fetch_research(con, new_research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')


@app.patch('/api/rules/{rule_id}/research', response_model_by_alias=True)
def update_rule_research(rule_id: str, req: ResearchScopeRequest) -> RuleOut:
    con = _pg()
    row = con.execute(
        'SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority, '
        'created_at, description, research_id FROM rules WHERE id = %s', [rule_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    _validate_research_scope_target(con, req.research_id)
    if _conflicting_runs_for_rule(con, rule_id, req.research_id) is not None:
        raise HTTPException(
            status_code=409,
            detail='Правило используется в прогонах других исследований — нельзя сделать приватным',
        )
    con.execute('UPDATE rules SET research_id = %s WHERE id = %s', [req.research_id, rule_id])
    return RuleOut(
        id=row[0], name=row[1], trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7], research_id=req.research_id,
    )


@app.patch('/api/strategies/{strategy_id}/research', response_model_by_alias=True)
def update_strategy_research(strategy_id: str, req: ResearchScopeRequest) -> StrategyOut:
    con = _pg()
    row = con.execute(
        'SELECT id, name, created_at, description FROM strategies WHERE id = %s',
        [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    _validate_research_scope_target(con, req.research_id)
    if _conflicting_runs_for_strategy(con, strategy_id, req.research_id) is not None:
        raise HTTPException(
            status_code=409,
            detail='Стратегия использовалась в прогонах других исследований — нельзя сделать приватной',
        )
    con.execute(
        'UPDATE strategies SET research_id = %s WHERE id = %s',
        [req.research_id, strategy_id],
    )
    return StrategyOut(
        id=row[0], name=row[1], rule_ids=_strategy_rule_ids(con, row[0]),
        created_at=row[2], description=row[3], research_id=req.research_id,
    )


@app.patch('/api/environments/{env_id}/research', response_model_by_alias=True)
def update_environment_research(env_id: str, req: ResearchScopeRequest) -> EnvironmentOut:
    con = _pg()
    row = con.execute(
        'SELECT id, name, date_start, date_end, starting_capital, created_at, description '
        'FROM environments WHERE id = %s',
        [env_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    _validate_research_scope_target(con, req.research_id)
    if _conflicting_runs_for_environment(con, env_id, req.research_id) is not None:
        raise HTTPException(
            status_code=409,
            detail='Окружение использовалось в прогонах других исследований — нельзя сделать приватным',
        )
    con.execute(
        'UPDATE environments SET research_id = %s WHERE id = %s',
        [req.research_id, env_id],
    )
    return _row_to_env((row[0], row[1], row[2], row[3], row[4], row[5], row[6], req.research_id))
