"""Диагностические поля EventStudy.analyze: R², σ-остатки, накопленный CAR, полоса."""
import numpy as np
import pandas as pd
import pytest

from core.event_study import EventStudy


def _make_study(seed: int = 0):
    """Синтетика с реальной связью акции с рынком: stock = 0.0002 + 0.9·market + шум."""
    dates = pd.bdate_range('2020-01-01', periods=300)
    rng = np.random.default_rng(seed)
    market = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    stock = pd.Series(
        0.0002 + 0.9 * market.values + rng.normal(0, 0.008, len(dates)),
        index=dates,
    )
    return EventStudy(stock_log_returns=stock), market, dates


def test_market_model_diagnostics():
    study, market, dates = _make_study()
    res = study.analyze(
        event_date=dates[250].date(),
        model='market_model',
        event_window=(-5, 5),
        estimation_window=200,
        market=market,
    )
    assert res is not None
    # R² рыночной модели (МНК со свободным членом) всегда в [0, 1]
    assert 0.0 <= res.r_squared <= 1.0
    # связь с рынком заложена в данные → модель объясняет заметную долю дисперсии
    assert res.r_squared > 0.3
    # накопленный CAR замыкается на итоговый CAR
    assert res.car_cumulative[-1] == pytest.approx(res.car)
    # длины рядов согласованы с окнами
    assert len(res.car_cumulative) == len(res.ar)
    assert len(res.ci_band) == len(res.ar)
    assert len(res.residual_sigmas) == len(res.estimation_dates)
    # полоса неотрицательна и растёт (√k)
    assert res.ci_band[0] >= 0
    assert res.ci_band[-1] >= res.ci_band[0]


def test_mean_adjusted_r_squared_is_zero():
    study, _market, dates = _make_study()
    res = study.analyze(
        event_date=dates[250].date(),
        model='mean_adjusted',
        event_window=(-5, 5),
        estimation_window=200,
    )
    assert res is not None
    # модель на среднем: прогноз — константа, объясняющей силы нет → R² = 0
    assert res.r_squared == pytest.approx(0.0, abs=1e-9)


def test_residual_sigmas_consistent_with_std():
    study, market, dates = _make_study()
    res = study.analyze(
        event_date=dates[250].date(),
        model='market_model',
        event_window=(-5, 5),
        estimation_window=200,
        market=market,
    )
    # σ-расстояние × σ_ε = исходный остаток (факт − прогноз)
    residuals = np.array(res.estimation_actual) - np.array(res.estimation_predicted)
    reconstructed = np.array(res.residual_sigmas) * res.estimation_std
    np.testing.assert_allclose(reconstructed, residuals, atol=1e-12)
