"""Парсер корпоративных событий с e-disclosure.ru для эмитентов из БД.

См. docs/drafts/SPEC_CORP_DISCLOSURE_DRAFT.md, этап 4.

Запрашивает POST /api/search/sevents по ИНН эмитента, фильтруя по четырём
типам событий (МСФО, годовая РСБУ, объявление и исполнение buyback).
Результат — один JSON-файл на эмитента в data/events/.

WAF-cookie берутся из переменных окружения; при истечении сессии скрипт
останавливается и печатает инструкцию по обновлению.

Список эмитентов — JOIN emitters × stocks (только те, у кого в БД есть
хотя бы одна бумага). В БД не пишет — заливку делает load_data_to_postgres.py.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from time import sleep

import psycopg
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'events')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

ENDPOINT = 'https://e-disclosure.ru/api/search/sevents'

# Типы событий первой волны (P0). Числа — идентификаторы на e-disclosure.
EVENT_TYPE_IDS = {
    'REPORT_IFRS': 36,
    'REPORT_RSBU_ANNUAL': 76,
    'BUYBACK_ANNOUNCE': 303,
    'BUYBACK_EXECUTE': 221,
}

# Cookie сессии — соответствие имени в WAF и переменной окружения.
COOKIE_ENV_VARS: dict[str, str] = {
    'spid': 'EDISCLOSURE_SPID',
    'spsc': 'EDISCLOSURE_SPSC',
    '.AspNetCore.Antiforgery.tl_-DOxheG0': 'EDISCLOSURE_ANTIFORGERY',
}

# Initial-load: окно начинается с этой даты. Берём заведомо «снизу»,
# чтобы поднять всю историю, которую отдаёт e-disclosure — у портала
# первые публикации начинаются в начале 2000-х.
INITIAL_FROM = date(2000, 1, 1)

# Перекрытие при инкрементальной загрузке: тянем последние 14 дней
# заново, чтобы захватить отложенные публикации.
OVERLAP_DAYS = 14

# Пауза между эмитентами, чтобы не нагружать API.
PAUSE_BETWEEN_EMITTERS_SEC = 0.5


class CookieExpired(Exception):
    """Признак истёкшей WAF-cookie: API ответил не-JSON."""


def _print_cookie_instructions() -> None:
    print('\nИнструкция по обновлению cookie:', file=sys.stderr)
    print('  1. Открыть https://e-disclosure.ru/poisk-po-soobshheniyam в Chrome', file=sys.stderr)
    print('  2. F12 → Application → Cookies → e-disclosure.ru', file=sys.stderr)
    print('  3. Скопировать значения cookies и переустановить переменные окружения:', file=sys.stderr)
    for cookie_name, env_var in COOKIE_ENV_VARS.items():
        print(f'        $env:{env_var} = "<значение cookie {cookie_name}>"', file=sys.stderr)
    print('  4. Перезапустить скрипт. Уже сохранённые файлы будут пропущены.', file=sys.stderr)


def _build_session() -> requests.Session:
    cookies: dict[str, str] = {}
    missing: list[str] = []
    for cookie_name, env_var in COOKIE_ENV_VARS.items():
        val = os.environ.get(env_var)
        if not val:
            missing.append(env_var)
        else:
            cookies[cookie_name] = val
    if missing:
        print(
            f'Отсутствуют переменные окружения: {", ".join(missing)}',
            file=sys.stderr,
        )
        _print_cookie_instructions()
        sys.exit(2)

    s = requests.Session()
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
    params: list[tuple[str, str]] = [
        ('eventTypeTerm', ''),
        ('radView', '0'),
    ]
    for tid in EVENT_TYPE_IDS.values():
        params.append(('eventTypeCheckboxGroup', str(tid)))
    params.extend([
        ('dateStart', date_from.strftime('%d.%m.%Y')),
        ('dateFinish', date_till.strftime('%d.%m.%Y')),
        ('textfieldEvent', ''),
        ('radReg', 'FederalDistricts'),
        ('districtsCheckboxGroup', '-1'),
        ('regionsCheckboxGroup', '-1'),
        ('branchesCheckboxGroup', '-1'),
        ('textfieldCompany', inn),
        ('lastPageSize', '10'),
        ('lastPageNumber', str(page)),
        ('query', inn),
        ('queryEvent', ''),
    ])
    return params


def _fetch_page(
    session: requests.Session, inn: str,
    date_from: date, date_till: date, page: int,
) -> dict:
    r = session.post(ENDPOINT, data=_build_payload(inn, date_from, date_till, page), timeout=30)
    ct = r.headers.get('Content-Type', '')
    if not ct.lower().startswith('application/json'):
        raise CookieExpired(
            f'API вернул не-JSON (status={r.status_code}, Content-Type={ct!r}). '
            'Cookie сессии истекла или была инвалидирована WAF.'
        )
    return r.json()


def _fetch_emitter_events(
    session: requests.Session, inn: str,
    date_from: date, date_till: date,
) -> list[dict]:
    """Все события одного эмитента за окно дат, с пагинацией."""
    events: list[dict] = []
    page = 1
    last_response: dict = {}
    while True:
        j = _fetch_page(session, inn, date_from, date_till, page)
        last_response = j
        events.extend(j.get('foundEventsList', []))
        paging = j.get('pagingInfo', {})
        current = paging.get('currentPage', 1)
        total = paging.get('totalPages', 1)
        if current >= total:
            break
        page += 1

    all_found = last_response.get('allFoundEvents', 0)
    max_shown = last_response.get('maxFoundEventsToShow', 0)
    if all_found > max_shown > 0:
        print(
            f'  WARNING inn={inn}: allFoundEvents={all_found} > '
            f'maxFoundEventsToShow={max_shown} — часть событий отброшена. '
            f'Окно стоит сузить.'
        )
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


def _make_out_path(inn: str, date_from: date, date_till: date) -> str:
    return os.path.join(
        OUT_DIR,
        f'edisclosure_{inn}_{date_from.isoformat()}_{date_till.isoformat()}.json',
    )


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
    print(f'Окно: {date_from} .. {date_till}')
    print(f'Типы событий: {", ".join(EVENT_TYPE_IDS.keys())}')

    skipped = 0
    fetched_total = 0
    for idx, (emitter_id, inn) in enumerate(emitters, 1):
        out_path = _make_out_path(inn, date_from, date_till)
        if os.path.exists(out_path):
            skipped += 1
            continue

        print(f'[{idx}/{len(emitters)}] inn={inn} emitter_id={emitter_id} …', end=' ', flush=True)
        try:
            events = _fetch_emitter_events(session, inn, date_from, date_till)
        except CookieExpired as e:
            print(f'\nОстановка: {e}', file=sys.stderr)
            _print_cookie_instructions()
            sys.exit(1)

        snapshot = {
            'inn': inn,
            'emitter_id': emitter_id,
            'from': date_from.isoformat(),
            'till': date_till.isoformat(),
            'event_type_ids': list(EVENT_TYPE_IDS.values()),
            'events': events,
        }
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        fetched_total += len(events)
        print(f'{len(events)} событий')
        sleep(PAUSE_BETWEEN_EMITTERS_SEC)

    print(f'\nЗакончено. Обработано: {len(emitters) - skipped}, пропущено (уже есть): {skipped}.')
    print(f'Всего событий в текущем прогоне: {fetched_total}')


if __name__ == '__main__':
    main()
