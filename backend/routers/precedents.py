"""Эндпоинты PQL: поиск прецедентов и CRUD сохранённых запросов."""
import time
import uuid as _uuid
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, HTTPException

from routers._common import get_pg, pg_type_name, to_json_safe
from schemas.precedents import (
    PrecedentColumn,
    PrecedentFuzzyHit,
    PrecedentFuzzySearchRequest,
    PrecedentFuzzySearchResponse,
    PrecedentSearchRequest,
    PrecedentSearchResponse,
    PrecedentSearchStats,
    SavedQuery,
    SavedQuerySaveRequest,
)

router = APIRouter()

PRECEDENT_MAX_ROWS = 1000


@router.post("/api/precedents/search", response_model_by_alias=True)
def search_precedents(req: PrecedentSearchRequest) -> PrecedentSearchResponse:
    """Исполняет PQL-запрос. Жёсткий потолок MAX_ROWS=1000."""
    con = get_pg()
    started_at = time.monotonic()

    try:
        cur = con.execute(req.source)
        description = cur.description or []
        rows = cur.fetchmany(PRECEDENT_MAX_ROWS + 1)
    except psycopg.Error as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "line": None, "column": None},
        )

    truncated = len(rows) > PRECEDENT_MAX_ROWS
    if truncated:
        rows = rows[:PRECEDENT_MAX_ROWS]

    duration_ms = int((time.monotonic() - started_at) * 1000)
    columns = [PrecedentColumn(name=col.name, type=pg_type_name(col.type_code)) for col in description]
    rows_safe = [[to_json_safe(v) for v in row] for row in rows]

    return PrecedentSearchResponse(
        columns=columns,
        rows=rows_safe,
        stats=PrecedentSearchStats(truncated=truncated, duration_ms=duration_ms),
    )


@router.get("/api/precedents/queries", response_model_by_alias=True)
def list_saved_queries(kind: str | None = None) -> list[SavedQuery]:
    """Сохранённые запросы поиска, новые первыми. `kind` фильтрует по виду (FUZZY/PQL)."""
    con = get_pg()
    if kind is not None:
        rows = con.execute(
            "SELECT id, name, source, kind, created_at FROM saved_queries"
            " WHERE kind = %s ORDER BY created_at DESC",
            [kind],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, name, source, kind, created_at FROM saved_queries"
            " ORDER BY created_at DESC"
        ).fetchall()
    return [
        SavedQuery(id=r[0], name=r[1], source=r[2], kind=r[3], created_at=r[4])
        for r in rows
    ]


@router.post("/api/precedents/queries", response_model_by_alias=True, status_code=201)
def save_saved_query(req: SavedQuerySaveRequest) -> SavedQuery:
    """Сохраняет запрос поиска (FUZZY или PQL). Имя должно быть уникальным."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    if name.startswith('★'):
        raise HTTPException(status_code=400, detail="Имена с префиксом ★ зарезервированы за системными рецептами")
    source = req.source
    if not source.strip():
        raise HTTPException(status_code=400, detail="Текст запроса не может быть пустым")

    con = get_pg()
    existing = con.execute(
        "SELECT 1 FROM saved_queries WHERE name = %s LIMIT 1",
        [name],
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Запрос с таким именем уже существует")

    new_id = str(_uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    con.execute(
        "INSERT INTO saved_queries (id, name, source, created_at, kind) VALUES (%s, %s, %s, %s, %s)",
        [new_id, name, source, created_at, req.kind],
    )

    return SavedQuery(id=new_id, name=name, source=source, kind=req.kind, created_at=created_at)


@router.post("/api/precedents/search/fuzzy", response_model_by_alias=True)
def search_precedents_fuzzy(req: PrecedentFuzzySearchRequest) -> PrecedentFuzzySearchResponse:
    """Подстрочный поиск по описанию события (ILIKE).

    Триграммный GIN-индекс на events.event ускоряет шаблон '%...%'.
    Жёсткий потолок MAX_ROWS=1000 — как в PQL.
    """
    query = req.query.strip()
    if not query:
        return PrecedentFuzzySearchResponse(hits=[], truncated=False)

    pattern = f"%{query}%"
    con = get_pg()
    rows = con.execute(
        "SELECT id, event, date_start FROM events WHERE event ILIKE %s ORDER BY date_start DESC LIMIT %s",
        [pattern, PRECEDENT_MAX_ROWS + 1],
    ).fetchall()

    truncated = len(rows) > PRECEDENT_MAX_ROWS
    if truncated:
        rows = rows[:PRECEDENT_MAX_ROWS]

    hits = [
        PrecedentFuzzyHit(
            event_id=r[0],
            event=r[1] or '',
            date_start=r[2].isoformat() if r[2] is not None else '',
        )
        for r in rows
    ]
    return PrecedentFuzzySearchResponse(hits=hits, truncated=truncated)
