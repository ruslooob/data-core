"""Тесты этапа R6 — перевод сущностей между общей и приватной видимостью.

PATCH /api/{strategies,rules,environments}/{id}/research принимает
researchId (null = сделать общей; UUID = приватной указанного исследования).
Перевод общая → приватная блокируется, если на сущность ссылаются прогоны
*других* исследований.
"""
from __future__ import annotations

import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.postgres_db import PG_DSN
from main import app
from routers._common import DEFAULT_RESEARCH_ID

client = TestClient(app)


def _pg():
    return psycopg.connect(PG_DSN, autocommit=True)


@pytest.fixture
def fresh_research():
    rid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [rid, f'scope-{rid}'])
    yield rid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id = %s', [rid])


@pytest.fixture
def common_strategy():
    sid = str(uuid.uuid4())
    name = f'common-strat-{sid}'
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, research_id) '
            'VALUES (%s, %s, %s, NULL)',
            [sid, name, '2026-01-01T00:00:00+00:00'],
        )
    yield sid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM strategies WHERE id = %s', [sid])


@pytest.fixture
def common_environment():
    eid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO environments '
            '(id, name, date_start, date_end, starting_capital, created_at, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, NULL)',
            [eid, f'common-env-{eid}', date(2020, 1, 1), date(2020, 12, 31),
             1_000_000.0, '2026-01-01T00:00:00+00:00'],
        )
    yield eid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM environments WHERE id = %s', [eid])


@pytest.fixture
def common_rule():
    rid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO rules '
            '(id, name, trigger_sql, action_type, action_quantity_sql, priority, '
            ' created_at, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)',
            [rid, f'common-rule-{rid}', 'SELECT 1', 'buy', 'SELECT 1',
             10, '2026-01-01T00:00:00+00:00'],
        )
    yield rid
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM rules WHERE id = %s', [rid])


# ── happy-path: common → private → common ─────────────────────────────────

def test_strategy_common_to_private_then_back(common_strategy, fresh_research):
    sid = common_strategy
    rid = fresh_research

    r1 = client.patch(f'/api/strategies/{sid}/research', json={'researchId': rid})
    assert r1.status_code == 200
    assert r1.json()['researchId'] == rid

    r2 = client.patch(f'/api/strategies/{sid}/research', json={'researchId': None})
    assert r2.status_code == 200
    assert r2.json()['researchId'] is None


def test_rule_common_to_private(common_rule, fresh_research):
    r = client.patch(f'/api/rules/{common_rule}/research', json={'researchId': fresh_research})
    assert r.status_code == 200
    assert r.json()['researchId'] == fresh_research


def test_environment_common_to_private(common_environment, fresh_research):
    r = client.patch(
        f'/api/environments/{common_environment}/research',
        json={'researchId': fresh_research},
    )
    assert r.status_code == 200
    assert r.json()['researchId'] == fresh_research


# ── валидация целевого research ────────────────────────────────────────────

def test_unknown_research_returns_404(common_strategy):
    fake = str(uuid.uuid4())
    r = client.patch(f'/api/strategies/{common_strategy}/research', json={'researchId': fake})
    assert r.status_code == 404


# ── инвариант: блок при чужих прогонах ─────────────────────────────────────

def _create_alien_run(con, *, strategy_id, environment_id, alien_research_id):
    """Вставляет фиктивный backtest_result в чужое исследование."""
    rid = str(uuid.uuid4())
    con.execute(
        'INSERT INTO backtest_results '
        '(id, strategy_id, environment_id, created_at, total_return_pct, annual_return_pct, '
        ' max_drawdown_pct, sharpe, n_trades, profit_factor, win_rate_pct, research_id) '
        'VALUES (%s, %s, %s, %s, 0, 0, 0, 0, 0, NULL, NULL, %s)',
        [rid, strategy_id, environment_id, '2026-01-01T00:00:00+00:00', alien_research_id],
    )
    return rid


def test_strategy_blocked_when_alien_run_exists(common_strategy, common_environment):
    """Прогон в `Default` блокирует попытку привязать общую стратегию к новому
    исследованию."""
    sid = common_strategy
    new_research = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [new_research, f'r-{new_research}'])
        run_id = _create_alien_run(
            cur, strategy_id=sid, environment_id=common_environment,
            alien_research_id=DEFAULT_RESEARCH_ID,
        )

    try:
        r = client.patch(f'/api/strategies/{sid}/research', json={'researchId': new_research})
        assert r.status_code == 409
    finally:
        with _pg() as con, con.cursor() as cur:
            cur.execute('DELETE FROM backtest_results WHERE id = %s', [run_id])
            cur.execute('DELETE FROM research WHERE id = %s', [new_research])


def test_environment_blocked_when_alien_run_exists(common_strategy, common_environment):
    eid = common_environment
    new_research = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [new_research, f'r-{new_research}'])
        run_id = _create_alien_run(
            cur, strategy_id=common_strategy, environment_id=eid,
            alien_research_id=DEFAULT_RESEARCH_ID,
        )

    try:
        r = client.patch(f'/api/environments/{eid}/research', json={'researchId': new_research})
        assert r.status_code == 409
    finally:
        with _pg() as con, con.cursor() as cur:
            cur.execute('DELETE FROM backtest_results WHERE id = %s', [run_id])
            cur.execute('DELETE FROM research WHERE id = %s', [new_research])


def test_rule_blocked_when_alien_run_via_strategy(common_rule, common_strategy, common_environment):
    """Если правило входит в стратегию, по которой есть прогон в чужом
    исследовании — нельзя сделать правило приватным."""
    rule_id = common_rule
    sid = common_strategy
    new_research = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [new_research, f'r-{new_research}'])
        cur.execute(
            'INSERT INTO strategy_rules (strategy_id, rule_id, position) VALUES (%s, %s, %s)',
            [sid, rule_id, 0],
        )
        run_id = _create_alien_run(
            cur, strategy_id=sid, environment_id=common_environment,
            alien_research_id=DEFAULT_RESEARCH_ID,
        )

    try:
        r = client.patch(f'/api/rules/{rule_id}/research', json={'researchId': new_research})
        assert r.status_code == 409
    finally:
        with _pg() as con, con.cursor() as cur:
            cur.execute('DELETE FROM backtest_results WHERE id = %s', [run_id])
            cur.execute('DELETE FROM strategy_rules WHERE strategy_id = %s AND rule_id = %s', [sid, rule_id])
            cur.execute('DELETE FROM research WHERE id = %s', [new_research])


def test_make_common_always_allowed(common_strategy, common_environment, fresh_research):
    """Перевод приватная → общая разрешён всегда (расширение видимости),
    даже если есть прогоны привязанные к этому исследованию."""
    sid = common_strategy
    rid = fresh_research

    # Сделаем приватной для fresh_research
    client.patch(f'/api/strategies/{sid}/research', json={'researchId': rid})

    # Создадим прогон, привязанный к этому же исследованию
    with _pg() as con, con.cursor() as cur:
        run_id = _create_alien_run(
            cur, strategy_id=sid, environment_id=common_environment, alien_research_id=rid,
        )

    try:
        r = client.patch(f'/api/strategies/{sid}/research', json={'researchId': None})
        assert r.status_code == 200
        assert r.json()['researchId'] is None
    finally:
        with _pg() as con, con.cursor() as cur:
            cur.execute('DELETE FROM backtest_results WHERE id = %s', [run_id])
