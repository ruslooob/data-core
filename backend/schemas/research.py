"""DTO для исследований (research)."""
from schemas._common import CamelModel


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
