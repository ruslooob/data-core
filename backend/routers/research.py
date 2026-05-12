"""CRUD-эндпоинты исследований + markdown-отчёт."""
import uuid as _uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from routers._common import DEFAULT_RESEARCH_ID, fetch_research, get_pg, validate_name
from schemas.research import ResearchCreate, ResearchOut, ResearchPatch

router = APIRouter()


def _row_to_research(row) -> ResearchOut:
    rid, name, description, conclusion, created_at = row
    return ResearchOut(
        id=rid, name=name, description=description, conclusion=conclusion,
        created_at=created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
        is_default=(rid == DEFAULT_RESEARCH_ID),
    )


@router.get('/api/research', response_model_by_alias=True)
def list_research() -> list[ResearchOut]:
    con = get_pg()
    rows = con.execute(
        'SELECT id, name, description, conclusion, created_at '
        'FROM research ORDER BY created_at ASC'
    ).fetchall()
    return [_row_to_research(r) for r in rows]


@router.get('/api/research/{research_id}', response_model_by_alias=True)
def get_research(research_id: str) -> ResearchOut:
    con = get_pg()
    row = fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    return _row_to_research(row)


@router.post('/api/research', response_model_by_alias=True, status_code=201)
def create_research(req: ResearchCreate) -> ResearchOut:
    name = validate_name(req.name)
    con = get_pg()
    if con.execute('SELECT 1 FROM research WHERE name = %s LIMIT 1', [name]).fetchone() is not None:
        raise HTTPException(status_code=409, detail=f'Исследование с именем "{name}" уже существует')
    rid = str(_uuid.uuid4())
    con.execute(
        'INSERT INTO research (id, name, description) VALUES (%s, %s, %s)',
        [rid, name, req.description],
    )
    return _row_to_research(fetch_research(con, rid))


@router.patch('/api/research/{research_id}', response_model_by_alias=True)
def update_research(research_id: str, req: ResearchPatch) -> ResearchOut:
    con = get_pg()
    row = fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')

    is_default = research_id == DEFAULT_RESEARCH_ID
    new_name = validate_name(req.name) if req.name is not None else None
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

    return _row_to_research(fetch_research(con, research_id))


@router.delete('/api/research/{research_id}', status_code=204)
def delete_research(research_id: str) -> None:
    if research_id == DEFAULT_RESEARCH_ID:
        raise HTTPException(status_code=400, detail='Системное исследование Default нельзя удалять')
    con = get_pg()
    if fetch_research(con, research_id) is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    con.execute('DELETE FROM research WHERE id = %s', [research_id])


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


@router.get('/api/research/{research_id}/report')
def get_research_report(research_id: str):
    con = get_pg()
    row = fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    text = _format_research_report(con, row)
    return PlainTextResponse(text, media_type='text/markdown; charset=utf-8')
