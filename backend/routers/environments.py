"""CRUD-эндпоинты окружений + перевод между общей/приватной (Research scope)."""
import uuid as _uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from routers._common import (
    fetch_research,
    get_pg,
    now_iso,
    validate_name,
    validate_research_scope_target,
)
from schemas._common import DescriptionRequest, RenameRequest, ResearchScopeRequest
from schemas.environments import EnvironmentCreate, EnvironmentOut

router = APIRouter()


def row_to_env(row) -> EnvironmentOut:
    return EnvironmentOut(
        id=row[0], name=row[1],
        date_start=row[2].isoformat() if hasattr(row[2], 'isoformat') else str(row[2]),
        date_end=row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]),
        starting_capital=float(row[4]), created_at=row[5],
        description=row[6] if len(row) > 6 else None,
        research_id=row[7] if len(row) > 7 else None,
    )


def _conflicting_runs_for_environment(con, env_id: str, new_research_id: str | None):
    if new_research_id is None:
        return None
    return con.execute(
        'SELECT 1 FROM backtest_results br '
        'WHERE br.environment_id = %s AND br.research_id <> %s LIMIT 1',
        [env_id, new_research_id],
    ).fetchone()


@router.get('/api/environments', response_model_by_alias=True)
def list_environments(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[EnvironmentOut]:
    con = get_pg()
    if include_common:
        rows = con.execute("""
            SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
            FROM environments
            WHERE research_id = %s OR research_id IS NULL
            ORDER BY created_at DESC
        """, [research_id]).fetchall()
    else:
        rows = con.execute("""
            SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
            FROM environments
            WHERE research_id = %s
            ORDER BY created_at DESC
        """, [research_id]).fetchall()
    return [row_to_env(r) for r in rows]


@router.patch('/api/environments/{env_id}/description', response_model_by_alias=True)
def update_environment_description(env_id: str, req: DescriptionRequest) -> EnvironmentOut:
    con = get_pg()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    con.execute('UPDATE environments SET description = %s WHERE id = %s', [req.description, env_id])
    return row_to_env((row[0], row[1], row[2], row[3], row[4], row[5], req.description, row[7]))


@router.post('/api/environments', response_model_by_alias=True, status_code=201)
def create_environment(req: EnvironmentCreate) -> EnvironmentOut:
    name = validate_name(req.name)
    try:
        ds = date.fromisoformat(req.date_start)
        de = date.fromisoformat(req.date_end)
    except ValueError:
        raise HTTPException(status_code=400, detail='Даты должны быть в формате YYYY-MM-DD')
    if ds > de:
        raise HTTPException(status_code=400, detail='date_start должен быть не позже date_end')
    if req.starting_capital <= 0:
        raise HTTPException(status_code=400, detail='starting_capital должен быть положительным')

    con = get_pg()
    if req.research_id is not None and fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    if con.execute(
            'SELECT 1 FROM environments WHERE name = %s '
            'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
            [name, req.research_id, req.research_id],
    ).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')

    env_id = str(_uuid.uuid4())
    created_at = now_iso()
    con.execute(
        'INSERT INTO environments '
        '(id, name, date_start, date_end, starting_capital, created_at, description, research_id) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
        [env_id, name, ds, de, req.starting_capital, created_at, req.description, req.research_id],
    )
    return EnvironmentOut(
        id=env_id, name=name, date_start=ds.isoformat(), date_end=de.isoformat(),
        starting_capital=req.starting_capital, created_at=created_at,
        description=req.description, research_id=req.research_id,
    )


@router.patch('/api/environments/{env_id}', response_model_by_alias=True)
def rename_environment(env_id: str, req: RenameRequest) -> EnvironmentOut:
    name = validate_name(req.name)
    con = get_pg()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    current_research_id = row[7]
    dup = con.execute(
        'SELECT 1 FROM environments WHERE name = %s AND id <> %s '
        'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
        [name, env_id, current_research_id, current_research_id],
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')
    con.execute('UPDATE environments SET name = %s WHERE id = %s', [name, env_id])
    return row_to_env((row[0], name, row[2], row[3], row[4], row[5], row[6], row[7]))


@router.delete('/api/environments/{env_id}', status_code=204)
def delete_environment(env_id: str) -> None:
    con = get_pg()
    if con.execute('SELECT 1 FROM environments WHERE id = %s LIMIT 1', [env_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    refs = con.execute(
        'SELECT COUNT(*) FROM backtest_results WHERE environment_id = %s', [env_id],
    ).fetchone()[0]
    if refs > 0:
        raise HTTPException(
            status_code=409,
            detail=f'Окружение использовано в {refs} прогонах. Сначала удалите эти прогоны.',
        )
    con.execute('DELETE FROM environments WHERE id = %s', [env_id])


@router.patch('/api/environments/{env_id}/research', response_model_by_alias=True)
def update_environment_research(env_id: str, req: ResearchScopeRequest) -> EnvironmentOut:
    con = get_pg()
    row = con.execute(
        'SELECT id, name, date_start, date_end, starting_capital, created_at, description '
        'FROM environments WHERE id = %s',
        [env_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    validate_research_scope_target(con, req.research_id)
    if _conflicting_runs_for_environment(con, env_id, req.research_id) is not None:
        raise HTTPException(
            status_code=409,
            detail='Окружение использовалось в прогонах других исследований — нельзя сделать приватным',
        )
    con.execute(
        'UPDATE environments SET research_id = %s WHERE id = %s',
        [req.research_id, env_id],
    )
    return row_to_env((row[0], row[1], row[2], row[3], row[4], row[5], row[6], req.research_id))
