"""Парсер корпоративных событий с e-disclosure.ru для эмитентов из БД.

См. docs/drafts/SPEC_CORP_DISCLOSURE_DRAFT.md.

Запрашивает POST /api/search/sevents по ИНН эмитента **без фильтра типа** —
тянет всю выдачу за окно дат. Классификация (eventName → тег) выполняется
позже в load_data_to_postgres.py.

API e-disclosure режет выдачу одного запроса значением maxFoundEventsToShow
(обычно 1200) — обойти размером страницы нельзя. Поэтому окно дат при
превышении лимита делится пополам рекурсивно, пока каждое подокно не
укладывается в лимит. Все собранные подокна сливаются в один JSON-файл
на эмитента: data/events/edisclosure_<inn>.json.

WAF Servicepipe принимает запрос даже без cookies (через 307-redirect).
Если переменные окружения EDISCLOSURE_SPID/SPSC/ANTIFORGERY заданы — они
подкладываются в сессию (для подстраховки). При не-JSON ответе скрипт
останавливается с инструкцией по обновлению cookies.

Список эмитентов — JOIN emitters × stocks (только те, у кого в БД есть
хотя бы одна бумага). В БД не пишет — заливку делает load_data_to_postgres.py.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from time import sleep

import psycopg
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'events', 'edisclosure')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

ENDPOINT = 'https://e-disclosure.ru/api/search/sevents'

# Cookie сессии — опциональны. Если в env заданы — подкладываем; нет —
# рассчитываем на 307-flow WAF Servicepipe.
COOKIE_ENV_VARS: dict[str, str] = {
    'spid': 'EDISCLOSURE_SPID',
    'spsc': 'EDISCLOSURE_SPSC',
    '.AspNetCore.Antiforgery.tl_-DOxheG0': 'EDISCLOSURE_ANTIFORGERY',
}

# Initial-load: окно начинается с этой даты. Берём заведомо «снизу»,
# чтобы поднять всю историю, которую отдаёт e-disclosure.
INITIAL_FROM = date(2000, 1, 1)

# Размер страницы. Лимит API на общее число событий за запрос (1200)
# жёсткий — увеличение страницы выше 100 не помогает. 100 укладывается
# в одну страницу для большинства подокон и снижает число round-trip'ов.
PAGE_SIZE = 100

# Минимальная ширина подокна при рекурсивном дроблении (защита от
# бесконечной рекурсии при патологическом числе событий в один день).
MIN_WINDOW_DAYS = 1

# Пауза между эмитентами, чтобы не нагружать API.
PAUSE_BETWEEN_EMITTERS_SEC = 0.5

# Сетевые тайм-ауты (connect, read), сек.
TIMEOUTS = (5, 25)


class CookieExpired(Exception):
    """API ответил не-JSON: WAF challenge или истёкшая сессия."""


def _print_cookie_instructions() -> None:
    print('\nИнструкция по обновлению cookie:', file=sys.stderr)
    print('  1. Открыть https://e-disclosure.ru/poisk-po-soobshheniyam в Chrome', file=sys.stderr)
    print('  2. F12 → Application → Cookies → e-disclosure.ru', file=sys.stderr)
    print('  3. Скопировать значения cookies и переустановить переменные окружения:', file=sys.stderr)
    for cookie_name, env_var in COOKIE_ENV_VARS.items():
        print(f'        $env:{env_var} = "<значение cookie {cookie_name}>"', file=sys.stderr)
    print('  4. Перезапустить скрипт. Уже сохранённые файлы будут пропущены.', file=sys.stderr)


def _build_session() -> requests.Session:
    s = requests.Session()
    cookies: dict[str, str] = {}
    for cookie_name, env_var in COOKIE_ENV_VARS.items():
        val = os.environ.get(env_var)
        if val:
            cookies[cookie_name] = val
    if cookies:
        s.cookies.update(cookies)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ru,en;q=0.9',
        'Origin': 'https://e-disclosure.ru',
        'Referer': 'https://e-disclosure.ru/poisk-po-soobshheniyam',
        'X-Requested-With': 'XMLHttpRequest',
    })
    return s


def _build_payload(inn: str, date_from: date, date_till: date, page: int) -> list[tuple[str, str]]:
    return [
        ('eventTypeTerm', ''),
        ('radView', '0'),
        ('dateStart', date_from.strftime('%d.%m.%Y')),
        ('dateFinish', date_till.strftime('%d.%m.%Y')),
        ('textfieldEvent', ''),
        ('radReg', 'FederalDistricts'),
        ('districtsCheckboxGroup', '-1'),
        ('regionsCheckboxGroup', '-1'),
        ('branchesCheckboxGroup', '-1'),
        ('textfieldCompany', inn),
        ('lastPageSize', str(PAGE_SIZE)),
        ('lastPageNumber', str(page)),
        ('query', inn),
        ('queryEvent', ''),
    ]


def _fetch_page(
    session: requests.Session, inn: str,
    date_from: date, date_till: date, page: int,
) -> dict:
    r = session.post(ENDPOINT, data=_build_payload(inn, date_from, date_till, page),
                     timeout=TIMEOUTS, allow_redirects=True)
    ct = r.headers.get('Content-Type', '')
    if not ct.lower().startswith('application/json'):
        raise CookieExpired(
            f'API вернул не-JSON (status={r.status_code}, Content-Type={ct!r}). '
            'WAF не пропустил запрос; обновите cookies сессии.'
        )
    return r.json()


def _fetch_window(
    session: requests.Session, inn: str,
    date_from: date, date_till: date,
    depth: int = 0,
) -> list[dict]:
    """Все события за окно дат с авто-дроблением при превышении лимита API.

    Если allFoundEvents > maxFoundEventsToShow — делим окно пополам и
    повторяем рекурсивно. На листовом подокне собираем все страницы.
    """
    j = _fetch_page(session, inn, date_from, date_till, page=1)
    paging = j.get('pagingInfo', {})
    all_found = j.get('allFoundEvents', 0)
    max_show = j.get('maxFoundEventsToShow', 0) or 0

    overflow = max_show > 0 and all_found > max_show
    width_days = (date_till - date_from).days
    indent = '  ' * (depth + 1)

    if overflow and width_days > MIN_WINDOW_DAYS:
        mid = date_from + timedelta(days=width_days // 2)
        print(f'{indent}окно {date_from}..{date_till}: {all_found} > {max_show}, '
              f'делю на {date_from}..{mid} и {mid + timedelta(days=1)}..{date_till}',
              flush=True)
        left = _fetch_window(session, inn, date_from, mid, depth + 1)
        right = _fetch_window(session, inn, mid + timedelta(days=1), date_till, depth + 1)
        return left + right

    if overflow:
        # упёрлись в MIN_WINDOW_DAYS: всё равно режется, фиксируем и идём дальше
        print(f'{indent}WARNING окно {date_from}..{date_till}: {all_found} > {max_show} '
              f'и подокно уже минимально — {all_found - max_show} событий потеряно',
              flush=True)

    events: list[dict] = list(j.get('foundEventsList', []))
    total_pages = paging.get('totalPages', 1)
    for page in range(2, total_pages + 1):
        jp = _fetch_page(session, inn, date_from, date_till, page)
        events.extend(jp.get('foundEventsList', []))
    return events


def _load_emitters_from_db(pg) -> list[tuple[int, str]]:
    """Эмитенты, у которых в stocks есть хотя бы одна бумага."""
    with pg.cursor() as cur:
        cur.execute(
            'SELECT DISTINCT e.emitter_id, e.inn '
            'FROM emitters e JOIN stocks s ON s.emitter_id = e.emitter_id '
            'ORDER BY e.inn'
        )
        return [(int(eid), inn) for eid, inn in cur.fetchall()]


def _out_path(inn: str) -> str:
    return os.path.join(OUT_DIR, f'{inn}.json')


def main() -> None:
    session = _build_session()
    pg = psycopg.connect(PG_DSN, autocommit=True)
    try:
        emitters = _load_emitters_from_db(pg)
    finally:
        pg.close()

    smoke_inns_raw = os.environ.get('EDISCLOSURE_SMOKE_INNS') or os.environ.get('EDISCLOSURE_SMOKE_INN')
    if smoke_inns_raw:
        smoke_set = {x.strip() for x in smoke_inns_raw.split(',') if x.strip()}
        emitters = [(eid, inn) for eid, inn in emitters if inn in smoke_set]
        print(f'SMOKE-режим: фильтр по ИНН={sorted(smoke_set)} → {len(emitters)} эмитентов')

    print(f'Эмитентов для опроса: {len(emitters)}')
    os.makedirs(OUT_DIR, exist_ok=True)

    date_from = INITIAL_FROM
    date_till = date.today()
    print(f'Окно: {date_from} .. {date_till}, фильтр типа: НЕТ (берём всё)')

    skipped = 0
    fetched_total = 0
    for idx, (emitter_id, inn) in enumerate(emitters, 1):
        out_path = _out_path(inn)
        if os.path.exists(out_path):
            skipped += 1
            continue

        print(f'[{idx}/{len(emitters)}] inn={inn} emitter_id={emitter_id} …', flush=True)
        try:
            events = _fetch_window(session, inn, date_from, date_till)
        except CookieExpired as e:
            print(f'Остановка: {e}', file=sys.stderr)
            _print_cookie_instructions()
            sys.exit(1)

        snapshot = {
            'inn': inn,
            'emitter_id': emitter_id,
            'from': date_from.isoformat(),
            'till': date_till.isoformat(),
            'fetched_at': datetime.now().isoformat(timespec='seconds'),
            'events': events,
        }
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        fetched_total += len(events)
        print(f'  → {len(events)} событий, сохранено: {os.path.basename(out_path)}', flush=True)
        sleep(PAUSE_BETWEEN_EMITTERS_SEC)

    print(f'\nЗакончено. Обработано: {len(emitters) - skipped}, пропущено (уже есть): {skipped}.')
    print(f'Всего событий в текущем прогоне: {fetched_total}')


if __name__ == '__main__':
    main()
