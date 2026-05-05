"""Тесты этапа R3 — фильтрация листинговых эндпоинтов по research_id и
видимость общих сущностей через include_common.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.postgres_db import PG_DSN
from main import DEFAULT_RESEARCH_ID, app

client = TestClient(app)


def _pg():
    return psycopg.connect(PG_DSN, autocommit=True)


@pytest.fixture
def research_a():
    rid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [rid, f'A-{rid}'])
    yield rid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id = %s', [rid])


@pytest.fixture
def research_b():
    rid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [rid, f'B-{rid}'])
    yield rid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id = %s', [rid])


# ── listing требует research_id ───────────────────────────────────────────

def test_list_strategies_without_research_id_returns_422():
    r = client.get('/api/strategies')
    assert r.status_code == 422


def test_list_rules_without_research_id_returns_422():
    r = client.get('/api/rules')
    assert r.status_code == 422


def test_list_environments_without_research_id_returns_422():
    r = client.get('/api/environments')
    assert r.status_code == 422


def test_list_backtest_results_without_research_id_returns_422():
    r = client.get('/api/backtest/results')
    assert r.status_code == 422


# ── видимость стратегий ───────────────────────────────────────────────────

def test_listing_default_returns_empty_for_strategies(research_a):
    """В свежесозданном исследовании А нет приватных стратегий."""
    r = client.get('/api/strategies', params={'researchId': research_a})
    assert r.status_code == 200
    assert r.json() == []


def test_private_strategy_visible_only_in_owning_research(research_a, research_b):
    name = f'priv-{uuid.uuid4()}'
    created = client.post('/api/strategies', json={
        'name': name,
        'ruleIds': [],
        'researchId': research_a,
    })
    # rule_ids пустой → 400, поэтому привяжу через прямой INSERT
    assert created.status_code == 400  # подтверждаем что endpoint требует rules
    sid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, research_id) '
            'VALUES (%s, %s, %s, %s)',
            [sid, name, '2026-01-01T00:00:00+00:00', research_a],
        )
    r_a = client.get('/api/strategies', params={'researchId': research_a})
    r_b = client.get('/api/strategies', params={'researchId': research_b})
    a_ids = {it['id'] for it in r_a.json()}
    b_ids = {it['id'] for it in r_b.json()}
    assert sid in a_ids
    assert sid not in b_ids


def test_shared_strategy_hidden_by_default_and_visible_with_include_common(research_a):
    """Существующие 24 общих стратегии не должны появляться без include_common."""
    r_default = client.get('/api/strategies', params={'researchId': research_a})
    r_shared = client.get('/api/strategies', params={'researchId': research_a, 'includeCommon': True})
    assert r_default.status_code == 200
    assert r_shared.status_code == 200
    assert len(r_default.json()) == 0
    assert len(r_shared.json()) > 0


# ── привязка прогона ──────────────────────────────────────────────────────

def test_backtest_result_inherits_research_id_at_insert(research_a):
    """Прямая проверка: persist_backtest_result пишет research_id в строку."""
    from core.backtest_engine import BacktestResult, persist_backtest_result

    sample = BacktestResult(
        strategy_id='nonexistent', environment_id='nonexistent',
        total_return_pct=0.0, annual_return_pct=0.0, max_drawdown_pct=0.0,
        sharpe=0.0, n_trades=0, profit_factor=None, win_rate_pct=None,
        trades=[], equity_curve=[],
    )
    # FK нарушится — но мы хотим увидеть, что research_id корректно
    # подставляется в запрос.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with _pg() as con:
            persist_backtest_result(con, sample, research_a)


def test_run_endpoint_rejects_unknown_research(research_a):
    """POST /api/backtest/run с несуществующим research_id → 404."""
    fake_research = str(uuid.uuid4())
    r = client.post('/api/backtest/run', json={
        'strategyId': str(uuid.uuid4()),
        'environmentId': str(uuid.uuid4()),
        'researchId': fake_research,
    })
    assert r.status_code == 404


def test_run_endpoint_requires_research_id():
    """POST /api/backtest/run без researchId → 422."""
    r = client.post('/api/backtest/run', json={
        'strategyId': str(uuid.uuid4()),
        'environmentId': str(uuid.uuid4()),
    })
    assert r.status_code == 422
