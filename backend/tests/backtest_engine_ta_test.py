"""Тесты оконных TA-функций движка бэктеста: sma, volume_sma, volatility,
return_n_days. Все четыре используют окно [date - window, date - 1] —
правая граница (саму дату) не включают."""
from __future__ import annotations

import math
import os
from datetime import date

import numpy as np
import pytest

from core import stock_data_provider
from core.backtest_engine import BacktestEngine
from core.stock_data_provider import StockDataProvider

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'stocks')


@pytest.fixture(autouse=True)
def patch_stock_paths(monkeypatch):
    monkeypatch.setattr(stock_data_provider, 'STOCKS_FOLDER', FIXTURES_DIR)
    monkeypatch.setattr(
        stock_data_provider, '_SPLITS_PATH',
        os.path.join(FIXTURES_DIR, 'splits.json'),
    )


class _StubEngine:
    """Лёгкий хост методов TA-функций без полной инициализации BacktestEngine.

    BacktestEngine.__init__ читает persistent-БД и dividends CSV, что не
    нужно в чистых юнит-тестах TA-функций. Прокидываем только `_stocks` и
    переиспользуем методы класса напрямую."""

    def __init__(self, stocks: StockDataProvider):
        self._stocks = stocks

    _window_slice = BacktestEngine._window_slice
    _sma = BacktestEngine._sma
    _volume_sma = BacktestEngine._volume_sma
    _volatility = BacktestEngine._volatility
    _return_n_days = BacktestEngine._return_n_days


@pytest.fixture
def engine() -> _StubEngine:
    return _StubEngine(StockDataProvider())


# ── sma ────────────────────────────────────────────────────────────────────

def test_sma_excludes_target_date(engine):
    """`sma(ticker, d, n)` берёт n строк СТРОГО ДО `d`. Сама `d` не входит.

    В фикстуре close: 101..110 на торговых днях 2020-01-02..2020-01-15.
    На дату 2020-01-08 окно n=3 = (2020-01-03, 06, 07) → close = 102, 103, 104 → mean = 103.
    """
    assert engine._sma('TEST', date(2020, 1, 8), 3) == pytest.approx(103.0)


def test_sma_returns_none_when_not_enough_history(engine):
    """До даты 2020-01-03 был только один торговый день (2020-01-02).
    Просим окно 5 — данных не хватает → None."""
    assert engine._sma('TEST', date(2020, 1, 3), 5) is None


def test_sma_returns_none_for_unknown_ticker(engine):
    assert engine._sma('NOPE', date(2020, 1, 8), 3) is None


def test_sma_returns_none_for_zero_window(engine):
    assert engine._sma('TEST', date(2020, 1, 8), 0) is None


# ── volume_sma ────────────────────────────────────────────────────────────

def test_volume_sma(engine):
    """В фикстуре volume = 1000 + 100*i на торговых днях. На 2020-01-08 окно 3 =
    (1100, 1200, 1300) → mean = 1200."""
    assert engine._volume_sma('TEST', date(2020, 1, 8), 3) == pytest.approx(1200.0)


def test_volume_sma_excludes_target_date(engine):
    """Smoke: сама дата не должна попадать в окно. На 2020-01-09, n=2 →
    (2020-01-07, 08) → vol (1300, 1400) → mean 1350. Если бы включалась
    сама дата — было бы (1400, 1500) = 1450."""
    assert engine._volume_sma('TEST', date(2020, 1, 9), 2) == pytest.approx(1350.0)


# ── volatility ────────────────────────────────────────────────────────────

def test_volatility_matches_manual_std(engine):
    """std дневных лог-доходностей за последние n дней (ddof=1).
    На 2020-01-10, окно 5 → берём log_returns на 2020-01-03..2020-01-09 = 5
    значений (т.к. log_returns пропускает первую дату 2020-01-02).
    Сверка с numpy."""
    stocks = engine._stocks
    log_ret = stocks.get_log_returns('TEST')
    import pandas as pd
    target = pd.Timestamp(date(2020, 1, 10))
    expected = float(log_ret[log_ret.index < target].tail(5).std(ddof=1))
    assert engine._volatility('TEST', date(2020, 1, 10), 5) == pytest.approx(expected)


def test_volatility_none_when_not_enough_days(engine):
    """Просим 100 дней истории — нет такого."""
    assert engine._volatility('TEST', date(2020, 1, 10), 100) is None


def test_volatility_window_must_be_at_least_two(engine):
    """Std из одной точки не определена → None."""
    assert engine._volatility('TEST', date(2020, 1, 10), 1) is None


# ── return_n_days ─────────────────────────────────────────────────────────

def test_return_n_days_3(engine):
    """В фикстуре close на 2020-01-13 = 108, на 2020-01-08 = 105.
    Окно n=3 берёт log_returns на 2020-01-09, 10, 13 (СТРОГО ДО даты).
    Накопленная доходность = exp(Σ log_ret) − 1.

    На 2020-01-14 (target) окно n=3 → log_returns на 2020-01-10, 13, 14 = 3
    последних значений до 2020-01-14 (НЕ включая 14).
    """
    import pandas as pd
    log_ret = engine._stocks.get_log_returns('TEST')
    target = pd.Timestamp(date(2020, 1, 14))
    expected = float(np.exp(log_ret[log_ret.index < target].tail(3).sum()) - 1.0)
    assert engine._return_n_days('TEST', date(2020, 1, 14), 3) == pytest.approx(expected)


def test_return_n_days_none_for_too_large_n(engine):
    assert engine._return_n_days('TEST', date(2020, 1, 14), 100) is None


def test_return_n_days_none_for_zero(engine):
    assert engine._return_n_days('TEST', date(2020, 1, 14), 0) is None


# ── общие проверки ────────────────────────────────────────────────────────

def test_all_functions_accept_none_args(engine):
    """Если ticker/date/window None — функция не падает, возвращает None."""
    assert engine._sma(None, date(2020, 1, 8), 3) is None
    assert engine._sma('TEST', None, 3) is None
    assert engine._sma('TEST', date(2020, 1, 8), None) is None
    assert engine._volume_sma(None, date(2020, 1, 8), 3) is None
    assert engine._volatility(None, date(2020, 1, 8), 3) is None
    assert engine._return_n_days(None, date(2020, 1, 8), 3) is None
