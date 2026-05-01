"""Тесты HTTP-эндпоинтов для сохранения и чтения прецедентных запросов.

Используется временная DuckDB-база с такой же схемой, что и продакшен — основная
data-core.duckdb не затрагивается.
"""
from __future__ import annotations

import duckdb
import pytest


def _create_test_db(path: str) -> None:
    """Создаёт временный DuckDB-файл с минимальной схемой для тестов API сохранения."""
    con = duckdb.connect(path)
    con.execute("""
        CREATE TABLE precedent_queries (
            id         VARCHAR PRIMARY KEY,
            name       VARCHAR NOT NULL UNIQUE,
            source     TEXT    NOT NULL,
            created_at VARCHAR NOT NULL
        )
    """)
    con.close()


@pytest.fixture(autouse=True)
def reset_precedent_engine(monkeypatch, tmp_path):
    """Подменяет APP_DB_PATH на временный файл и сбрасывает singleton движка."""
    tmp_db = tmp_path / 'data-core.duckdb'
    _create_test_db(str(tmp_db))

    from core import precedent_engine
    monkeypatch.setattr(precedent_engine, 'APP_DB_PATH', str(tmp_db))

    import main
    monkeypatch.setattr(main, '_precedent_engine', None)
    yield
    monkeypatch.setattr(main, '_precedent_engine', None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_list_initially_empty(client):
    r = client.get("/api/precedents/queries")
    assert r.status_code == 200
    assert r.json() == []


def test_save_and_list(client):
    r = client.post("/api/precedents/queries", json={
        "name": "LKOH dividends",
        "source": "SELECT * FROM tagged_events WHERE tag = 'LKOH' LIMIT 10",
    })
    assert r.status_code == 201
    saved = r.json()
    assert saved["name"] == "LKOH dividends"
    assert saved["source"].startswith("SELECT")
    assert "id" in saved
    assert "createdAt" in saved

    r2 = client.get("/api/precedents/queries")
    items = r2.json()
    assert len(items) == 1
    assert items[0]["name"] == "LKOH dividends"


def test_save_rejects_duplicate_name(client):
    payload = {"name": "Duplicate test", "source": "SELECT 1"}
    r1 = client.post("/api/precedents/queries", json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/precedents/queries", json=payload)
    assert r2.status_code == 409


def test_save_rejects_empty_name(client):
    r = client.post("/api/precedents/queries", json={"name": "  ", "source": "SELECT 1"})
    assert r.status_code == 400


def test_save_rejects_empty_source(client):
    r = client.post("/api/precedents/queries", json={"name": "name", "source": "   "})
    assert r.status_code == 400


def test_list_sorted_newest_first(client):
    import time
    client.post("/api/precedents/queries", json={"name": "A", "source": "SELECT 1"})
    time.sleep(1.1)  # секундная гранулярность ISO timestamp
    client.post("/api/precedents/queries", json={"name": "B", "source": "SELECT 2"})

    items = client.get("/api/precedents/queries").json()
    assert [i["name"] for i in items] == ["B", "A"]


def test_saved_query_visible_via_pql(client):
    """Сохранённый запрос виден через POST /api/precedents/search в таблице precedent_queries."""
    client.post("/api/precedents/queries", json={
        "name": "PQL visible test",
        "source": "SELECT 42",
    })
    r = client.post("/api/precedents/search", json={
        "source": "SELECT name FROM precedent_queries WHERE name = 'PQL visible test'",
    })
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows == [["PQL visible test"]]
