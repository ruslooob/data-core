"""DTO для окружений."""
from schemas._common import CamelModel


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
