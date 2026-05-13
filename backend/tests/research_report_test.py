"""Тесты эндпоинта экспорта отчёта по исследованию.

GET /api/research/{id}/export?format=csv|pdf — единая точка экспорта.
CSV — плоская таблица прогонов с BOM; PDF — 501 (заглушка); неизвестный
format — 400; несуществующий research — 404.
"""
from __future__ import annotations

import csv
import io
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
def research_with_run():
    rid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    eid = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    name = f'export-test-{rid}'
    strategy_name = f's-{sid}'
    env_name = f'env-{eid}'
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO research (id, name) VALUES (%s, %s)', [rid, name],
        )
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, research_id) '
            'VALUES (%s, %s, %s, %s)',
            [sid, strategy_name, '2026-01-01T00:00:00+00:00', rid],
        )
        cur.execute(
            'INSERT INTO environments '
            '(id, name, date_start, date_end, starting_capital, created_at, research_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            [eid, env_name, date(2020, 1, 1), date(2020, 12, 31),
             1_000_000.0, '2026-01-01T00:00:00+00:00', rid],
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
    yield {
        'research_id': rid, 'name': name,
        'strategy_name': strategy_name, 'env_name': env_name,
    }
    with _pg() as con, con.cursor() as cur:
        cur.execute('DELETE FROM research WHERE id = %s', [rid])


def test_export_csv_returns_200_with_bom_and_correct_headers(research_with_run):
    a = research_with_run
    r = client.get(f'/api/research/{a["research_id"]}/export', params={'format': 'csv'})
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/csv')
    assert 'charset=utf-8' in r.headers['content-type']
    # BOM в начале — для Excel под Windows.
    assert r.text.startswith('\ufeff')


def test_export_csv_contains_run_row(research_with_run):
    a = research_with_run
    r = client.get(f'/api/research/{a["research_id"]}/export', params={'format': 'csv'})
    assert r.status_code == 200
    # BOM перед парсингом отрезаем — csv его не ждёт.
    text = r.text.lstrip('\ufeff')
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert header[0] == 'strategy'
    assert header[1] == 'environment'
    assert 'total_return_pct' in header
    assert 'sharpe' in header
    # ровно одна data-строка с нашим прогоном
    assert len(rows) == 2
    data = rows[1]
    assert data[0] == a['strategy_name']
    assert data[1] == a['env_name']


def test_export_csv_default_research_returns_200():
    r = client.get(f'/api/research/{DEFAULT_RESEARCH_ID}/export', params={'format': 'csv'})
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/csv')


def test_export_pdf_returns_501():
    r = client.get(f'/api/research/{DEFAULT_RESEARCH_ID}/export', params={'format': 'pdf'})
    assert r.status_code == 501


def test_export_unknown_format_returns_400():
    r = client.get(f'/api/research/{DEFAULT_RESEARCH_ID}/export', params={'format': 'xlsx'})
    assert r.status_code == 400


def test_export_unknown_research_returns_404():
    fake = str(uuid.uuid4())
    r = client.get(f'/api/research/{fake}/export', params={'format': 'csv'})
    assert r.status_code == 404
