"""
nirs — модуль событийного анализа для НИРС.

Экспортирует:
    models  — BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
    study   — EventStudyConfig, Event, MarketContext,
              EventResult, CompanyResult, StudyResult,
              EventStudyRunner
    loaders — load_events, load_rf, load_prices
"""
from .models import BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
from .study import (
    EventStudyConfig, Event, MarketContext,
    EventResult, CompanyResult, StudyResult,
    EventStudyRunner,
)
from .loaders import load_events, load_rf, load_prices

__all__ = [
    "BaseModel", "MeanAdjustedModel", "MarketModel", "CAPMModel",
    "EventStudyConfig", "Event", "MarketContext",
    "EventResult", "CompanyResult", "StudyResult", "EventStudyRunner",
    "load_events", "load_rf", "load_prices",
]
