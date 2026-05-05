"""Тесты Этапа 3 — HTTP-эндпоинт POST /api/precedents/search."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_happy_path_simple_select():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT id, date_start, event FROM events LIMIT 3",
    })
    assert r.status_code == 200
    body = r.json()
    assert "columns" in body
    assert "rows" in body
    assert "stats" in body
    assert len(body["columns"]) == 3
    assert {c["name"] for c in body["columns"]} == {"id", "date_start", "event"}
    assert len(body["rows"]) == 3


def test_columns_have_name_and_type():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT 'hello' AS s, 42 AS n, DATE '2022-01-01' AS d",
    })
    assert r.status_code == 200
    cols = r.json()["columns"]
    by_name = {c["name"]: c["type"] for c in cols}
    assert "s" in by_name and "n" in by_name and "d" in by_name


def test_dates_serialized_as_iso_strings():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT DATE '2022-12-16' AS d",
    })
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows[0][0] == "2022-12-16"


def test_empty_result_returns_columns():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT id FROM events WHERE 1 = 0",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert len(body["columns"]) == 1
    assert body["columns"][0]["name"] == "id"


def test_syntax_error_returns_400():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT * FORM events",
    })
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body
    detail = body["detail"]
    assert "message" in detail
    assert detail["message"]


def test_unknown_table_returns_400():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT * FROM nonexistent_table",
    })
    assert r.status_code == 400


def test_max_rows_truncates():
    # events.csv содержит много строк — гарантированно > 1000
    r = client.post("/api/precedents/search", json={
        "source": "SELECT id FROM events",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) <= 1000
    assert body["stats"]["truncated"] is True


def test_within_limit_not_truncated():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT id FROM events LIMIT 5",
    })
    assert r.status_code == 200
    assert r.json()["stats"]["truncated"] is False


def test_tagged_events_view_accessible():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT date_start, tag FROM tagged_events WHERE tag = 'SANCTIONS' LIMIT 3",
    })
    assert r.status_code == 200
    body = r.json()
    assert all(row[1] == "SANCTIONS" for row in body["rows"])


def test_car_function_accessible():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT car('LKOH', DATE '2022-12-16') AS car",
    })
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0][0] is not None
    assert isinstance(rows[0][0], (int, float))


def test_car_returns_null_for_unknown_ticker():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT car('NOTAREAL', DATE '2022-01-01') AS car",
    })
    assert r.status_code == 200
    assert r.json()["rows"][0][0] is None


def test_stats_duration_ms_present():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT 1",
    })
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert "durationMs" in stats
    assert isinstance(stats["durationMs"], int)
    assert stats["durationMs"] >= 0


# ---------- UDF/macro доступность через cursor ----------
# Регрессия: TEMP MACRO живёт в приватной temp-схеме коннекта и не виден из
# `con.cursor()` (новой сессии), которым API возвращает соединение каждому
# запросу. Эти тесты гарантируют, что vol_ratio/volume_ratio/car доступны
# в публичном контракте /api/precedents/search.

def test_vol_ratio_callable_via_api():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT vol_ratio('LKOH', DATE '2022-12-16') AS v",
    })
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0][0] is not None


def test_volume_ratio_callable_via_api():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT volume_ratio('LKOH', DATE '2022-12-16') AS v",
    })
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] is not None


def test_car_callable_via_api():
    r = client.post("/api/precedents/search", json={
        "source": "SELECT car('LKOH', DATE '2022-12-16') AS c",
    })
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] is not None
