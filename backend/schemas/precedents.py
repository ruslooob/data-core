"""DTO для PQL-эндпоинтов: поиск прецедентов и сохранённые запросы."""
from schemas._common import CamelModel


class PrecedentSearchRequest(CamelModel):
    source: str


class PrecedentColumn(CamelModel):
    name: str
    type: str


class PrecedentSearchStats(CamelModel):
    truncated: bool
    duration_ms: int


class PrecedentSearchResponse(CamelModel):
    columns: list[PrecedentColumn]
    rows: list[list]
    stats: PrecedentSearchStats


class PrecedentQueryRecord(CamelModel):
    id: str
    name: str
    source: str
    created_at: str


class PrecedentQuerySaveRequest(CamelModel):
    name: str
    source: str


class PrecedentFuzzySearchRequest(CamelModel):
    query: str


class PrecedentFuzzyHit(CamelModel):
    event_id: str
    event: str


class PrecedentFuzzySearchResponse(CamelModel):
    hits: list[PrecedentFuzzyHit]
    truncated: bool


class EventsInfoRequest(CamelModel):
    event_ids: list[str]


class EventInfoRow(CamelModel):
    event_id: str
    date_start: str
    tags: list[str]


class EventsInfoResponse(CamelModel):
    rows: list[EventInfoRow]
