"""FastAPI backend для data-core."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from datetime import date, datetime, timezone
import uuid as _uuid

from core.postgres_db import get_pool
from routers import (
    event_study as event_study_router,
    market as market_router,
    precedents as precedents_router,
)
from routers._common import (
    DEFAULT_RESEARCH_ID,
    dividends as _dividends,
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


# ── Бэктест: стратегии, правила, окружения ─────────────────────────────────

# ---- Research ----


class ResearchOut(CamelModel):
    id: str
    name: str
    description: str | None = None
    conclusion: str | None = None
    created_at: str
    is_default: bool


class ResearchCreate(CamelModel):
    name: str
    description: str | None = None


class ResearchPatch(CamelModel):
    name: str | None = None
    description: str | None = None
    conclusion: str | None = None


def _row_to_research(row) -> ResearchOut:
    rid, name, description, conclusion, created_at = row
    return ResearchOut(
        id=rid, name=name, description=description, conclusion=conclusion,
        created_at=created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
        is_default=(rid == DEFAULT_RESEARCH_ID),
    )


def _fetch_research(con, research_id: str):
    return con.execute(
        'SELECT id, name, description, conclusion, created_at '
        'FROM research WHERE id = %s', [research_id],
    ).fetchone()


@app.get('/api/research', response_model_by_alias=True)
def list_research() -> list[ResearchOut]:
    con = _pg()
    rows = con.execute(
        'SELECT id, name, description, conclusion, created_at '
        'FROM research ORDER BY created_at ASC'
    ).fetchall()
    return [_row_to_research(r) for r in rows]


@app.get('/api/research/{research_id}', response_model_by_alias=True)
def get_research(research_id: str) -> ResearchOut:
    con = _pg()
    row = _fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    return _row_to_research(row)


@app.post('/api/research', response_model_by_alias=True, status_code=201)
def create_research(req: ResearchCreate) -> ResearchOut:
    name = _validate_name(req.name)
    con = _pg()
    if con.execute('SELECT 1 FROM research WHERE name = %s LIMIT 1', [name]).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Исследование с именем "{name}" уже существует')
    rid = str(_uuid.uuid4())
    con.execute(
        'INSERT INTO research (id, name, description) VALUES (%s, %s, %s)',
        [rid, name, req.description],
    )
    return _row_to_research(_fetch_research(con, rid))


@app.patch('/api/research/{research_id}', response_model_by_alias=True)
def update_research(research_id: str, req: ResearchPatch) -> ResearchOut:
    con = _pg()
    row = _fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')

    is_default = research_id == DEFAULT_RESEARCH_ID
    new_name = _validate_name(req.name) if req.name is not None else None
    if new_name is not None and is_default:
        raise HTTPException(status_code=400, detail='Системное исследование Default нельзя переименовывать')

    if new_name is not None and new_name != row[1]:
        dup = con.execute(
            'SELECT 1 FROM research WHERE name = %s AND id <> %s LIMIT 1',
            [new_name, research_id],
        ).fetchone()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f'Исследование с именем "{new_name}" уже существует')

    sets, vals = [], []
    if new_name is not None:
        sets.append('name = %s'); vals.append(new_name)
    if req.description is not None:
        sets.append('description = %s'); vals.append(req.description)
    if req.conclusion is not None:
        sets.append('conclusion = %s'); vals.append(req.conclusion)

    if sets:
        vals.append(research_id)
        con.execute(f'UPDATE research SET {", ".join(sets)} WHERE id = %s', vals)

    return _row_to_research(_fetch_research(con, research_id))


@app.delete('/api/research/{research_id}', status_code=204)
def delete_research(research_id: str) -> None:
    if research_id == DEFAULT_RESEARCH_ID:
        raise HTTPException(status_code=400, detail='Системное исследование Default нельзя удалять')
    con = _pg()
    if _fetch_research(con, research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    con.execute('DELETE FROM research WHERE id = %s', [research_id])


# ── Отчёт по исследованию ─────────────────────────────────────────────────

def _format_research_report(con, research_row) -> str:
    """Собирает markdown-отчёт по одному исследованию."""
    rid, name, description, conclusion, _created_at = research_row
    out: list[str] = [f'# {name}', '']
    if description and description.strip():
        out += ['## Идея исследования', '', description.strip(), '']

    strategies = con.execute(
        'SELECT id, name, created_at, description FROM strategies '
        'WHERE research_id = %s ORDER BY created_at',
        [rid],
    ).fetchall()
    if strategies:
        out += ['## Приватные стратегии', '',
                '| Имя | Правил | Создано | Описание |',
                '|---|---:|---|---|']
        for s in strategies:
            n_rules = con.execute(
                'SELECT COUNT(*) FROM strategy_rules WHERE strategy_id = %s', [s[0]],
            ).fetchone()[0]
            desc = (s[3] or '').replace('|', '\\|').replace('\n', ' ')
            out.append(f'| {s[1]} | {n_rules} | {s[2]} | {desc} |')
        out.append('')

    rules = con.execute(
        'SELECT name, action_type, priority, created_at, description '
        'FROM rules WHERE research_id = %s ORDER BY created_at',
        [rid],
    ).fetchall()
    if rules:
        out += ['## Приватные правила', '',
                '| Имя | Тип | Priority | Создано | Описание |',
                '|---|---|---:|---|---|']
        for r in rules:
            desc = (r[4] or '').replace('|', '\\|').replace('\n', ' ')
            out.append(f'| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {desc} |')
        out.append('')

    envs = con.execute(
        'SELECT name, date_start, date_end, starting_capital, description '
        'FROM environments WHERE research_id = %s ORDER BY created_at',
        [rid],
    ).fetchall()
    if envs:
        out += ['## Приватные окружения', '',
                '| Имя | Период | Капитал | Описание |',
                '|---|---|---:|---|']
        for e in envs:
            desc = (e[4] or '').replace('|', '\\|').replace('\n', ' ')
            out.append(f'| {e[0]} | {e[1]}…{e[2]} | {float(e[3]):,.0f} | {desc} |')
        out.append('')

    runs = con.execute(
        '''
        SELECT br.created_at, br.total_return_pct, br.annual_return_pct,
               br.max_drawdown_pct, br.sharpe, br.n_trades,
               br.profit_factor, br.win_rate_pct,
               s.name, e.name
        FROM backtest_results br
        LEFT JOIN strategies   s ON s.id = br.strategy_id
        LEFT JOIN environments e ON e.id = br.environment_id
        WHERE br.research_id = %s
        ORDER BY br.created_at
        ''',
        [rid],
    ).fetchall()
    if runs:
        out += ['## Прогоны', '',
                '| Стратегия | Окружение | Σ доход., % | Год., % | maxDD, % | Sharpe | PF | Win, % | Сделок | Дата |',
                '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for r in runs:
            sname = (r[8] or '—').replace('|', '\\|')
            ename = (r[9] or '—').replace('|', '\\|')
            pf = '—' if r[6] is None else f'{float(r[6]):.2f}'
            wr = '—' if r[7] is None else f'{float(r[7]):.1f}'
            out.append(
                f'| {sname} | {ename} | '
                f'{float(r[1]):.1f} | {float(r[2]):.2f} | {float(r[3]):.1f} | '
                f'{float(r[4]):.2f} | {pf} | {wr} | {r[5]} | {r[0]} |'
            )
        out.append('')

    if conclusion and conclusion.strip():
        out += ['## Выводы', '', conclusion.strip(), '']

    return '\n'.join(out).rstrip() + '\n'


@app.get('/api/research/{research_id}/report')
def get_research_report(research_id: str):
    from fastapi.responses import PlainTextResponse
    con = _pg()
    row = _fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    text = _format_research_report(con, row)
    return PlainTextResponse(text, media_type='text/markdown; charset=utf-8')


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
    research_id: str | None = None


class RuleCreate(CamelModel):
    name: str
    trigger_sql: str
    action_type: str
    action_quantity_sql: str
    priority: int
    description: str | None = None
    research_id: str | None = None


def _row_to_rule(row) -> RuleOut:
    return RuleOut(
        id=row[0], name=row[1], trigger_sql=row[2], action_type=row[3],
        action_quantity_sql=row[4], priority=row[5], created_at=row[6],
        description=row[7] if len(row) > 7 else None,
        research_id=row[8] if len(row) > 8 else None,
    )


@app.get('/api/rules', response_model_by_alias=True)
def list_rules(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[RuleOut]:
    con = _pg()
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


@app.post('/api/rules', response_model_by_alias=True, status_code=201)
def create_rule(req: RuleCreate) -> RuleOut:
    from core.rule_validator import RuleSqlError, validate_quantity_sql, validate_trigger_sql

    name = _validate_name(req.name)
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

    con = _pg()
    if req.research_id is not None and _fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    if con.execute(
            'SELECT 1 FROM rules WHERE name = %s '
            'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
            [name, req.research_id, req.research_id],
    ).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Правило с именем "{name}" уже существует')

    rule_id = str(_uuid.uuid4())
    created_at = _now_iso()
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


@app.patch('/api/rules/{rule_id}/description', response_model_by_alias=True)
def update_rule_description(rule_id: str, req: DescriptionRequest) -> RuleOut:
    con = _pg()
    if con.execute('SELECT 1 FROM rules WHERE id = %s LIMIT 1', [rule_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail='Правило не найдено')
    con.execute('UPDATE rules SET description = %s WHERE id = %s', [req.description, rule_id])
    row = con.execute("""
        SELECT id, name, trigger_sql, action_type, action_quantity_sql, priority,
               created_at, description, research_id FROM rules WHERE id = %s
    """, [rule_id]).fetchone()
    return _row_to_rule(row)


@app.patch('/api/rules/{rule_id}', response_model_by_alias=True)
def rename_rule(rule_id: str, req: RenameRequest) -> RuleOut:
    name = _validate_name(req.name)
    con = _pg()
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


@app.delete('/api/rules/{rule_id}', status_code=204)
def delete_rule(rule_id: str) -> None:
    con = _pg()
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


# ---- Strategy ----

class StrategyOut(CamelModel):
    id: str
    name: str
    rule_ids: list[str]
    created_at: str
    description: str | None = None
    research_id: str | None = None


class StrategyCreate(CamelModel):
    name: str
    rule_ids: list[str]
    description: str | None = None
    research_id: str | None = None


def _strategy_rule_ids(con, strategy_id: str) -> list[str]:
    rows = con.execute(
        'SELECT rule_id FROM strategy_rules WHERE strategy_id = %s ORDER BY position',
        [strategy_id],
    ).fetchall()
    return [r[0] for r in rows]


@app.get('/api/strategies', response_model_by_alias=True)
def list_strategies(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[StrategyOut]:
    con = _pg()
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
            id=r[0], name=r[1], rule_ids=_strategy_rule_ids(con, r[0]),
            created_at=r[2], description=r[3], research_id=r[4],
        )
        for r in rows
    ]


@app.patch('/api/strategies/{strategy_id}/description', response_model_by_alias=True)
def update_strategy_description(strategy_id: str, req: DescriptionRequest) -> StrategyOut:
    con = _pg()
    row = con.execute(
        'SELECT id, name, created_at, research_id FROM strategies WHERE id = %s', [strategy_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Стратегия не найдена')
    con.execute('UPDATE strategies SET description = %s WHERE id = %s', [req.description, strategy_id])
    return StrategyOut(
        id=row[0], name=row[1],
        rule_ids=_strategy_rule_ids(con, row[0]),
        created_at=row[2], description=req.description, research_id=row[3],
    )


@app.post('/api/strategies', response_model_by_alias=True, status_code=201)
def create_strategy(req: StrategyCreate) -> StrategyOut:
    name = _validate_name(req.name)
    if not req.rule_ids:
        raise HTTPException(status_code=400, detail='Стратегия должна содержать минимум одно правило')
    if len(set(req.rule_ids)) != len(req.rule_ids):
        raise HTTPException(status_code=400, detail='Правила в стратегии должны быть уникальными')

    con = _pg()
    if req.research_id is not None and _fetch_research(con, req.research_id) is None:
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
    created_at = _now_iso()
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


@app.patch('/api/strategies/{strategy_id}', response_model_by_alias=True)
def rename_strategy(strategy_id: str, req: RenameRequest) -> StrategyOut:
    name = _validate_name(req.name)
    con = _pg()
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
        id=row[0], name=name, rule_ids=_strategy_rule_ids(con, row[0]),
        created_at=row[2], description=row[3], research_id=row[4],
    )


@app.delete('/api/strategies/{strategy_id}', status_code=204)
def delete_strategy(strategy_id: str) -> None:
    con = _pg()
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


# ---- Environment ----

class EnvironmentOut(CamelModel):
    id: str
    name: str
    date_start: str
    date_end: str
    starting_capital: float
    created_at: str
    description: str | None = None
    research_id: str | None = None


class EnvironmentCreate(CamelModel):
    name: str
    date_start: str
    date_end: str
    starting_capital: float
    description: str | None = None
    research_id: str | None = None


def _row_to_env(row) -> EnvironmentOut:
    return EnvironmentOut(
        id=row[0], name=row[1],
        date_start=row[2].isoformat() if hasattr(row[2], 'isoformat') else str(row[2]),
        date_end=row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]),
        starting_capital=float(row[4]), created_at=row[5],
        description=row[6] if len(row) > 6 else None,
        research_id=row[7] if len(row) > 7 else None,
    )


@app.get('/api/environments', response_model_by_alias=True)
def list_environments(
        research_id: str = Query(..., alias='researchId'),
        include_common: bool = Query(False, alias='includeCommon'),
) -> list[EnvironmentOut]:
    con = _pg()
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
    return [_row_to_env(r) for r in rows]


@app.patch('/api/environments/{env_id}/description', response_model_by_alias=True)
def update_environment_description(env_id: str, req: DescriptionRequest) -> EnvironmentOut:
    con = _pg()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    # У environments нет дочерних строк в strategy_rules, FK-проблема DuckDB
    # к нему не относится — обычный UPDATE работает.
    con.execute('UPDATE environments SET description = %s WHERE id = %s', [req.description, env_id])
    return _row_to_env((row[0], row[1], row[2], row[3], row[4], row[5], req.description, row[7]))


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

    con = _pg()
    if req.research_id is not None and _fetch_research(con, req.research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    if con.execute(
            'SELECT 1 FROM environments WHERE name = %s '
            'AND (research_id = %s OR (research_id IS NULL AND %s::text IS NULL)) LIMIT 1',
            [name, req.research_id, req.research_id],
    ).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')

    env_id = str(_uuid.uuid4())
    created_at = _now_iso()
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


@app.patch('/api/environments/{env_id}', response_model_by_alias=True)
def rename_environment(env_id: str, req: RenameRequest) -> EnvironmentOut:
    name = _validate_name(req.name)
    con = _pg()
    row = con.execute("""
        SELECT id, name, date_start, date_end, starting_capital, created_at, description, research_id
        FROM environments WHERE id = %s
    """, [env_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Окружение не найдено')
    dup = con.execute(
        'SELECT 1 FROM environments WHERE name = %s AND id <> %s LIMIT 1', [name, env_id],
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f'Окружение с именем "{name}" уже существует')
    con.execute('UPDATE environments SET name = %s WHERE id = %s', [name, env_id])
    return _row_to_env((row[0], name, row[2], row[3], row[4], row[5], row[6], row[7]))


@app.delete('/api/environments/{env_id}', status_code=204)
def delete_environment(env_id: str) -> None:
    con = _pg()
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
