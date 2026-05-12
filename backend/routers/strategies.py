"""CRUD-эндпоинты стратегий + перевод между общей/приватной (Research scope)."""
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query

from routers._common import (
    fetch_research,
    get_pg,
    now_iso,
    validate_name,
    validate_research_scope_target,
)
from schemas._common import DescriptionRequest, RenameRequest, ResearchScopeRequest
from schemas.strategies import StrategyCreate, StrategyOut

router = APIRouter()


def strategy_rule_ids(con, strategy_id: str) -> list[str]:
    """Возвращает упорядоченный список id правил стратегии. Используется и здесь,
    и роутером backtest для построения BacktestResultDetailOut."""
    rows = con.execute(
        'SELECT rule_id FROM strategy_rules WHERE strategy_id = %s ORDER BY position',
        [strategy_id],
    ).fetchall()
    return [r[0] for r in rows]


def _conflicting_runs_for_strategy(con, strategy_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'WHERE br.strategy_id = %s AND br.research_id <> %s LIMIT 1',
        [strategy_id, new_research_id],
    ).fetchone()


@router.get('/api/strategies', response_model_by_alias=True)
def list_strategies(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[StrategyOut]:
    con = get_pg()
    if include_common:
        rows = con.execute(
            'SELECT id, name, created_at, description, research_id FROM strategies '
            'WHERE research_id = %s OR research_id IS NULL '
            'ORDER BY created_at DESC',
            [research_id],
        ).fetchall()
    else:
        rows = con.execute(
            'SELECT id, name, created_at, description, research_id FROM strategies '
            'WHERE research_id = %s '
            'ORDER BY created_at DESC',
            [research_id],
        ).fetchall()
    return [
        StrategyOut(
            id=r[0], name=r[1], rule_ids=strategy_rule_ids(con, r[0]),
            created_at=r[2], description=r[3], research_id=r[4],
        )
        for r in rows
    ]


@router.patch('/api/strategies/{strategy_id}/description', response_model_by_alias=True)
def update_strategy_description(strategy_id: str, req: DescriptionRequest) -> StrategyOut:
    con = get_pg()
    row = con.execute(
        'SELECT id, name, created_at, research_id FROM strategies WHERE id = %s', [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    con.execute('UPDATE strategies SET description = %s WHERE id = %s', [req.description, strategy_id])
    return StrategyOut(
        id=row[0], name=row[1],
        rule_ids=strategy_rule_ids(con, row[0]),
        created_at=row[2], description=req.description, research_id=row[3],
    )


@router.post('/api/strategies', response_model_by_alias=True, status_code=201)
def create_strategy(req: StrategyCreate) -> StrategyOut:
    name = validate_name(req.name)
    if not req.rule_ids:
        raise HTTPException(status_code=400, detail='Стратегия должна содержать минимум одно правило')
    if len(set(req.rule_ids)) != len(req.rule_ids):
        raise HTTPException(status_code=400, detail='Правила в стратегии должны быть уникальными')

    con = get_pg()
    if req.research_id is not None and fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    if con.execute(
            'SELECT 1 FROM strategies WHERE name = %s '
            'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
            [name, req.research_id, req.research_id],
    ).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Стратегия с именем "{name}" уже существует')

    placeholders = ','.join(['%s'] * len(req.rule_ids))
    found = con.execute(
        f'SELECT id FROM rules WHERE id IN ({placeholders})', list(req.rule_ids),
    ).fetchall()
    found_ids = {r[0] for r in found}
    missing = [rid for rid in req.rule_ids if rid not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f'Правила не найдены: {", ".join(missing)}')

    strategy_id = str(_uuid.uuid4())
    created_at = now_iso()
    con.execute(
        'INSERT INTO strategies (id, name, created_at, description, research_id) '
        'VALUES (%s, %s, %s, %s, %s)',
        [strategy_id, name, created_at, req.description, req.research_id],
    )
    for position, rule_id in enumerate(req.rule_ids):
        con.execute(
            'INSERT INTO strategy_rules VALUES (%s, %s, %s)',
            [strategy_id, rule_id, position],
        )
    return StrategyOut(
        id=strategy_id, name=name, rule_ids=list(req.rule_ids),
        created_at=created_at, description=req.description,
        research_id=req.research_id,
    )


@router.patch('/api/strategies/{strategy_id}', response_model_by_alias=True)
def rename_strategy(strategy_id: str, req: RenameRequest) -> StrategyOut:
    name = validate_name(req.name)
    con = get_pg()
    row = con.execute(
        'SELECT id, name, created_at, description, research_id FROM strategies WHERE id = %s',
        [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    dup = con.execute(
        'SELECT 1 FROM strategies WHERE name = %s AND id <> %s LIMIT 1', [name, strategy_id],
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Стратегия с именем "{name}" уже существует')
    con.execute('UPDATE strategies SET name = %s WHERE id = %s', [name, strategy_id])
    return StrategyOut(
        id=row[0], name=name, rule_ids=strategy_rule_ids(con, row[0]),
        created_at=row[2], description=row[3], research_id=row[4],
    )


@router.delete('/api/strategies/{strategy_id}', status_code=204)
def delete_strategy(strategy_id: str) -> None:
    con = get_pg()
    if con.execute('SELECT 1 FROM strategies WHERE id = %s LIMIT 1', [strategy_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    # Каскад: связки strategy_rules + все backtest_results (и их trade_journal),
    # потом сама стратегия. DuckDB не поддерживает ON DELETE CASCADE на FK,
    # поэтому чистим в коде в правильном порядке.
    con.execute("""
        DELETE FROM trade_journal
        WHERE backtest_result_id IN (
            SELECT id FROM backtest_results WHERE strategy_id = %s
        )
    """, [strategy_id])
    con.execute('DELETE FROM backtest_results WHERE strategy_id = %s', [strategy_id])
    con.execute('DELETE FROM strategy_rules WHERE strategy_id = %s', [strategy_id])
    con.execute('DELETE FROM strategies WHERE id = %s', [strategy_id])


@router.patch('/api/strategies/{strategy_id}/research', response_model_by_alias=True)
def update_strategy_research(strategy_id: str, req: ResearchScopeRequest) -> StrategyOut:
    con = get_pg()
    row = con.execute(
        'SELECT id, name, created_at, description FROM strategies WHERE id = %s',
        [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    validate_research_scope_target(con, req.research_id)
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
        id=row[0], name=row[1], rule_ids=strategy_rule_ids(con, row[0]),
        created_at=row[2], description=row[3], research_id=req.research_id,
    )
