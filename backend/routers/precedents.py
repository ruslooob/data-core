"""Эндпоинты PQL: поиск прецедентов и CRUD сохранённых запросов."""
import time
import uuid as _uuid
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, HTTPException

from routers._common import get_pg, pg_type_name, to_json_safe
from schemas.precedents import (
    EventInfoRow,
    EventsInfoRequest,
    EventsInfoResponse,
    PrecedentColumn,
    PrecedentFuzzyHit,
    PrecedentFuzzySearchRequest,
    PrecedentFuzzySearchResponse,
    PrecedentQueryRecord,
    PrecedentQuerySaveRequest,
    PrecedentSearchRequest,
    PrecedentSearchResponse,
    PrecedentSearchStats,
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
def list_precedent_queries() -> list[PrecedentQueryRecord]:
    """Список сохранённых прецедентных запросов, отсортированный по дате создания (новые первыми)."""
    con = get_pg()
    rows = con.execute("""
        SELECT id, name, source, created_at FROM precedent_queries
        ORDER BY created_at DESC
    """).fetchall()
    return [
        PrecedentQueryRecord(id=r[0], name=r[1], source=r[2], created_at=r[3])
        for r in rows
    ]


@router.post("/api/precedents/queries", response_model_by_alias=True, status_code=201)
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

    con = get_pg()
    existing = con.execute(
        "SELECT 1 FROM precedent_queries WHERE name = %s LIMIT 1",
        [name],
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Запрос с таким именем уже существует")

    new_id = str(_uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    con.execute(
        "INSERT INTO precedent_queries VALUES (%s, %s, %s, %s)",
        [new_id, name, source, created_at],
    )

    return PrecedentQueryRecord(id=new_id, name=name, source=source, created_at=created_at)


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
        "SELECT id, event FROM events WHERE event ILIKE %s ORDER BY date_start DESC LIMIT %s",
        [pattern, PRECEDENT_MAX_ROWS + 1],
    ).fetchall()

    truncated = len(rows) > PRECEDENT_MAX_ROWS
    if truncated:
        rows = rows[:PRECEDENT_MAX_ROWS]

    hits = [PrecedentFuzzyHit(event_id=r[0], event=r[1] or '') for r in rows]
    return PrecedentFuzzySearchResponse(hits=hits, truncated=truncated)


@router.post("/api/precedents/events-info", response_model_by_alias=True)
def events_info(req: EventsInfoRequest) -> EventsInfoResponse:
    """Возвращает дату события и его теги по списку event_id.

    Используется виджетом «Поиск прецедентов»: PQL и fuzzy выдают только
    id+event, остальной контекст (дата, теги) дотягивается одним батчем.
    """
    if not req.event_ids:
        return EventsInfoResponse(rows=[])

    con = get_pg()
    rows = con.execute(
        """
        SELECT e.id, e.date_start, COALESCE(ARRAY_AGG(et.tag_code ORDER BY et.tag_code)
                                            FILTER (WHERE et.tag_code IS NOT NULL),
                                            '{}')
        FROM events e
        LEFT JOIN event_tags et ON et.event_id = e.id
        WHERE e.id = ANY(%s)
        GROUP BY e.id, e.date_start
        """,
        [req.event_ids],
    ).fetchall()

    return EventsInfoResponse(
        rows=[
            EventInfoRow(
                event_id=r[0],
                date_start=r[1].isoformat() if r[1] is not None else '',
                tags=list(r[2] or []),
            )
            for r in rows
        ],
    )
