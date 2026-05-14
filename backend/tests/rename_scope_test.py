"""Smoke-тест на уникальность имён при rename: PATCH /{id} проверяет
дубликат в пределах своей области (исследование или «общие»), а не
глобально.

Контракт из SPEC_BACKTEST.md, §6.2:
- внутри одного исследования имена уникальны (`(research_id, name)`);
- среди общих сущностей (`research_id IS NULL`) — отдельная уникальность;
- одно и то же имя одновременно может существовать как общее и как
  приватное одного или нескольких исследований.

Поэтому переименование в имя, занятое в *чужой* области, — допустимо.
"""
from __future__ import annotations

import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.postgres_db import PG_DSN
from main import app

client = TestClient(app)


def _pg():
    return psycopg.connect(PG_DSN, autocommit=True)


@pytest.fixture
def two_researches():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [a, f'rename-a-{a}'])
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [b, f'rename-b-{b}'])
    yield a, b
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id IN (%s, %s)', [a, b])


def _create_strategy(name: str, research_id: str) -> str:
    sid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, research_id) '
            'VALUES (%s, %s, %s, %s)',
            [sid, name, '2026-01-01T00:00:00+00:00', research_id],
        )
    return sid


def _create_rule(name: str, research_id: str) -> str:
    rid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO rules '
            '(id, name, trigger_sql, action_type, action_quantity_sql, priority, '
            ' created_at, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            [rid, name, 'SELECT 1', 'buy', 'SELECT 1', 10,
             '2026-01-01T00:00:00+00:00', research_id],
        )
    return rid


def _create_environment(name: str, research_id: str) -> str:
    eid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO environments '
            '(id, name, date_start, date_end, starting_capital, created_at, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            [eid, name, date(2020, 1, 1), date(2020, 12, 31),
             1_000_000.0, '2026-01-01T00:00:00+00:00', research_id],
        )
    return eid


# ── Strategy ──────────────────────────────────────────────────────────────

def test_rename_strategy_to_name_used_in_other_research(two_researches):
    """В исследовании B можно переименовать стратегию в имя, занятое в A."""
    a, b = two_researches
    _create_strategy('shared-name', a)
    sid_b = _create_strategy('original', b)

    r = client.patch(f'/api/strategies/{sid_b}', json={'name': 'shared-name'})
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'shared-name'


def test_rename_strategy_to_name_used_in_same_research(two_researches):
    """В одном исследовании нельзя занять имя другой стратегии того же исследования."""
    a, _ = two_researches
    _create_strategy('first', a)
    sid = _create_strategy('second', a)

    r = client.patch(f'/api/strategies/{sid}', json={'name': 'first'})
    assert r.status_code == 409


# ── Rule ──────────────────────────────────────────────────────────────────

def test_rename_rule_to_name_used_in_other_research(two_researches):
    a, b = two_researches
    _create_rule('shared-rule', a)
    rid_b = _create_rule('original', b)

    r = client.patch(f'/api/rules/{rid_b}', json={'name': 'shared-rule'})
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'shared-rule'


def test_rename_rule_to_name_used_in_same_research(two_researches):
    a, _ = two_researches
    _create_rule('first', a)
    rid = _create_rule('second', a)

    r = client.patch(f'/api/rules/{rid}', json={'name': 'first'})
    assert r.status_code == 409


# ── Environment ───────────────────────────────────────────────────────────

def test_rename_environment_to_name_used_in_other_research(two_researches):
    a, b = two_researches
    _create_environment('shared-env', a)
    eid_b = _create_environment('original', b)

    r = client.patch(f'/api/environments/{eid_b}', json={'name': 'shared-env'})
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'shared-env'


def test_rename_environment_to_name_used_in_same_research(two_researches):
    a, _ = two_researches
    _create_environment('first', a)
    eid = _create_environment('second', a)

    r = client.patch(f'/api/environments/{eid}', json={'name': 'first'})
    assert r.status_code == 409
