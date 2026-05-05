"""Тесты схемы Research (этап R1).

Предполагают, что миграция уже выполнена через
`python scripts/init_research_schema.py`.
"""
from __future__ import annotations

import psycopg
import pytest

from core.postgres_db import PG_DSN

DEFAULT_RESEARCH_ID = '00000000-0000-0000-0000-000000000001'
OWNED_TABLES = ('strategies', 'rules', 'environments')


@pytest.fixture(scope='module')
def cur():
    con = psycopg.connect(PG_DSN, autocommit=True)
    try:
        with con.cursor() as c:
            yield c
    finally:
        con.close()


def test_research_table_exists(cur):
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'research'"
    )
    assert cur.fetchone() is not None


def test_default_research_seeded(cur):
    cur.execute(
        'SELECT id, name FROM research WHERE id = %s', [DEFAULT_RESEARCH_ID]
    )
    row = cur.fetchone()
    assert row is not None
    assert row[1] == 'Default'


def test_owned_tables_have_research_id(cur):
    for tbl in OWNED_TABLES + ('backtest_results',):
        cur.execute(
            'SELECT 1 FROM information_schema.columns '
            "WHERE table_name = %s AND column_name = 'research_id'",
            [tbl],
        )
        assert cur.fetchone() is not None, f'{tbl}.research_id отсутствует'


def test_backtest_results_research_id_not_null(cur):
    cur.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'backtest_results' AND column_name = 'research_id'"
    )
    assert cur.fetchone()[0] == 'NO'


def test_owned_tables_research_id_nullable(cur):
    for tbl in OWNED_TABLES:
        cur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'research_id'",
            [tbl],
        )
        assert cur.fetchone()[0] == 'YES', f'{tbl}.research_id должен быть NULLable'


def test_existing_runs_bound_to_default(cur):
    cur.execute('SELECT COUNT(*) FROM backtest_results WHERE research_id IS NULL')
    assert cur.fetchone()[0] == 0


def test_research_id_fk_has_cascade(cur):
    for tbl in OWNED_TABLES + ('backtest_results',):
        cur.execute(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conrelid = %s::regclass AND contype = 'f' "
            "  AND pg_get_constraintdef(oid) LIKE %s",
            [tbl, '%research(id)%'],
        )
        # confdeltype = 'c' означает CASCADE
        rows = cur.fetchall()
        assert any(r[0] == 'c' for r in rows), f'{tbl}: FK research(id) без ON DELETE CASCADE'


def test_unique_indexes_present(cur):
    for tbl in OWNED_TABLES:
        for idx in (f'{tbl}_research_id_name_uniq', f'{tbl}_shared_name_uniq'):
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", [idx])
            assert cur.fetchone() is not None, f'индекс {idx} отсутствует'


def test_old_global_unique_dropped(cur):
    for tbl in OWNED_TABLES:
        cur.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = %s::regclass AND conname = %s",
            [tbl, f'{tbl}_name_key'],
        )
        assert cur.fetchone() is None, f'старый {tbl}_name_key UNIQUE не удалён'
