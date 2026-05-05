"""Тесты этапа R7 — отчёт по исследованию (markdown).

GET /api/research/{id}/report возвращает text/markdown.
"""
from __future__ import annotations

import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.postgres_db import PG_DSN
from main import DEFAULT_RESEARCH_ID, app

client = TestClient(app)


def _pg():
    return psycopg.connect(PG_DSN, autocommit=True)


@pytest.fixture
def research_with_artifacts():
    rid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    eid = str(uuid.uuid4())
    rule_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    name = f'report-test-{rid}'
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO research (id, name, description, conclusion) '
            'VALUES (%s, %s, %s, %s)',
            [rid, name, 'Описание идеи исследования.', 'Финальные выводы.'],
        )
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, description, research_id) '
            'VALUES (%s, %s, %s, %s, %s)',
            [sid, f's-{sid}', '2026-01-01T00:00:00+00:00', 'desc s', rid],
        )
        cur.execute(
            'INSERT INTO rules '
            '(id, name, trigger_sql, action_type, action_quantity_sql, priority, '
            ' created_at, description, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [rule_id, f'r-{rule_id}', 'SELECT 1', 'buy', 'SELECT 1', 10,
             '2026-01-01T00:00:00+00:00', 'desc r', rid],
        )
        cur.execute(
            'INSERT INTO environments '
            '(id, name, date_start, date_end, starting_capital, created_at, description, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            [eid, f'env-{eid}', date(2020, 1, 1), date(2020, 12, 31),
             1_000_000.0, '2026-01-01T00:00:00+00:00', 'desc env', rid],
        )
        cur.execute(
            'INSERT INTO backtest_results '
            '(id, strategy_id, environment_id, created_at, total_return_pct, '
            ' annual_return_pct, max_drawdown_pct, sharpe, n_trades, profit_factor, '
            ' win_rate_pct, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [run_id, sid, eid, '2026-01-02T10:00:00+00:00',
             12.5, 15.0, 8.0, 1.2, 42, 1.5, 60.0, rid],
        )
    yield {'research_id': rid, 'name': name, 'strategy_id': sid, 'env_id': eid,
           'rule_id': rule_id, 'run_id': run_id}
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id = %s', [rid])


def test_report_unknown_research_returns_404():
    fake = str(uuid.uuid4())
    r = client.get(f'/api/research/{fake}/report')
    assert r.status_code == 404


def test_report_default_returns_200():
    r = client.get(f'/api/research/{DEFAULT_RESEARCH_ID}/report')
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/markdown')
    assert 'Default' in r.text


def test_report_includes_all_sections(research_with_artifacts):
    a = research_with_artifacts
    r = client.get(f'/api/research/{a["research_id"]}/report')
    assert r.status_code == 200
    text = r.text
    assert f'# {a["name"]}' in text
    assert 'Описание идеи исследования.' in text
    assert '## Приватные стратегии' in text
    assert '## Приватные правила' in text
    assert '## Приватные окружения' in text
    assert '## Прогоны' in text
    assert '## Выводы' in text
    assert 'Финальные выводы.' in text


def test_report_skips_empty_sections():
    rid = str(uuid.uuid4())
    name = f'empty-{rid}'
    with _pg() as con, con.cursor() as cur:
        cur.execute('INSERT INTO research (id, name) VALUES (%s, %s)', [rid, name])
    try:
        r = client.get(f'/api/research/{rid}/report')
        assert r.status_code == 200
        text = r.text
        assert f'# {name}' in text
        assert '## Приватные стратегии' not in text
        assert '## Прогоны' not in text
        assert '## Выводы' not in text
    finally:
        with _pg() as con, con.cursor() as cur:
            cur.execute('DELETE FROM research WHERE id = %s', [rid])
