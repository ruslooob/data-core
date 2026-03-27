"""
nirs — модуль событийного анализа для НИРС.

Экспортирует:
    models  — BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
    study   — EventStudyConfig, DividendEvent, MarketContext,
              EventResult, CompanyResult, StudyResult,
              EventStudyRunner
"""
from .models import BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
from .study import (
    EventStudyConfig, DividendEvent, MarketContext,
    EventResult, CompanyResult, StudyResult,
    EventStudyRunner,
)

__all__ = [
    "BaseModel", "MeanAdjustedModel", "MarketModel", "CAPMModel",
    "EventStudyConfig", "DividendEvent", "MarketContext",
    "EventResult", "CompanyResult", "StudyResult", "EventStudyRunner",
]
