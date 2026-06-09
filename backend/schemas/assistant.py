"""DTO для эндпоинтов помощника."""
from schemas._common import CamelModel


class AssistantMessage(CamelModel):
    role: str  # 'user' | 'assistant'
    text: str


class AssistantRequest(CamelModel):
    history: list[AssistantMessage]
    research_id: str | None = None
    attached_docs: list[str] = []
