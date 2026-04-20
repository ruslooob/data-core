import numpy as np
import pandas as pd
import pytest

from core.expected_return_models import (
    MeanAdjustedModel,
    MarketModel,
    CAPMModel,
)


# ============================================================
# MeanAdjustedModel
# ============================================================

class TestMeanAdjustedModel:

    def test_predict_without_fit_raises(self):
        model = MeanAdjustedModel()
        dates = pd.DatetimeIndex(['2020-01-01', '2020-01-02'])
        with pytest.raises(ValueError):
            model.predict(dates=dates)

    def test_fit_empty_series_raises(self):
        model = MeanAdjustedModel()
        with pytest.raises(ValueError):
            model.fit(stock_log_returns=pd.Series([], dtype=float))

    def test_fit_series_with_nan_raises(self):
        model = MeanAdjustedModel()
        with pytest.raises(ValueError):
            model.fit(stock_log_returns=pd.Series([0.01, np.nan, 0.02]))

    def test_predict_with_nat_raises(self):
        model = MeanAdjustedModel()
        model.fit(stock_log_returns=pd.Series([0.01, 0.02, 0.03]))
        dates = pd.DatetimeIndex(['2020-01-01', pd.NaT, '2020-01-03'])
        with pytest.raises(ValueError):
            model.predict(dates=dates)

    def test_predict_returns_constant_mean(self):
        model = MeanAdjustedModel()
        model.fit(stock_log_returns=pd.Series([0.01, 0.02, 0.03]))  # mean = 0.02
        dates = pd.DatetimeIndex(['2020-01-01', '2020-01-02', '2020-01-03'])
        expected = model.predict(dates=dates)
        assert expected.tolist() == pytest.approx([0.02, 0.02, 0.02])

    def test_predict_index_equals_input_dates(self):
        model = MeanAdjustedModel()
        model.fit(stock_log_returns=pd.Series([0.01, 0.02]))
        dates = pd.DatetimeIndex(['2020-06-01', '2020-06-02'])
        result = model.predict(dates=dates)
        assert result.index.equals(dates)

    def test_refit_updates_mean(self):
        model = MeanAdjustedModel()
        model.fit(stock_log_returns=pd.Series([1.0, 1.0]))
        model.fit(stock_log_returns=pd.Series([5.0, 5.0]))
        result = model.predict(dates=pd.DatetimeIndex(['2020-01-01']))
        assert result.iloc[0] == pytest.approx(5.0)

    def test_fit_ignores_extra_kwargs(self):
        # Единообразный интерфейс: лишние аргументы игнорируются.
        model = MeanAdjustedModel()
        model.fit(
            stock_log_returns=pd.Series([0.01, 0.02]),
            market_log_returns=pd.Series([0.5, 0.5]),
            rf_log_returns=pd.Series([0.0001]),
        )


# ============================================================
# MarketModel
# ============================================================

def _make_linear_data(n: int, alpha: float, beta: float):
    """Генерит (stock, market) с stock = alpha + beta * market."""
    idx = pd.date_range('2020-01-01', periods=n, freq='D')
    market = pd.Series(np.linspace(-0.05, 0.05, n), index=idx)
    stock = alpha + beta * market
    return stock, market


class TestMarketModel:

    def test_predict_without_fit_raises(self):
        model = MarketModel()
        mkt = pd.Series([0.01], index=pd.DatetimeIndex(['2020-01-01']))
        with pytest.raises(ValueError):
            model.predict(market_log_returns=mkt)

    @pytest.mark.parametrize('which', ['stock', 'market'])
    def test_fit_empty_series_raises(self, which):
        model = MarketModel()
        empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
        other = pd.Series([0.01, 0.02],
                          index=pd.date_range('2020-01-01', periods=2, freq='D'))
        with pytest.raises(ValueError):
            if which == 'stock':
                model.fit(stock_log_returns=empty, market_log_returns=other)
            else:
                model.fit(stock_log_returns=other, market_log_returns=empty)

    @pytest.mark.parametrize('which', ['stock', 'market'])
    def test_fit_nan_raises(self, which):
        model = MarketModel()
        idx = pd.date_range('2020-01-01', periods=3, freq='D')
        good = pd.Series([0.01, 0.02, 0.03], index=idx)
        bad = pd.Series([0.01, np.nan, 0.03], index=idx)
        with pytest.raises(ValueError):
            if which == 'stock':
                model.fit(stock_log_returns=bad, market_log_returns=good)
            else:
                model.fit(stock_log_returns=good, market_log_returns=bad)

    def test_fit_different_lengths_raises(self):
        model = MarketModel()
        stock = pd.Series([0.01, 0.02, 0.03],
                          index=pd.date_range('2020-01-01', periods=3, freq='D'))
        market = pd.Series([0.01, 0.02],
                           index=pd.date_range('2020-01-01', periods=2, freq='D'))
        with pytest.raises(ValueError):
            model.fit(stock_log_returns=stock, market_log_returns=market)

    def test_fit_mismatched_indices_raises(self):
        model = MarketModel()
        stock = pd.Series([0.01, 0.02, 0.03],
                          index=pd.date_range('2020-01-01', periods=3, freq='D'))
        market = pd.Series([0.01, 0.02, 0.03],
                           index=pd.date_range('2020-06-01', periods=3, freq='D'))
        with pytest.raises(ValueError):
            model.fit(stock_log_returns=stock, market_log_returns=market)

    def test_predict_nan_raises(self):
        model = MarketModel()
        stock, market = _make_linear_data(10, alpha=0.01, beta=1.5)
        model.fit(stock_log_returns=stock, market_log_returns=market)
        bad_market = pd.Series(
            [0.01, np.nan],
            index=pd.date_range('2020-06-01', periods=2, freq='D'),
        )
        with pytest.raises(ValueError):
            model.predict(market_log_returns=bad_market)

    def test_fit_recovers_alpha_and_beta(self):
        model = MarketModel()
        stock, market = _make_linear_data(100, alpha=0.005, beta=1.3)
        model.fit(stock_log_returns=stock, market_log_returns=market)
        assert model._alpha == pytest.approx(0.005, abs=1e-10)
        assert model._beta == pytest.approx(1.3, abs=1e-10)

    def test_predict_applies_linear_formula(self):
        model = MarketModel()
        stock, market = _make_linear_data(50, alpha=0.005, beta=1.3)
        model.fit(stock_log_returns=stock, market_log_returns=market)

        new_idx = pd.date_range('2021-01-01', periods=5, freq='D')
        new_market = pd.Series([0.01, -0.02, 0.03, 0.0, 0.015], index=new_idx)
        result = model.predict(market_log_returns=new_market)

        expected_values = 0.005 + 1.3 * new_market.values
        np.testing.assert_allclose(result.values, expected_values, rtol=1e-10)
        assert result.index.equals(new_idx)

    def test_refit_updates_parameters(self):
        model = MarketModel()
        stock1, market1 = _make_linear_data(50, alpha=0.0, beta=1.0)
        model.fit(stock_log_returns=stock1, market_log_returns=market1)

        stock2, market2 = _make_linear_data(50, alpha=0.01, beta=2.0)
        model.fit(stock_log_returns=stock2, market_log_returns=market2)

        assert model._alpha == pytest.approx(0.01, abs=1e-10)
        assert model._beta == pytest.approx(2.0, abs=1e-10)

    def test_fit_ignores_extra_kwargs(self):
        model = MarketModel()
        stock, market = _make_linear_data(20, alpha=0.0, beta=1.0)
        rf = pd.Series([0.0001] * 20, index=stock.index)
        model.fit(
            stock_log_returns=stock,
            market_log_returns=market,
            rf_log_returns=rf,
        )


# ============================================================
# CAPMModel
# ============================================================

def _make_capm_data(n: int, beta: float, rf_value: float = 0.0001):
    """Генерит (stock, market, rf), где stock - rf = beta * (market - rf)."""
    idx = pd.date_range('2020-01-01', periods=n, freq='D')
    market = pd.Series(np.linspace(-0.05, 0.05, n), index=idx)
    rf = pd.Series([rf_value] * n, index=idx)
    # По CAPM: r_i = rf + β·(r_m − rf)
    stock = rf_value + beta * (market - rf_value)
    return stock, market, rf


class TestCAPMModel:

    def test_predict_without_fit_raises(self):
        model = CAPMModel()
        idx = pd.DatetimeIndex(['2020-01-01'])
        mkt = pd.Series([0.01], index=idx)
        rf = pd.Series([0.0001], index=idx)
        with pytest.raises(ValueError):
            model.predict(market_log_returns=mkt, rf_log_returns=rf)

    @pytest.mark.parametrize('which', ['stock', 'market', 'rf'])
    def test_fit_empty_series_raises(self, which):
        model = CAPMModel()
        idx = pd.date_range('2020-01-01', periods=3, freq='D')
        good = pd.Series([0.01, 0.02, 0.03], index=idx)
        empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
        inputs = {'stock': good, 'market': good, 'rf': good}
        inputs[which] = empty
        with pytest.raises(ValueError):
            model.fit(
                stock_log_returns=inputs['stock'],
                market_log_returns=inputs['market'],
                rf_log_returns=inputs['rf'],
            )

    @pytest.mark.parametrize('which', ['stock', 'market', 'rf'])
    def test_fit_nan_raises(self, which):
        model = CAPMModel()
        idx = pd.date_range('2020-01-01', periods=3, freq='D')
        good = pd.Series([0.01, 0.02, 0.03], index=idx)
        bad = pd.Series([0.01, np.nan, 0.03], index=idx)
        inputs = {'stock': good, 'market': good.copy(), 'rf': good.copy()}
        inputs[which] = bad
        with pytest.raises(ValueError):
            model.fit(
                stock_log_returns=inputs['stock'],
                market_log_returns=inputs['market'],
                rf_log_returns=inputs['rf'],
            )

    @pytest.mark.parametrize('mismatched', ['market', 'rf'])
    def test_fit_mismatched_indices_raises(self, mismatched):
        model = CAPMModel()
        idx_a = pd.date_range('2020-01-01', periods=3, freq='D')
        idx_b = pd.date_range('2020-06-01', periods=3, freq='D')
        stock = pd.Series([0.01, 0.02, 0.03], index=idx_a)
        market = pd.Series([0.01, 0.02, 0.03], index=idx_a)
        rf = pd.Series([0.0001, 0.0001, 0.0001], index=idx_a)
        if mismatched == 'market':
            market = pd.Series([0.01, 0.02, 0.03], index=idx_b)
        else:
            rf = pd.Series([0.0001, 0.0001, 0.0001], index=idx_b)
        with pytest.raises(ValueError):
            model.fit(
                stock_log_returns=stock,
                market_log_returns=market,
                rf_log_returns=rf,
            )

    @pytest.mark.parametrize('which', ['market', 'rf'])
    def test_predict_nan_raises(self, which):
        model = CAPMModel()
        stock, market, rf = _make_capm_data(10, beta=1.5)
        model.fit(stock_log_returns=stock, market_log_returns=market, rf_log_returns=rf)

        new_idx = pd.date_range('2021-01-01', periods=2, freq='D')
        new_market = pd.Series([0.01, 0.02], index=new_idx)
        new_rf = pd.Series([0.0001, 0.0001], index=new_idx)
        if which == 'market':
            new_market = pd.Series([0.01, np.nan], index=new_idx)
        else:
            new_rf = pd.Series([0.0001, np.nan], index=new_idx)
        with pytest.raises(ValueError):
            model.predict(market_log_returns=new_market, rf_log_returns=new_rf)

    def test_predict_mismatched_indices_raises(self):
        model = CAPMModel()
        stock, market, rf = _make_capm_data(10, beta=1.5)
        model.fit(stock_log_returns=stock, market_log_returns=market, rf_log_returns=rf)

        mkt = pd.Series([0.01, 0.02],
                        index=pd.date_range('2021-01-01', periods=2, freq='D'))
        rf_other = pd.Series([0.0001, 0.0001],
                             index=pd.date_range('2021-06-01', periods=2, freq='D'))
        with pytest.raises(ValueError):
            model.predict(market_log_returns=mkt, rf_log_returns=rf_other)

    def test_fit_recovers_beta(self):
        model = CAPMModel()
        stock, market, rf = _make_capm_data(100, beta=1.3)
        model.fit(stock_log_returns=stock, market_log_returns=market, rf_log_returns=rf)
        assert model._beta == pytest.approx(1.3, abs=1e-10)

    def test_predict_applies_capm_formula(self):
        model = CAPMModel()
        stock, market, rf = _make_capm_data(50, beta=1.3)
        model.fit(stock_log_returns=stock, market_log_returns=market, rf_log_returns=rf)

        new_idx = pd.date_range('2021-01-01', periods=5, freq='D')
        new_market = pd.Series([0.01, -0.02, 0.03, 0.0, 0.015], index=new_idx)
        new_rf = pd.Series([0.0002] * 5, index=new_idx)
        result = model.predict(market_log_returns=new_market, rf_log_returns=new_rf)

        expected_values = new_rf.values + 1.3 * (new_market.values - new_rf.values)
        np.testing.assert_allclose(result.values, expected_values, rtol=1e-10)
        assert result.index.equals(new_idx)

    def test_refit_updates_beta(self):
        model = CAPMModel()
        stock1, market1, rf1 = _make_capm_data(50, beta=1.0)
        model.fit(stock_log_returns=stock1, market_log_returns=market1, rf_log_returns=rf1)

        stock2, market2, rf2 = _make_capm_data(50, beta=2.0)
        model.fit(stock_log_returns=stock2, market_log_returns=market2, rf_log_returns=rf2)

        assert model._beta == pytest.approx(2.0, abs=1e-10)

    def test_fit_ignores_extra_kwargs(self):
        model = CAPMModel()
        stock, market, rf = _make_capm_data(20, beta=1.0)
        model.fit(
            stock_log_returns=stock,
            market_log_returns=market,
            rf_log_returns=rf,
            some_other_kwarg=42,
        )
