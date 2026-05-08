"""Тесты UDF в Postgres: vol_ratio, volume_ratio + расширенный car().

После миграции с DuckDB на Postgres движок прецедентов исполняет SQL
через REST-эндпоинт `POST /api/precedents/search`. Тесты дёргают
именно этот эндпоинт — он и есть публичный контракт PQL.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from core.stock_data_provider import StockDataProvider
from main import app

TICKER = 'LKOH'
EVENT_DATE = date(2022, 12, 16)
EVENT_DATE_SQL = "DATE '2022-12-16'"


@pytest.fixture(scope='module')
def stocks() -> StockDataProvider:
    return StockDataProvider()


@pytest.fixture(scope='module')
def client() -> TestClient:
    return TestClient(app)


def _query_scalar(client: TestClient, sql: str):
    r = client.post('/api/precedents/search', json={'source': sql})
    assert r.status_code == 200, r.text
    rows = r.json()['rows']
    assert len(rows) == 1, f'ожидалась одна строка, получено {len(rows)}'
    return rows[0][0]


# ---------- vol_ratio ----------

def test_vol_ratio_sql_matches_direct(client, stocks):
    sql_value = _query_scalar(client, f"SELECT vol_ratio('{TICKER}', {EVENT_DATE_SQL})")
    direct_value = stocks.vol_ratio(TICKER, EVENT_DATE)
    assert sql_value == pytest.approx(direct_value)


def test_vol_ratio_returns_null_for_unknown_ticker(client):
    assert _query_scalar(client, f"SELECT vol_ratio('NOTAREAL', {EVENT_DATE_SQL})") is None


def test_vol_ratio_returns_null_for_too_early_date(client):
    assert _query_scalar(client, f"SELECT vol_ratio('{TICKER}', DATE '1990-01-01')") is None


def test_vol_ratio_custom_windows(client, stocks):
    sql_value = _query_scalar(
        client,
        f"SELECT vol_ratio('{TICKER}', {EVENT_DATE_SQL}, window_before => 10, window_after => 10)",
    )
    direct_value = stocks.vol_ratio(TICKER, EVENT_DATE, window_before=10, window_after=10)
    assert sql_value == pytest.approx(direct_value)


# ---------- volume_ratio ----------

def test_volume_ratio_sql_matches_direct(client, stocks):
    sql_value = _query_scalar(client, f"SELECT volume_ratio('{TICKER}', {EVENT_DATE_SQL})")
    direct_value = stocks.volume_ratio(TICKER, EVENT_DATE)
    assert sql_value == pytest.approx(direct_value)


def test_volume_ratio_returns_null_for_unknown_ticker(client):
    assert _query_scalar(client, f"SELECT volume_ratio('NOTAREAL', {EVENT_DATE_SQL})") is None


def test_volume_ratio_custom_windows(client, stocks):
    sql_value = _query_scalar(
        client,
        f"SELECT volume_ratio('{TICKER}', {EVENT_DATE_SQL}, window_before => 20, window_after => 5)",
    )
    direct_value = stocks.volume_ratio(TICKER, EVENT_DATE, window_before=20, window_after=5)
    assert sql_value == pytest.approx(direct_value)


# ---------- car() с отрицательными окнами (только до события) ----------

def test_car_pre_only_window(client):
    """car(ticker, date, window_after => -1) считает CAR на [-window_before, -1] — только до события."""
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_after => -1)"
    )
    assert sql_value is not None
    assert isinstance(sql_value, float)


def test_car_post_only_window(client):
    """car(ticker, date, window_before => -1) считает CAR на [+1, +window_after] — только после события."""
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => -1)"
    )
    assert sql_value is not None
    assert isinstance(sql_value, float)


def test_car_pre_only_differs_from_post_only(client):
    """Pre-only и post-only окна обычно дают разные CAR — окна не пересекаются."""
    pre = _query_scalar(client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_after => -1)")
    post = _query_scalar(client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => -1)")
    assert pre != post


def test_car_empty_window_returns_null(client):
    """Окно с пустым интервалом ([-2, -3]) возвращает None."""
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, window_before => 2, window_after => -3)"
    )
    assert sql_value is None
