"""
Модели ожидаемой (нормальной) доходности для событийного анализа.

Иерархия:
    BaseModel (ABC)
    ├── MeanAdjustedModel  — модель постоянной средней доходности
    ├── MarketModel        — рыночная модель (OLS: r_i = α + β·r_m)
    └── CAPMModel          — CAPM (r_i = rf + β·(r_m − rf))

Каждая модель реализует интерфейс fit/predict через **kwargs.
Вызывающий код передаёт все доступные данные, модель берёт только нужное.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class BaseModel(ABC):
    """
    Абстрактный базовый класс модели ожидаемой доходности.

    Интерфейс:
        fit(**kwargs)     — обучение на оценочном окне
        predict(**kwargs)  — ожидаемые доходности для окна события
    """

    @abstractmethod
    def fit(self, **kwargs) -> None:
        """Оценивает параметры модели на оценочном окне."""

    @abstractmethod
    def predict(self, **kwargs) -> pd.Series:
        """Возвращает ожидаемые (нормальные) доходности для окна события."""


class MeanAdjustedModel(BaseModel):
    """
    Модель постоянной средней доходности.

    Нормальная доходность = среднее значение доходности акции
    в оценочном окне. Рыночные данные не используются.

    fit:     stock_returns
    predict: dates (DatetimeIndex)
    """

    def __init__(self) -> None:
        self._mean: float = 0.0

    def fit(self, *, stock_returns: pd.Series, **kwargs) -> None:
        self._mean = float(stock_returns.mean())

    def predict(self, *, dates: pd.DatetimeIndex, **kwargs) -> pd.Series:
        return pd.Series(self._mean, index=dates)


class MarketModel(BaseModel):
    """
    Рыночная модель (Market Model).

    Оценивает параметры МНК-регрессии в оценочном окне:
        r_i = α + β·r_m + ε

    Ожидаемая доходность в окне события:
        E[r_i] = α + β·r_m

    fit:     stock_returns, market_returns
    predict: market_returns
    """

    def __init__(self) -> None:
        self._alpha: float = 0.0
        self._beta: float = 1.0

    def fit(self, *, stock_returns: pd.Series, market_returns: pd.Series, **kwargs) -> None:
        beta, alpha = np.polyfit(market_returns.values, stock_returns.values, 1)
        self._alpha = float(alpha)
        self._beta = float(beta)

    def predict(self, *, market_returns: pd.Series, **kwargs) -> pd.Series:
        return pd.Series(
            self._alpha + self._beta * market_returns.values,
            index=market_returns.index,
        )


class CAPMModel(BaseModel):
    """
    Модель CAPM.

    Оценивает β в оценочном окне:
        (r_i − rf) = β·(r_m − rf) + ε

    Ожидаемая доходность в окне события:
        E[r_i] = rf + β·(r_m − rf)

    fit:     stock_returns, market_returns, rf_returns
    predict: market_returns, rf_returns
    """

    def __init__(self) -> None:
        self._beta: float = 1.0

    def fit(self, *, stock_returns: pd.Series, market_returns: pd.Series,
            rf_returns: pd.Series, **kwargs) -> None:
        excess_stock = stock_returns.values - rf_returns.values
        excess_market = market_returns.values - rf_returns.values
        denom = float(np.dot(excess_market, excess_market))
        self._beta = float(np.dot(excess_market, excess_stock) / denom) if denom != 0.0 else 1.0

    def predict(self, *, market_returns: pd.Series, rf_returns: pd.Series, **kwargs) -> pd.Series:
        rf = rf_returns.values
        rm = market_returns.values
        expected = rf + self._beta * (rm - rf)
        return pd.Series(expected, index=market_returns.index)
