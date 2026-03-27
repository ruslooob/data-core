"""
nirs — модуль событийного анализа для НИРС.

Экспортирует:
    models  — BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
    study   — EventStudyConfig, DividendEvent,
              EventResult, CompanyResult, StudyResult,
              EventStudyRunner
"""
from core.expected_return_models import BaseModel, MeanAdjustedModel, MarketModel, CAPMModel
from .study import (
    EventStudyConfig, DividendEvent,
    EventResult, CompanyResult, StudyResult,
    EventStudyRunner,
)

__all__ = [
    "BaseModel", "MeanAdjustedModel", "MarketModel", "CAPMModel",
    "EventStudyConfig", "DividendEvent",
    "EventResult", "CompanyResult", "StudyResult", "EventStudyRunner",
]
