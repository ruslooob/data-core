"""Индивидуальный Sensitivity: CAR против нормы по сетке параметров для одного события."""
import numpy as np
import pandas as pd

from core.event_effect import calculate_individual_sensitivity


class _FakeStocks:
    def __init__(self, series: pd.Series):
        self._series = series

    def get_log_returns(self, ticker: str) -> pd.Series:
        return self._series


class _FakeMarket:
    def __init__(self, market: pd.Series, rf: pd.Series):
        self._market = market
        self._rf = rf

    def load_market_index_log_returns(self) -> pd.Series:
        return self._market

    def load_daily_risk_free_rate(self) -> pd.Series:
        return self._rf


def _providers(seed: int = 0):
    """Синтетика со связью акции с рынком: stock = 0.0002 + 0.9·market + шум."""
    dates = pd.bdate_range('2018-01-01', periods=400)
    rng = np.random.default_rng(seed)
    market = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    stock = pd.Series(
        0.0002 + 0.9 * market.values + rng.normal(0, 0.008, len(dates)),
        index=dates,
    )
    rf = pd.Series(0.0001, index=dates)
    return _FakeStocks(stock), _FakeMarket(market, rf), dates


def test_grid_shape_and_norma_invariants():
    stocks, market, dates = _providers()
    cells = calculate_individual_sensitivity(
        ticker='X',
        event_date=dates[350].date(),
        windows=[3, 5],
        models=['market_model', 'capm'],
        estimation_windows=[150, 200],
        stocks=stocks,
        market=market,
    )
    # по ячейке на каждую комбинацию сетки
    assert len(cells) == 2 * 2 * 2

    for c in cells:
        if not c.available:
            continue
        # норма — корректный интервал
        assert c.baseline_down <= c.baseline_up
        assert 0.0 <= c.signed_rank <= 1.0
        # аномалия ⟺ signed_rank вне [0.05, 0.95]
        assert c.is_anomaly_signed == (c.signed_rank > 0.95 or c.signed_rank < 0.05)


def test_too_early_event_marked_unavailable():
    stocks, market, dates = _providers()
    cells = calculate_individual_sensitivity(
        ticker='X',
        event_date=dates[5].date(),  # истории под оценочное окно не хватает
        windows=[5],
        models=['market_model'],
        estimation_windows=[200],
        stocks=stocks,
        market=market,
    )
    assert len(cells) == 1
    assert cells[0].available is False
