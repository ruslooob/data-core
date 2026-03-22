"""
Модели нормальной доходности для событийного анализа.

Иерархия:
    BaseModel (ABC)
    ├── MeanAdjustedModel  — модель постоянной средней доходности
    ├── MarketModel        — рыночная модель (OLS: r_i = α + β·r_m)
    └── CAPMModel          — CAPM (OLS: r_i−rf = β·(r_m−rf))

Каждая модель принимает объект MarketContext, содержащий рыночные
доходности и безрисковую ставку. Конкретная модель берёт из контекста
только то, что ей нужно.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class MarketContext:
    """Рыночные данные для оценочного окна или окна события."""

    def __init__(self, market_returns: pd.Series, rf_returns: pd.Series) -> None:
        self.market_returns = market_returns
        self.rf_returns = rf_returns


# ---------------------------------------------------------------------------
# Абстрактный базовый класс
# ---------------------------------------------------------------------------

class BaseModel(ABC):
    """
    Абстрактный базовый класс модели нормальной доходности.

    Интерфейс:
        fit(stock_returns, ctx)  — обучение на оценочном окне
        predict(ctx)             — ожидаемые доходности для окна события
    """

    @abstractmethod
    def fit(self, stock_returns: pd.Series, ctx: MarketContext) -> None:
        """
        Оценивает параметры модели на оценочном окне.

        Параметры:
            stock_returns: дневные логдоходности акции в оценочном окне
            ctx:           рыночный контекст того же периода
        """

    @abstractmethod
    def predict(self, ctx: MarketContext) -> pd.Series:
        """
        Возвращает ожидаемые (нормальные) доходности для окна события.

        Параметры:
            ctx: рыночный контекст окна события

        Возвращает:
            pd.Series с индексом, совпадающим с ctx.market_returns.index
        """


# ---------------------------------------------------------------------------
# Модель 1: постоянная средняя доходность
# ---------------------------------------------------------------------------

class MeanAdjustedModel(BaseModel):
    """
    Модель постоянной средней доходности.

    Нормальная доходность = среднее значение доходности акции
    в оценочном окне. Рыночные данные не используются.
    """

    def __init__(self) -> None:
        self._mean: float = 0.0

    def fit(self, stock_returns: pd.Series, ctx: MarketContext) -> None:
        self._mean = float(stock_returns.mean())

    def predict(self, ctx: MarketContext) -> pd.Series:
        return pd.Series(self._mean, index=ctx.market_returns.index)


# ---------------------------------------------------------------------------
# Модель 2: рыночная модель
# ---------------------------------------------------------------------------

class MarketModel(BaseModel):
    """
    Рыночная модель (Market Model).

    Оценивает параметры МНК-регрессии в оценочном окне:
        r_i = α + β·r_m + ε

    Ожидаемая доходность в окне события:
        E[r_i] = α + β·r_m
    """

    def __init__(self) -> None:
        self._alpha: float = 0.0
        self._beta: float = 1.0

    def fit(self, stock_returns: pd.Series, ctx: MarketContext) -> None:
        x = ctx.market_returns.values
        y = stock_returns.values
        # МНК: [beta, alpha] = polyfit(x, y, 1)
        beta, alpha = np.polyfit(x, y, 1)
        self._alpha = float(alpha)
        self._beta = float(beta)

    def predict(self, ctx: MarketContext) -> pd.Series:
        return pd.Series(
            self._alpha + self._beta * ctx.market_returns.values,
            index=ctx.market_returns.index,
        )


# ---------------------------------------------------------------------------
# Модель 3: CAPM
# ---------------------------------------------------------------------------

class CAPMModel(BaseModel):
    """
    Модель CAPM.

    Оценивает β в оценочном окне по МНК-регрессии
    избыточных доходностей:
        (r_i − rf) = α + β·(r_m − rf) + ε

    Ожидаемая доходность в окне события:
        E[r_i] = rf + β·(r_m − rf)

    Безрисковая ставка берётся из MarketContext.rf_returns
    (RUONIA, переведённая в дневную: ruo/100/252).
    """

    def __init__(self) -> None:
        self._beta: float = 1.0

    def fit(self, stock_returns: pd.Series, ctx: MarketContext) -> None:
        excess_stock = stock_returns.values - ctx.rf_returns.values
        excess_market = ctx.market_returns.values - ctx.rf_returns.values
        # Классический CAPM предполагает alpha = 0.
        # beta = cov(ri−rf, rm−rf) / var(rm−rf) — МНК без свободного члена.
        denom = float(np.dot(excess_market, excess_market))
        self._beta = float(np.dot(excess_market, excess_stock) / denom) if denom != 0.0 else 1.0

    def predict(self, ctx: MarketContext) -> pd.Series:
        rf = ctx.rf_returns.values
        rm = ctx.market_returns.values
        expected = rf + self._beta * (rm - rf)
        return pd.Series(expected, index=ctx.market_returns.index)
