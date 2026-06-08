"""CRUD-эндпоинты исследований + CSV-экспорт прогонов."""
import csv
import io
import re
import uuid as _uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from core.research_report_pdf import render_research_report_pdf
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


@router.get('/api/research/{research_id}/export')
def export_research_report(research_id: str, format: str):
    """Единый эндпоинт экспорта отчёта.

    Поддерживаемые `format`:
      * `csv` — плоская таблица всех прогонов исследования.
      * `pdf` — пока не реализован (501).
    """
    con = get_pg()
    row = fetch_research(con, research_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Исследование не найдено')
    rid, name, *_ = row
    slug = re.sub(r'[^a-zA-Z0-9_\-]+', '-', (name or 'research').lower()).strip('-') or 'research'

    if format == 'csv':
        return Response(
            content=_render_research_runs_csv(con, rid),
            media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="{slug}.csv"'},
        )
    if format == 'pdf':
        return Response(
            content=render_research_report_pdf(con, rid),
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{slug}.pdf"'},
        )
    raise HTTPException(status_code=400, detail=f'Неизвестный формат: {format!r}')


def _render_research_runs_csv(con, research_id: str) -> str:
    runs = con.execute(
        '''
        SELECT s.name, e.name, e.date_start, e.date_end,
               br.total_return_pct, br.annual_return_pct, br.max_drawdown_pct,
               br.sharpe, br.n_trades, br.profit_factor, br.win_rate_pct,
               br.created_at
        FROM backtest_results br
        LEFT JOIN strategies   s ON s.id = br.strategy_id
        LEFT JOIN environments e ON e.id = br.environment_id
        WHERE br.research_id = %s
        ORDER BY br.created_at
        ''',
        [research_id],
    ).fetchall()

    buf = io.StringIO()
    # BOM — чтобы Excel под Windows подхватил UTF-8 без шаманства с кодировками.
    buf.write('\ufeff')
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow([
        'strategy', 'environment', 'date_start', 'date_end',
        'total_return_pct', 'annual_return_pct', 'max_drawdown_pct',
        'sharpe', 'n_trades', 'profit_factor', 'win_rate_pct', 'created_at',
    ])
    for r in runs:
        writer.writerow([
            r[0] or '', r[1] or '',
            r[2].isoformat() if hasattr(r[2], 'isoformat') else (r[2] or ''),
            r[3].isoformat() if hasattr(r[3], 'isoformat') else (r[3] or ''),
            f'{float(r[4]):.4f}',
            f'{float(r[5]):.4f}',
            f'{float(r[6]):.4f}',
            f'{float(r[7]):.4f}',
            int(r[8]),
            '' if r[9] is None else f'{float(r[9]):.4f}',
            '' if r[10] is None else f'{float(r[10]):.4f}',
            r[11],
        ])
    return buf.getvalue()
