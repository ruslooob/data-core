"""Тесты численной эквивалентности UDF car() с прямым вызовом
EventStudy.analyze для всех трёх моделей. Граничный случай:
неизвестный тикер → NULL.

PQL исполняется через REST-эндпоинт `POST /api/precedents/search` —
он и есть публичный контракт после миграции на Postgres.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from core.event_study import EventStudy
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider
from main import app

TICKER = 'LKOH'
EVENT_DATE = date(2022, 12, 16)
EVENT_DATE_SQL = "DATE '2022-12-16'"


@pytest.fixture(scope='module')
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope='module')
def stock_returns():
    return StockDataProvider().get_log_returns(TICKER)


@pytest.fixture(scope='module')
def market_returns():
    return MarketDataProvider().load_market_index_log_returns()


@pytest.fixture(scope='module')
def rf_returns():
    return MarketDataProvider().load_daily_risk_free_rate()


def _query_scalar(client: TestClient, sql: str):
    r = client.post('/api/precedents/search', json={'source': sql})
    assert r.status_code == 200, r.text
    rows = r.json()['rows']
    assert len(rows) == 1
    return rows[0][0]


def _query_row(client: TestClient, sql: str):
    r = client.post('/api/precedents/search', json={'source': sql})
    assert r.status_code == 200, r.text
    rows = r.json()['rows']
    assert len(rows) == 1
    return rows[0]


def _direct_car(
        stock,
        market,
        rf,
        model: str,
        window_before: int = 5,
        window_after: int = 5,
        estimation: int = 200,
) -> float:
    es = EventStudy(stock_log_returns=stock)
    result = es.analyze(
        event_date=EVENT_DATE,
        model=model,
        event_window=(-window_before, window_after),
        estimation_window=estimation,
        market=market if model in ('market_model', 'capm') else None,
        rf=rf if model == 'capm' else None,
    )
    assert result is not None, f"EventStudy.analyze вернул None для модели {model}"
    return float(result.car)


def test_car_default_model_equals_market_model(client, stock_returns, market_returns):
    sql_value = _query_scalar(client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL})")
    direct_value = _direct_car(stock_returns, market_returns, None, 'market_model')
    assert sql_value == pytest.approx(direct_value, abs=1e-12)


def test_car_market_model_explicit(client, stock_returns, market_returns):
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, model => 'market_model')"
    )
    direct_value = _direct_car(stock_returns, market_returns, None, 'market_model')
    assert sql_value == pytest.approx(direct_value, abs=1e-12)


def test_car_mean_adjusted_model(client, stock_returns):
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, model => 'mean_adjusted')"
    )
    direct_value = _direct_car(stock_returns, None, None, 'mean_adjusted')
    assert sql_value == pytest.approx(direct_value, abs=1e-12)


def test_car_capm_model(client, stock_returns, market_returns, rf_returns):
    sql_value = _query_scalar(
        client, f"SELECT car('{TICKER}', {EVENT_DATE_SQL}, model => 'capm')"
    )
    direct_value = _direct_car(stock_returns, market_returns, rf_returns, 'capm')
    assert sql_value == pytest.approx(direct_value, abs=1e-12)


def test_car_three_models_produce_different_values(client):
    """Базовая проверка: три модели не дают идентичных результатов."""
    row = _query_row(client, f"""
        SELECT car('{TICKER}', {EVENT_DATE_SQL}, model => 'mean_adjusted'),
               car('{TICKER}', {EVENT_DATE_SQL}, model => 'market_model'),
               car('{TICKER}', {EVENT_DATE_SQL}, model => 'capm')
    """)
    assert all(v is not None for v in row)
    # Хотя бы две из трёх моделей должны различаться
    assert len({round(v, 8) for v in row}) >= 2


def test_car_returns_null_for_unknown_ticker(client):
    assert _query_scalar(client, f"SELECT car('NOTAREAL', {EVENT_DATE_SQL})") is None


def test_car_returns_null_for_too_early_date(client):
    """Дата раньше начала истории по тикеру → недостаточно данных → NULL."""
    assert _query_scalar(client, f"SELECT car('{TICKER}', DATE '1990-01-01')") is None


def test_car_with_custom_windows(client, stock_returns, market_returns):
    sql_value = _query_scalar(client, f"""
        SELECT car('{TICKER}', {EVENT_DATE_SQL},
                   window_before => 10, window_after => 10, estimation => 250)
    """)
    direct_value = _direct_car(
        stock_returns, market_returns, None, 'market_model',
        window_before=10, window_after=10, estimation=250,
    )
    assert sql_value == pytest.approx(direct_value, abs=1e-12)


def test_car_in_where_clause(client):
    """car() корректно вызывается в WHERE и пропускает только нужные строки."""
    n = _query_scalar(client, f"""
        SELECT COUNT(*) FROM (
            SELECT car('{TICKER}', {EVENT_DATE_SQL}) AS c
        ) AS t WHERE c IS NOT NULL AND c < 0
    """)
    assert n == 1  # CAR LKOH 2022-12-16 — отрицательный, не NULL


def test_car_in_order_by(client):
    """car() корректно вызывается в ORDER BY."""
    r = client.post('/api/precedents/search', json={'source': f"""
        SELECT model, car('{TICKER}', {EVENT_DATE_SQL}, model => model) AS c
        FROM (VALUES ('mean_adjusted'), ('market_model'), ('capm')) AS t(model)
        ORDER BY c DESC
    """})
    assert r.status_code == 200, r.text
    rows = r.json()['rows']
    values = [r[1] for r in rows]
    assert values == sorted(values, reverse=True)
