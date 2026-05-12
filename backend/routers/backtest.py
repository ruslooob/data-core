"""Эндпоинты бэктеста: запуск прогона, прогресс, журнал сделок, результаты."""
from fastapi import APIRouter, HTTPException, Query

from routers._common import fetch_research, get_pg
from routers.environments import row_to_env
from routers.strategies import strategy_rule_ids
from schemas.backtest import (
    BacktestProgressOut,
    BacktestResultDetailOut,
    BacktestResultOut,
    BacktestRunRequest,
    BacktestRunStartedOut,
    TradeRecordOut,
)
from schemas.strategies import StrategyOut

router = APIRouter()


# Singleton runner. Создаём лениво при первом обращении (после загрузки всех модулей).
_backtest_runner = None


def _persist_result_callback(result, research_id: str):
    from core.backtest_engine import persist_backtest_result
    return persist_backtest_result(get_pg(), result, research_id)


def _get_backtest_runner():
    global _backtest_runner
    if _backtest_runner is None:
        from core.backtest_runner import BacktestRunner
        _backtest_runner = BacktestRunner(persist_callback=_persist_result_callback)
    return _backtest_runner


@router.post('/api/backtest/run', response_model_by_alias=True, status_code=202)
def run_backtest(req: BacktestRunRequest) -> BacktestRunStartedOut:
    """Запускает прогон в дочернем процессе. Возвращает сразу — без ожидания.
    Прогресс читается через GET /api/backtest/runs/{run_id}/progress."""
    from core.backtest_engine import load_environment_spec, load_strategy_spec

    con = get_pg()
    if fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    try:
        strategy = load_strategy_spec(con, req.strategy_id)
        environment = load_environment_spec(con, req.environment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = _get_backtest_runner()
    run_id = runner.start_run(strategy, environment, req.research_id)
    return BacktestRunStartedOut(run_id=run_id, status='running')


@router.get('/api/backtest/runs/{run_id}/progress', response_model_by_alias=True)
def get_run_progress(run_id: str) -> BacktestProgressOut:
    runner = _get_backtest_runner()
    p = runner.get_progress(run_id)
    if p is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    return BacktestProgressOut(**p)


@router.post('/api/backtest/runs/{run_id}/cancel', status_code=204)
def cancel_run(run_id: str) -> None:
    runner = _get_backtest_runner()
    if not runner.cancel(run_id):
        raise HTTPException(
            status_code=404,
            detail='Прогон не найден или уже завершён',
        )


@router.get('/api/backtest/runs/{run_id}/log')
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


@router.get('/api/backtest/results', response_model_by_alias=True)
def list_backtest_results(
        research_id: str = Query(..., alias='researchId'),
) -> list[BacktestResultOut]:
    con = get_pg()
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


@router.get('/api/backtest/results/{result_id}', response_model_by_alias=True)
def get_backtest_result(result_id: str) -> BacktestResultDetailOut:
    con = get_pg()
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
            rule_ids=strategy_rule_ids(con, strategy_row[0]),
            created_at=strategy_row[2], description=strategy_row[3],
            research_id=strategy_row[4],
        )
    env_row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
    """, [row[2]]).fetchone()
    env_out = row_to_env(env_row) if env_row is not None else None

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


@router.delete('/api/backtest/results/{result_id}', status_code=204)
def delete_backtest_result(result_id: str) -> None:
    con = get_pg()
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


@router.post('/api/backtest/results/{result_id}/recompute', response_model_by_alias=True)
def recompute_backtest_result(result_id: str) -> BacktestResultDetailOut:
    """Пересчитывает все метрики прогона из persistent trade_journal."""
    con = get_pg()
    if con.execute(
        'SELECT 1 FROM backtest_results WHERE id = %s LIMIT 1', [result_id],
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail='Прогон не найден')
    from core.backtest_engine import recompute_metrics
    recompute_metrics(con, result_id)
    return get_backtest_result(result_id)
