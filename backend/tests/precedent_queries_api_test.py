"""Тесты HTTP-эндпоинтов для сохранения и чтения прецедентных запросов.

После миграции на Postgres `saved_queries` живёт в той же БД, что
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
    """Изолирует тест от пользовательских saved_queries, не уничтожая их:
    снимает снимок не-★ записей, очищает их на время теста и
    восстанавливает после. Так прогон тестов против дев-БД не стирает
    реальные сохранённые запросы пользователя."""
    with get_pool().connection() as con:
        snapshot = con.execute(
            "SELECT id, name, source, created_at, kind "
            "FROM saved_queries WHERE name NOT LIKE '★%%'"
        ).fetchall()
        con.execute("DELETE FROM saved_queries WHERE name NOT LIKE '★%%'")
    yield
    with get_pool().connection() as con:
        con.execute("DELETE FROM saved_queries WHERE name NOT LIKE '★%%'")
        for row in snapshot:
            con.execute(
                "INSERT INTO saved_queries (id, name, source, created_at, kind) "
                "VALUES (%s, %s, %s, %s, %s)",
                row,
            )


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
    """Сохранённый запрос виден через POST /api/precedents/search в таблице saved_queries."""
    client.post('/api/precedents/queries', json={
        'name': 'PQL visible test',
        'source': 'SELECT 42',
    })
    r = client.post('/api/precedents/search', json={
        'source': "SELECT name FROM saved_queries WHERE name = 'PQL visible test'",
    })
    assert r.status_code == 200
    rows = r.json()['rows']
    assert rows == [['PQL visible test']]


def test_save_with_kind_and_filter(client):
    """kind сохраняется и фильтрует список: FUZZY и PQL не смешиваются."""
    client.post('/api/precedents/queries', json={
        'name': 'fuzzy one', 'source': 'газпром', 'kind': 'FUZZY',
    })
    client.post('/api/precedents/queries', json={
        'name': 'pql one', 'source': 'SELECT 1', 'kind': 'PQL',
    })

    fuzzy = _user_items(client.get('/api/precedents/queries?kind=FUZZY').json())
    assert [q['name'] for q in fuzzy] == ['fuzzy one']
    assert fuzzy[0]['kind'] == 'FUZZY'

    pql = _user_items(client.get('/api/precedents/queries?kind=PQL').json())
    assert [q['name'] for q in pql] == ['pql one']

    both = {q['name'] for q in _user_items(client.get('/api/precedents/queries').json())}
    assert both == {'fuzzy one', 'pql one'}


def test_save_defaults_kind_pql(client):
    """Без явного kind сохранение трактуется как PQL (обратная совместимость)."""
    saved = client.post('/api/precedents/queries', json={
        'name': 'no kind', 'source': 'SELECT 1',
    }).json()
    assert saved['kind'] == 'PQL'
