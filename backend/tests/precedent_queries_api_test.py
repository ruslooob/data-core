"""Тесты HTTP-эндпоинтов для сохранения и чтения прецедентных запросов.

После миграции на Postgres `precedent_queries` живёт в той же БД, что
и продакшен. Системные ★-рецепты засеваются Liquibase-миграцией, и в
выдаче `/api/precedents/queries` они присутствуют — тесты их фильтруют.
Перед каждым тестом удаляются накопленные пользовательские записи
(всё, что не начинается с «★»), чтобы тесты не зависели друг от друга.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.postgres_db import get_pool
from main import app


@pytest.fixture(autouse=True)
def cleanup_user_queries():
    """Удаляет пользовательские precedent_queries (без ★-префикса) до и
    после теста, чтобы между прогонами не оставался мусор."""
    def _purge():
        with get_pool().connection() as con:
            con.execute("DELETE FROM precedent_queries WHERE name NOT LIKE '★%%'")
    _purge()
    yield
    _purge()


@pytest.fixture
def client():
    return TestClient(app)


def _user_items(items: list[dict]) -> list[dict]:
    """Отфильтровывает пользовательские записи (без префикса ★)."""
    return [i for i in items if not i['name'].startswith('★')]


def test_list_initially_only_system_recipes(client):
    """Свежая БД (после cleanup): пользовательских записей нет, есть только системные ★-рецепты."""
    r = client.get('/api/precedents/queries')
    assert r.status_code == 200
    items = r.json()
    assert _user_items(items) == []
    assert len(items) >= 1  # хотя бы один системный засеялся
    assert all(i['name'].startswith('★') for i in items)


def test_save_and_list(client):
    r = client.post('/api/precedents/queries', json={
        'name': 'LKOH dividends',
        'source': "SELECT * FROM tagged_events WHERE tag = 'LKOH' LIMIT 10",
    })
    assert r.status_code == 201
    saved = r.json()
    assert saved['name'] == 'LKOH dividends'
    assert saved['source'].startswith('SELECT')
    assert 'id' in saved
    assert 'createdAt' in saved

    items = client.get('/api/precedents/queries').json()
    user = _user_items(items)
    assert len(user) == 1
    assert user[0]['name'] == 'LKOH dividends'


def test_save_rejects_duplicate_name(client):
    payload = {'name': 'Duplicate test', 'source': 'SELECT 1'}
    r1 = client.post('/api/precedents/queries', json=payload)
    assert r1.status_code == 201
    r2 = client.post('/api/precedents/queries', json=payload)
    assert r2.status_code == 409


def test_save_rejects_empty_name(client):
    r = client.post('/api/precedents/queries', json={'name': '  ', 'source': 'SELECT 1'})
    assert r.status_code == 400


def test_save_rejects_empty_source(client):
    r = client.post('/api/precedents/queries', json={'name': 'name', 'source': '   '})
    assert r.status_code == 400


def test_save_rejects_system_name(client):
    """Имена с префиксом ★ зарезервированы — пользователь не может их создать."""
    r = client.post('/api/precedents/queries', json={
        'name': '★ My fake recipe',
        'source': 'SELECT 1',
    })
    assert r.status_code == 400


def test_list_sorted_newest_first(client):
    import time
    client.post('/api/precedents/queries', json={'name': 'A', 'source': 'SELECT 1'})
    time.sleep(1.1)  # секундная гранулярность ISO timestamp
    client.post('/api/precedents/queries', json={'name': 'B', 'source': 'SELECT 2'})

    items = client.get('/api/precedents/queries').json()
    user_names = [i['name'] for i in _user_items(items)]
    assert user_names == ['B', 'A']


def test_saved_query_visible_via_pql(client):
    """Сохранённый запрос виден через POST /api/precedents/search в таблице precedent_queries."""
    client.post('/api/precedents/queries', json={
        'name': 'PQL visible test',
        'source': 'SELECT 42',
    })
    r = client.post('/api/precedents/search', json={
        'source': "SELECT name FROM precedent_queries WHERE name = 'PQL visible test'",
    })
    assert r.status_code == 200
    rows = r.json()['rows']
    assert rows == [['PQL visible test']]
