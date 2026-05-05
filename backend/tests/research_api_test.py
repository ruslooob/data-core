"""Тесты REST API исследований (этап R2).

Используют живую Postgres-БД и TestClient. Каждый тест создаёт свои
research-записи и убирает за собой в finally — Default-исследование
не трогаем.
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
def cleanup_research():
    """Удаляет созданные тестом research-записи по списку id."""
    created: list[str] = []
    yield created
    if not created:
        return
    with _pg() as con, con.cursor() as cur:
        for rid in created:
            if rid == DEFAULT_RESEARCH_ID:
                continue
            cur.execute('DELETE FROM research WHERE id = %s', [rid])


def test_list_includes_default():
    r = client.get('/api/research')
    assert r.status_code == 200
    items = r.json()
    by_id = {it['id']: it for it in items}
    assert DEFAULT_RESEARCH_ID in by_id
    assert by_id[DEFAULT_RESEARCH_ID]['name'] == 'Default'
    assert by_id[DEFAULT_RESEARCH_ID]['isDefault'] is True


def test_get_default():
    r = client.get(f'/api/research/{DEFAULT_RESEARCH_ID}')
    assert r.status_code == 200
    body = r.json()
    assert body['id'] == DEFAULT_RESEARCH_ID
    assert body['name'] == 'Default'
    assert body['isDefault'] is True


def test_get_unknown_returns_404():
    r = client.get(f'/api/research/{uuid.uuid4()}')
    assert r.status_code == 404


def test_create_happy_path(cleanup_research):
    name = f'test-{uuid.uuid4()}'
    r = client.post('/api/research', json={'name': name, 'description': 'идея'})
    assert r.status_code == 201
    body = r.json()
    cleanup_research.append(body['id'])
    assert body['name'] == name
    assert body['description'] == 'идея'
    assert body['conclusion'] is None
    assert body['isDefault'] is False


def test_create_duplicate_name_returns_409(cleanup_research):
    name = f'dup-{uuid.uuid4()}'
    r1 = client.post('/api/research', json={'name': name})
    assert r1.status_code == 201
    cleanup_research.append(r1.json()['id'])
    r2 = client.post('/api/research', json={'name': name})
    assert r2.status_code == 409


def test_create_empty_name_returns_400():
    r = client.post('/api/research', json={'name': '   '})
    assert r.status_code == 400


def test_patch_name_description_conclusion(cleanup_research):
    name = f'orig-{uuid.uuid4()}'
    r = client.post('/api/research', json={'name': name})
    rid = r.json()['id']
    cleanup_research.append(rid)

    new_name = f'renamed-{uuid.uuid4()}'
    r2 = client.patch(f'/api/research/{rid}', json={
        'name': new_name, 'description': 'desc', 'conclusion': 'итог',
    })
    assert r2.status_code == 200
    body = r2.json()
    assert body['name'] == new_name
    assert body['description'] == 'desc'
    assert body['conclusion'] == 'итог'


def test_patch_default_name_forbidden():
    r = client.patch(f'/api/research/{DEFAULT_RESEARCH_ID}', json={'name': 'Renamed'})
    assert r.status_code == 400


def test_patch_default_description_allowed():
    r = client.patch(f'/api/research/{DEFAULT_RESEARCH_ID}', json={'description': 'temp-desc'})
    assert r.status_code == 200
    assert r.json()['description'] == 'temp-desc'
    # cleanup: вернём description в None
    with _pg() as con, con.cursor() as cur:
        cur.execute('UPDATE research SET description = NULL WHERE id = %s', [DEFAULT_RESEARCH_ID])


def test_patch_duplicate_name_returns_409(cleanup_research):
    a = client.post('/api/research', json={'name': f'a-{uuid.uuid4()}'}).json()
    b = client.post('/api/research', json={'name': f'b-{uuid.uuid4()}'}).json()
    cleanup_research += [a['id'], b['id']]
    r = client.patch(f'/api/research/{b["id"]}', json={'name': a['name']})
    assert r.status_code == 409


def test_delete_default_forbidden():
    r = client.delete(f'/api/research/{DEFAULT_RESEARCH_ID}')
    assert r.status_code == 400


def test_delete_unknown_returns_404():
    r = client.delete(f'/api/research/{uuid.uuid4()}')
    assert r.status_code == 404


def test_delete_happy_path():
    name = f'todelete-{uuid.uuid4()}'
    rid = client.post('/api/research', json={'name': name}).json()['id']
    r = client.delete(f'/api/research/{rid}')
    assert r.status_code == 204
    assert client.get(f'/api/research/{rid}').status_code == 404


def test_delete_cascades_private_strategy():
    """При удалении research приватная стратегия с research_id = research уходит каскадом."""
    rid = client.post('/api/research', json={'name': f'cascade-{uuid.uuid4()}'}).json()['id']
    sid = str(uuid.uuid4())
    with _pg() as con, con.cursor() as cur:
        cur.execute(
            'INSERT INTO strategies (id, name, created_at, research_id) '
            'VALUES (%s, %s, %s, %s)',
            [sid, f'priv-{uuid.uuid4()}', '2026-01-01T00:00:00+00:00', rid],
        )

    r = client.delete(f'/api/research/{rid}')
    assert r.status_code == 204
    with _pg() as con, con.cursor() as cur:
        cur.execute('SELECT 1 FROM strategies WHERE id = %s', [sid])
        assert cur.fetchone() is None
