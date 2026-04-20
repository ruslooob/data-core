"""
Модели ожидаемой (нормальной) доходности для событийного анализа.

Иерархия:
    BaseExpectedReturnModel (ABC)
    ├── MeanAdjustedModel  — модель постоянной средней доходности
    ├── MarketModel        — рыночная модель (OLS: r_i = α + β·r_m)
    └── CAPMModel          — CAPM (r_i = rf + β·(r_m − rf))

Каждая модель реализует интерфейс fit/predict через **kwargs.
Вызывающий код передаёт все доступные данные, модель берёт только нужное.

Общие правила (действуют для всех моделей):
    - predict нельзя вызывать до fit — ValueError.
    - Все входные Series в fit должны быть непустыми и без NaN.
    - Индексы всех входных Series в fit должны совпадать (.equals).
    - Входные Series/DatetimeIndex в predict не должны содержать NaN/NaT.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


def _validate_fit_series(series: pd.Series, name: str) -> None:
    if len(series) == 0:
        raise ValueError(f"{name} не должна быть пустой")
    if series.isna().any():
        raise ValueError(f"{name} содержит NaN")


def _validate_same_index(
        series_a: pd.Series, name_a: str,
        series_b: pd.Series, name_b: str,
) -> None:
    if not series_a.index.equals(series_b.index):
        raise ValueError(f"Индексы {name_a} и {name_b} должны совпадать")


def _validate_fitted(fitted: bool, model_name: str) -> None:
    if not fitted:
        raise ValueError(f"{model_name}: нельзя вызывать predict до fit")


def _validate_no_nan(obj: pd.Series | pd.DatetimeIndex, name: str) -> None:
    if pd.isna(obj).any():
        raise ValueError(f"{name} содержит NaN/NaT")


class BaseExpectedReturnModel(ABC):
    """
    Абстрактный базовый класс модели ожидаемой доходности.

    Интерфейс:
        fit(**kwargs)     — обучение на оценочном окне
        predict(**kwargs) — ожидаемые доходности для окна события
    """

    @abstractmethod
    def fit(self, **kwargs) -> None:
        """Оценивает параметры модели на оценочном окне."""

    @abstractmethod
    def predict(self, **kwargs) -> pd.Series:
        """Возвращает ожидаемые (нормальные) доходности для окна события."""


class MeanAdjustedModel(BaseExpectedReturnModel):
    """
    Модель постоянной средней доходности.

    Нормальная доходность = среднее значение доходности акции
    в оценочном окне. Рыночные данные не используются.

    fit(stock_log_returns: pd.Series)    — непустая Series без NaN.
    predict(dates: pd.DatetimeIndex)     — DatetimeIndex без NaT.

    Исключения:
        ValueError при вызове predict до fit, при пустой Series в fit,
        при NaN в stock_log_returns, при NaT в dates.
    """

    def __init__(self) -> None:
        self._mean: float = 0.0
        self._fitted: bool = False

    def fit(self, *, stock_log_returns: pd.Series, **kwargs) -> None:
        _validate_fit_series(stock_log_returns, "stock_log_returns")
        self._mean = float(stock_log_returns.mean())
        self._fitted = True

    def predict(self, *, dates: pd.DatetimeIndex, **kwargs) -> pd.Series:
        _validate_fitted(self._fitted, type(self).__name__)
        _validate_no_nan(dates, "dates")
        return pd.Series(self._mean, index=dates)


class MarketModel(BaseExpectedReturnModel):
    """
    Рыночная модель (Market Model).

    Оценивает параметры МНК-регрессии в оценочном окне:
        r_i = α + β·r_m + ε

    Ожидаемая доходность в окне события:
        E[r_i] = α + β·r_m

    fit(stock_log_returns, market_log_returns)
        — непустые Series без NaN, индексы должны совпадать (.equals).
    predict(market_log_returns)
        — Series без NaN.

    Исключения:
        ValueError при вызове predict до fit, при пустых или
        NaN-содержащих Series, при несовпадении индексов в fit.
    """

    def __init__(self) -> None:
        self._alpha: float = 0.0
        self._beta: float = 1.0
        self._fitted: bool = False

    def fit(self, *, stock_log_returns: pd.Series,
            market_log_returns: pd.Series, **kwargs) -> None:
        _validate_fit_series(stock_log_returns, "stock_log_returns")
        _validate_fit_series(market_log_returns, "market_log_returns")
        _validate_same_index(
            stock_log_returns, "stock_log_returns",
            market_log_returns, "market_log_returns",
        )
        beta, alpha = np.polyfit(
            market_log_returns.values, stock_log_returns.values, 1,
        )
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._fitted = True

    def predict(self, *, market_log_returns: pd.Series, **kwargs) -> pd.Series:
        _validate_fitted(self._fitted, type(self).__name__)
        _validate_no_nan(market_log_returns, "market_log_returns")
        return pd.Series(
            self._alpha + self._beta * market_log_returns.values,
            index=market_log_returns.index,
        )


class CAPMModel(BaseExpectedReturnModel):
    """
    Модель CAPM.

    Оценивает β в оценочном окне:
        (r_i − rf) = β·(r_m − rf) + ε

    Ожидаемая доходность в окне события:
        E[r_i] = rf + β·(r_m − rf)

    fit(stock_log_returns, market_log_returns, rf_log_returns)
        — непустые Series без NaN, индексы всех трёх должны совпадать.
    predict(market_log_returns, rf_log_returns)
        — Series без NaN, индексы должны совпадать.

    Исключения:
        ValueError при вызове predict до fit, при пустых или
        NaN-содержащих Series, при несовпадении индексов.
    """

    def __init__(self) -> None:
        self._beta: float = 1.0
        self._fitted: bool = False

    def fit(self, *, stock_log_returns: pd.Series,
            market_log_returns: pd.Series,
            rf_log_returns: pd.Series, **kwargs) -> None:
        _validate_fit_series(stock_log_returns, "stock_log_returns")
        _validate_fit_series(market_log_returns, "market_log_returns")
        _validate_fit_series(rf_log_returns, "rf_log_returns")
        _validate_same_index(
            stock_log_returns, "stock_log_returns",
            market_log_returns, "market_log_returns",
        )
        _validate_same_index(
            stock_log_returns, "stock_log_returns",
            rf_log_returns, "rf_log_returns",
        )
        excess_stock = stock_log_returns.values - rf_log_returns.values
        excess_market = market_log_returns.values - rf_log_returns.values
        denom = float(np.dot(excess_market, excess_market))
        self._beta = float(np.dot(excess_market, excess_stock) / denom) if denom != 0.0 else 1.0
        self._fitted = True

    def predict(self, *, market_log_returns: pd.Series,
                rf_log_returns: pd.Series, **kwargs) -> pd.Series:
        _validate_fitted(self._fitted, type(self).__name__)
        _validate_no_nan(market_log_returns, "market_log_returns")
        _validate_no_nan(rf_log_returns, "rf_log_returns")
        _validate_same_index(
            market_log_returns, "market_log_returns",
            rf_log_returns, "rf_log_returns",
        )
        rf = rf_log_returns.values
        rm = market_log_returns.values
        expected = rf + self._beta * (rm - rf)
        return pd.Series(expected, index=market_log_returns.index)
