"""Тесты Этапа 1 — наличие видимой схемы PQL и работоспособность простого SELECT."""
from __future__ import annotations

import pytest

from core.precedent_engine import create_engine


@pytest.fixture(scope='module')
def con():
    return create_engine()


def _list_relations(con) -> set[str]:
    rows = con.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main'
    """).fetchall()
    return {r[0] for r in rows}


def test_engine_creates_three_base_tables(con):
    relations = _list_relations(con)
    assert {'events', 'tags', 'event_tags'}.issubset(relations)


def test_engine_creates_tagged_events_view(con):
    relations = _list_relations(con)
    assert 'tagged_events' in relations


def test_events_table_has_expected_columns(con):
    cols = [r[0] for r in con.execute("DESCRIBE events").fetchall()]
    assert {'id', 'date_start', 'date_end', 'event'}.issubset(set(cols))


def test_tags_table_has_expected_columns(con):
    cols = [r[0] for r in con.execute("DESCRIBE tags").fetchall()]
    assert {'code', 'name', 'type'}.issubset(set(cols))


def test_event_tags_table_has_expected_columns(con):
    cols = [r[0] for r in con.execute("DESCRIBE event_tags").fetchall()]
    assert {'event_id', 'tag_code'}.issubset(set(cols))


def test_tagged_events_has_expected_columns(con):
    cols = [r[0] for r in con.execute("DESCRIBE tagged_events").fetchall()]
    expected = {'event_id', 'date_start', 'date_end', 'event', 'tag', 'tag_name', 'tag_type'}
    assert expected.issubset(set(cols))


def test_simple_select_returns_rows(con):
    n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert n > 0


def test_tagged_events_returns_rows(con):
    n = con.execute("SELECT COUNT(*) FROM tagged_events").fetchone()[0]
    assert n > 0


def test_join_query_works(con):
    rows = con.execute("""
        SELECT e.id, e.date_start
        FROM events e
        JOIN event_tags et ON et.event_id = e.id
        JOIN tags t        ON t.code      = et.tag_code
        WHERE t.code = 'SANCTIONS'
        LIMIT 5
    """).fetchall()
    assert len(rows) > 0


def test_tagged_events_short_form_matches_join(con):
    n_join = con.execute("""
        SELECT COUNT(*)
        FROM events e
        JOIN event_tags et ON et.event_id = e.id
        JOIN tags t        ON t.code      = et.tag_code
        WHERE t.code = 'SANCTIONS'
    """).fetchone()[0]
    n_view = con.execute("""
        SELECT COUNT(*) FROM tagged_events WHERE tag = 'SANCTIONS'
    """).fetchone()[0]
    assert n_join == n_view


def test_car_function_registered_as_macro(con):
    rows = con.execute("""
        SELECT function_name FROM duckdb_functions()
        WHERE function_name = 'car'
    """).fetchall()
    assert len(rows) >= 1
