"""Общие Pydantic-классы для HTTP DTO."""
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Базовый Pydantic-класс с camelCase-сериализацией для JSON DTO.

    Поля внутри Python-класса остаются snake_case (Python-конвенция),
    а в JSON попадают как camelCase через alias_generator.
    populate_by_name=True позволяет принимать и snake_case, и camelCase на входе.
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RenameRequest(CamelModel):
    name: str


class DescriptionRequest(CamelModel):
    description: str | None = None


class ResearchScopeRequest(CamelModel):
    """`null` = сделать общей; UUID = сделать приватной указанного исследования."""
    research_id: str | None = None
