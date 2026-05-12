"""DTO для стратегий."""
from schemas._common import CamelModel


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
