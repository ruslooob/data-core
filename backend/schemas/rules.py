"""DTO для правил."""
from schemas._common import CamelModel


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
