"""DTO для PQL-эндпоинтов: поиск прецедентов и сохранённые запросы."""
from typing import Literal

from schemas._common import CamelModel

SavedQueryKind = Literal['FUZZY', 'PQL']


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


class SavedQuery(CamelModel):
    id: str
    name: str
    source: str
    kind: SavedQueryKind
    created_at: str


class SavedQuerySaveRequest(CamelModel):
    name: str
    source: str
    kind: SavedQueryKind = 'PQL'


class PrecedentFuzzySearchRequest(CamelModel):
    query: str


class PrecedentFuzzyHit(CamelModel):
    event_id: str
    event: str
    date_start: str


class PrecedentFuzzySearchResponse(CamelModel):
    hits: list[PrecedentFuzzyHit]
    truncated: bool
