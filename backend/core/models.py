"""Общие датаклассы проекта."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DividendEvent:
    """Одно дивидендное событие."""
    ticker: str
    event_date: date
    dividend: float
    year: int
