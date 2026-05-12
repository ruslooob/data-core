"""CRUD-эндпоинты правил + перевод между общей/приватной (Research scope)."""
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
from schemas.rules import RuleCreate, RuleOut

router = APIRouter()


def _row_to_rule(row) -> RuleOut:
    return RuleOut(
        id=row[0], name=row[1], trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7] if len(row) > 7 else None,
        research_id=row[8] if len(row) > 8 else None,
    )


def _conflicting_runs_for_rule(con, rule_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'JOIN strategy_rules sr ON sr.strategy_id = br.strategy_id '
        'WHERE sr.rule_id = %s AND br.research_id <> %s LIMIT 1',
        [rule_id, new_research_id],
    ).fetchone()


@router.get('/api/rules', response_model_by_alias=True)
def list_rules(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[RuleOut]:
    con = get_pg()
    if include_common:
        rows = con.execute("""
            SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
                   created_at, description, research_id
            FROM rules
            WHERE research_id = %s OR research_id IS NULL
            ORDER BY created_at DESC
        """, [research_id]).fetchall()
    else:
        rows = con.execute("""
            SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
                   created_at, description, research_id
            FROM rules
            WHERE research_id = %s
            ORDER BY created_at DESC
        """, [research_id]).fetchall()
    return [_row_to_rule(r) for r in rows]


@router.post('/api/rules', response_model_by_alias=True, status_code=201)
def create_rule(req: RuleCreate) -> RuleOut:
    from core.rule_validator import RuleSqlError, validate_quantity_sql, validate_trigger_sql

    name = validate_name(req.name)
    if req.action_type not in ('buy', 'sell'):
        raise HTTPException(status_code=400, detail="action_type должен быть 'buy' или 'sell'")
    if not req.trigger_sql.strip():
        raise HTTPException(status_code=400, detail='trigger_sql не может быть пустым')
    if not req.action_quantity_sql.strip():
        raise HTTPException(status_code=400, detail='action_quantity_sql не может быть пустым')

    try:
        validate_trigger_sql(req.trigger_sql)
        validate_quantity_sql(req.action_quantity_sql)
    except RuleSqlError as e:
        raise HTTPException(status_code=400, detail=str(e))

    con = get_pg()
    if req.research_id is not None and fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    if con.execute(
            'SELECT 1 FROM rules WHERE name = %s '
            'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
            [name, req.research_id, req.research_id],
    ).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Правило с именем "{name}" уже существует')

    rule_id = str(_uuid.uuid4())
    created_at = now_iso()
    con.execute(
        'INSERT INTO rules '
        '(id, name, trigger_sql, action_type, action_quantity_sql, priority, '
        ' created_at, description, research_id) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [rule_id, name, req.trigger_sql, req.action_type, req.action_quantity_sql,
         req.priority, created_at, req.description, req.research_id],
    )
    return RuleOut(
        id=rule_id, name=name, trigger_sql=req.trigger_sql, action_type=req.action_type,
        action_quantity_sql=req.action_quantity_sql, priority=req.priority,
        created_at=created_at, description=req.description,
        research_id=req.research_id,
    )


@router.patch('/api/rules/{rule_id}/description', response_model_by_alias=True)
def update_rule_description(rule_id: str, req: DescriptionRequest) -> RuleOut:
    con = get_pg()
    if con.execute('SELECT 1 FROM rules WHERE id = %s LIMIT 1', [rule_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    con.execute('UPDATE rules SET description = %s WHERE id = %s', [req.description, rule_id])
    row = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description, research_id FROM rules WHERE id = %s
    """, [rule_id]).fetchone()
    return _row_to_rule(row)


@router.patch('/api/rules/{rule_id}', response_model_by_alias=True)
def rename_rule(rule_id: str, req: RenameRequest) -> RuleOut:
    name = validate_name(req.name)
    con = get_pg()
    row = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description, research_id
        FROM rules WHERE id = %s
    """, [rule_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    dup = con.execute('SELECT 1 FROM rules WHERE name = %s AND id <> %s LIMIT 1', [name, rule_id]).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Правило с именем "{name}" уже существует')
    con.execute('UPDATE rules SET name = %s WHERE id = %s', [name, rule_id])
    return RuleOut(
        id=row[0], name=name, trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7], research_id=row[8],
    )


@router.delete('/api/rules/{rule_id}', status_code=204)
def delete_rule(rule_id: str) -> None:
    con = get_pg()
    if con.execute('SELECT 1 FROM rules WHERE id = %s LIMIT 1', [rule_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    refs = con.execute("""
        SELECT s.name FROM strategy_rules sr
        JOIN strategies s ON s.id = sr.strategy_id
        WHERE sr.rule_id = %s
    """, [rule_id]).fetchall()
    if refs:
        names = ', '.join(f'"{r[0]}"' for r in refs)
        raise HTTPException(
            status_code=409,
            detail=f'Правило используется в стратегиях: {names}. Сначала удалите эти стратегии.',
        )
    con.execute('DELETE FROM rules WHERE id = %s', [rule_id])


@router.patch('/api/rules/{rule_id}/research', response_model_by_alias=True)
def update_rule_research(rule_id: str, req: ResearchScopeRequest) -> RuleOut:
    con = get_pg()
    row = con.execute(
        'SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority, '
        'created_at, description, research_id FROM rules WHERE id = %s', [rule_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    validate_research_scope_target(con, req.research_id)
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
