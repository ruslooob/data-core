"""Тесты новых UDF в PrecedentEngine: vol_ratio, volume_ratio + расширенный car()."""
from __future__ import annotations

from datetime import date

import pytest

from core.market_data_provider import MarketDataProvider
from core.precedent_engine import PrecedentEngine
from core.stock_data_provider import StockDataProvider

TICKER = 'LKOH'
EVENT_DATE = date(2022, 12, 16)
EVENT_DATE_SQL = "DATE '2022-12-16'"


@pytest.fixture(scope='module')
def stocks() -> StockDataProvider:
    return StockDataProvider()


@pytest.fixture(scope='module')
def con(stocks):
    return PrecedentEngine(stocks, MarketDataProvider()).con


# ---------- vol_ratio ----------

def test_vol_ratio_sql_matches_direct(con, stocks):
    sql_value = con.execute(
        f"SELECT vol_ratio('{TICKER}', {EVENT_DATE_SQL})"
    ).fetchone()[0]
    direct_value = stocks.vol_ratio(TICKER, EVENT_DATE)
    assert sql_value == pytest.approx(direct_value)


def test_vol_ratio_returns_null_for_unknown_ticker(con):
    sql_value = con.execute(
        f"SELECT vol_ratio('NOTAREAL', {EVENT_DATE_SQL})"
    ).fetchone()[0]
    assert sql_value is None


def test_vol_ratio_returns_null_for_too_early_date(con):
    sql_value = con.execute(
        f"SELECT vol_ratio('{TICKER}', DATE '1990-01-01')"
    ).fetchone()[0]
    assert sql_value is None


def test_vol_ratio_custom_windows(con, stocks):
    sql_value = con.execute(
        f"SELECT vol_ratio('{TICKER}', {EVENT_DATE_SQL}, window_before => 10, window_after => 10)"
    ).fetchone()[0]
    direct_value = stocks.vol_ratio(TICKER, EVENT_DATE, window_before=10, window_after=10)
    assert sql_value == pytest.approx(direct_value)


# ---------- volume_ratio ----------

def test_volume_ratio_sql_matches_direct(con, stocks):
    sql_value = con.execute(
        f"SELECT volume_ratio('{TICKER}', {EVENT_DATE_SQL})"
    ).fetchone()[0]
    direct_value = stocks.volume_ratio(TICKER, EVENT_DATE)
    assert sql_value == pytest.approx(direct_value)


def test_volume_ratio_returns_null_for_unknown_ticker(con):
    sql_value = con.execute(
        f"SELECT volume_ratio('NOTAREAL', {EVENT_DATE_SQL})"
    ).fetchone()[0]
    assert sql_value is None


def test_volume_ratio_custom_windows(con, stocks):
    sql_value = con.execute(
        f"SELECT volume_ratio('{TICKER}', {EVENT_DATE_SQL}, window_before => 20, window_after => 5)"
    ).fetchone()[0]
    direct_value = stocks.volume_ratio(TICKER, EVENT_DATE, window_before=20, window_after=5)
    assert sql_value == pytest.approx(direct_value)


# ---------- car() с отрицательными окнами (только до события) ----------

def test_car_pre_only_window(con):
    """car(ticker, date, window_after => -1) считает CAR на [-window_before, -1] — только до события."""
    sql_value = con.execute(
        f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_after => -1)"
    ).fetchone()[0]
    assert sql_value is not None
    assert isinstance(sql_value, float)


def test_car_post_only_window(con):
    """car(ticker, date, window_before => -1) считает CAR на [+1, +window_after] — только после события."""
    sql_value = con.execute(
        f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => -1)"
    ).fetchone()[0]
    assert sql_value is not None
    assert isinstance(sql_value, float)


def test_car_pre_only_differs_from_post_only(con):
    """Pre-only и post-only окна обычно дают разные CAR — окна не пересекаются."""
    pre = con.execute(
        f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_after => -1)"
    ).fetchone()[0]
    post = con.execute(
        f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => -1)"
    ).fetchone()[0]
    assert pre != post


def test_car_empty_window_returns_null(con):
    """Окно с пустым интервалом ([-2, -3]) возвращает None."""
    sql_value = con.execute(
        f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => 2, window_after => -3)"
    ).fetchone()[0]
    assert sql_value is None
