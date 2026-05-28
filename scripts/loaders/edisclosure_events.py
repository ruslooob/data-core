"""Лоадер: корпоративные раскрытия с e-disclosure.ru.

Стадии:
- `fetch()` — POST `/api/search/sevents` по ИНН эмитента **без фильтра
  типа**, тянет всю выдачу за окно дат. API режет выдачу одного запроса
  значением maxFoundEventsToShow (обычно 1200) — окно дат при превышении
  лимита делится пополам рекурсивно, пока каждое подокно не укладывается
  в лимит. Все подокна сливаются в один JSON-файл на эмитента:
  `data/events/edisclosure/<inn>.json`.

  WAF Servicepipe принимает запрос даже без cookies (через 307-redirect).
  Если переменные окружения EDISCLOSURE_SPID/SPSC/ANTIFORGERY заданы —
  подкладываются в сессию (для подстраховки). При не-JSON ответе скрипт
  останавливается с инструкцией по обновлению cookies.

  Список эмитентов — JOIN emitters × stocks (только те, у кого в БД есть
  хотя бы одна бумага).

- `load(pg)` — читает JSON-файлы и для каждого подходящего события (тип
  в словаре `EDISCLOSURE_EVENT_NAME_TO_TAG`) создаёт строку в `events`
  с id `edisc:<pseudoGUID>` + связки `event_tags`: тег типа события
  плюс company-теги всех бумаг эмитента. Заодно обновляет
  `emitters.e_disclosure_company_id`.

См. docs/SPEC_LOADERS.md и docs/drafts/SPEC_CORP_DISCLOSURE_DRAFT.md.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from glob import glob
from time import sleep

import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'data', 'events', 'edisclosure')

ENDPOINT = 'https://e-disclosure.ru/api/search/sevents'

COOKIE_ENV_VARS: dict[str, str] = {
    'spid': 'EDISCLOSURE_SPID',
    'spsc': 'EDISCLOSURE_SPSC',
    '.AspNetCore.Antiforgery.tl_-DOxheG0': 'EDISCLOSURE_ANTIFORGERY',
}

# Initial-load: окно начинается с этой даты. Берём заведомо «снизу»,
# чтобы поднять всю историю, которую отдаёт e-disclosure.
INITIAL_FROM = date(2000, 1, 1)

PAGE_SIZE = 100
MIN_WINDOW_DAYS = 1
PAUSE_BETWEEN_EMITTERS_SEC = 0.5
TIMEOUTS = (5, 25)

# Нормализованный текст eventName → код нашего тега. Нормализация:
# схлопывание любой последовательности пробельных символов в один пробел
# плюс strip. Это снимает реальный дубль на портале — варианты с двойными
# пробелами в названиях. Эмитенты, чей тип события не присутствует
# в словаре, остаются в JSON на диске и в БД не попадают — расширение
# словаря не требует перезагрузки с e-disclosure.
EDISCLOSURE_EVENT_NAME_TO_TAG: dict[str, str] = {
    # REPORT_IFRS — зонтик над тремя регуляторными формами одной сущности
    # (раскрытие отчётности по международному / консолидированному стандарту);
    # эмитенты переключались между ними по мере смены положений ЦБ, но для
    # event-study это один и тот же тип события.
    'Раскрытие эмитентом бухгалтерской отчетности в стандартах МСФО или US GAAP':
        'REPORT_IFRS',
    'Раскрытие эмитентом консолидированной финансовой отчетности':
        'REPORT_IFRS',
    'Раскрытие эмитентом сводной бухгалтерской (консолидированной финансовой) отчетности':
        'REPORT_IFRS',
    'Раскрытие эмитентом ежеквартального отчета':
        'REPORT_QUARTERLY',
    'Раскрытие в сети Интернет годовой бухгалтерской отчетности':
        'REPORT_RSBU_ANNUAL',
    'Принятие решения о приобретении размещённых эмитентом акций':
        'BUYBACK_ANNOUNCE',
    'Принятие решения о приобретении размещенных эмитентом акций':  # без «ё»
        'BUYBACK_ANNOUNCE',
    'Приобретение эмитентом собственных голосующих акций (долей) или депозитарных расписок на акции эмитента':
        'BUYBACK_EXECUTE',
    # Buyback через подконтрольную организацию — для event-study неотличим
    # от прямого выкупа эмитентом, кладётся под тот же тег.
    'Приобретение подконтрольной эмитенту организацией голосующих акций (долей) эмитента или депозитарных расписок на акции эмитента':
        'BUYBACK_EXECUTE',
    # SPO — отчуждение собственных или казначейских акций (продажа в рынок).
    # Симметрично BUYBACK_EXECUTE по экономическому смыслу, реакция котировок
    # обратная. Покрывает оба варианта — самим эмитентом и через подконтрольную.
    'Отчуждение эмитентом собственных голосующих акций (долей) или депозитарных расписок на акции эмитента':
        'SPO',
    'Отчуждение подконтрольной эмитенту организацией голосующих акций (долей) эмитента или депозитарных расписок на акции эмитента':
        'SPO',
}


class CookieExpired(Exception):
    """API ответил не-JSON: WAF challenge или истёкшая сессия."""


# ── fetch ─────────────────────────────────────────────────────────────────

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


def _fetch_page(session: requests.Session, inn: str,
                date_from: date, date_till: date, page: int) -> dict:
    r = session.post(ENDPOINT, data=_build_payload(inn, date_from, date_till, page),
                     timeout=TIMEOUTS, allow_redirects=True)
    ct = r.headers.get('Content-Type', '')
    if not ct.lower().startswith('application/json'):
        raise CookieExpired(
            f'API вернул не-JSON (status={r.status_code}, Content-Type={ct!r}). '
            'WAF не пропустил запрос; обновите cookies сессии.'
        )
    return r.json()


def _fetch_window(session: requests.Session, inn: str,
                  date_from: date, date_till: date, depth: int = 0) -> list[dict]:
    """Все события за окно дат с авто-дроблением при превышении лимита API."""
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
    with pg.cursor() as cur:
        cur.execute(
            'SELECT DISTINCT e.emitter_id, e.inn '
            'FROM emitters e JOIN stocks s ON s.emitter_id = e.emitter_id '
            'ORDER BY e.inn'
        )
        return [(int(eid), inn) for eid, inn in cur.fetchall()]


def _out_path(inn: str) -> str:
    return os.path.join(OUT_DIR, f'{inn}.json')


def fetch() -> None:
    import psycopg

    pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
    session = _build_session()
    with psycopg.connect(pg_dsn, autocommit=True) as pg:
        emitters = _load_emitters_from_db(pg)

    smoke_inns_raw = (os.environ.get('EDISCLOSURE_SMOKE_INNS')
                      or os.environ.get('EDISCLOSURE_SMOKE_INN'))
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
            raise

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


# ── load ──────────────────────────────────────────────────────────────────

def _normalize_event_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name).strip()


def load(pg) -> None:
    """Заливает корпоративные события из data/events/edisclosure/*.json.

    На каждое событие: одна строка в `events` (id = `edisc:<pseudoGUID>`),
    плюс связи в `event_tags` — тег типа события и теги всех бумаг
    эмитента из stocks. Параллельно заполняется emitters.e_disclosure_company_id.
    """
    files = sorted(glob(os.path.join(OUT_DIR, '*.json')))
    if not files:
        print('  Нет файлов edisclosure/*.json — пропускаем')
        return

    with pg.cursor() as cur:
        cur.execute("SELECT code FROM tags WHERE type = 'company'")
        company_tags = {r[0] for r in cur.fetchall()}
        cur.execute(
            'SELECT emitter_id, ticker FROM stocks WHERE emitter_id IS NOT NULL'
        )
        tickers_by_emitter: dict[int, list[str]] = {}
        for emitter_id, ticker in cur.fetchall():
            if ticker in company_tags:
                tickers_by_emitter.setdefault(emitter_id, []).append(ticker)

    event_rows: list[tuple] = []
    tag_rows: list[tuple] = []
    company_id_updates: dict[int, int] = {}
    unknown_types: dict[str, str] = {}
    files_without_tickers: list[str] = []

    for path in files:
        with open(path, encoding='utf-8') as fh:
            snap = json.load(fh)
        inn = snap['inn']
        emitter_id = snap['emitter_id']
        tickers = tickers_by_emitter.get(emitter_id, [])
        if not tickers:
            files_without_tickers.append(os.path.basename(path))
            continue

        for raw in snap['events']:
            event_name = _normalize_event_name(raw['eventName'])
            tag = EDISCLOSURE_EVENT_NAME_TO_TAG.get(event_name)
            if tag is None:
                unknown_types.setdefault(event_name, os.path.basename(path))
                continue
            pseudo_guid = raw['pseudoGUID']
            event_id = f'edisc:{pseudo_guid}'
            pub_date = raw['pubDate'][:10]
            nominal_date = raw['eventDate'][:10]
            payload = json.dumps({
                'pseudoGUID': pseudo_guid,
                'inn': inn,
                'emitter_id': emitter_id,
                'company_id_edisclosure': raw.get('companyID'),
                'agency': raw.get('agency'),
                'nominal_date': nominal_date,
            })
            # event_date = announce_date = pub_date: раскрытие влияет на рынок
            # в момент публикации, а не на номинальную дату корпоративного
            # действия (заседание/отчётный период) — та уходит в payload как
            # справочная.
            event_rows.append((event_id, pub_date, pub_date, event_name, payload))
            tag_rows.append((event_id, tag))
            for ticker in tickers:
                tag_rows.append((event_id, ticker))

            cid = raw.get('companyID')
            if cid is not None and emitter_id not in company_id_updates:
                company_id_updates[emitter_id] = cid

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events (id, event_date, announce_date, event, payload) '
            'VALUES (%s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            event_rows,
        )
        cur.executemany(
            'INSERT INTO event_tags (event_id, tag_code) VALUES (%s, %s) '
            'ON CONFLICT (event_id, tag_code) DO NOTHING',
            tag_rows,
        )
        cur.executemany(
            'UPDATE emitters SET e_disclosure_company_id = %s '
            'WHERE emitter_id = %s AND e_disclosure_company_id IS NULL',
            [(cid, eid) for eid, cid in company_id_updates.items()],
        )

    print(f'  events (e-disclosure): {len(event_rows)} attempted, '
          f'event_tags: {len(tag_rows)} attempted, '
          f'company_id обновлено у {len(company_id_updates)} эмитентов')
    if files_without_tickers:
        print(f'  пропущено файлов (эмитент не в stocks): {len(files_without_tickers)}')
    if unknown_types:
        print(f'  WARNING: {len(unknown_types)} неизвестных типов событий:')
        for name, fname in list(unknown_types.items())[:5]:
            print(f'    "{name[:80]}" ({fname})')


# ── direct run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='только fetch')
    parser.add_argument('--load', action='store_true', help='только load в БД')
    args = parser.parse_args()
    do_fetch = args.fetch or not args.load
    do_load = args.load or not args.fetch

    if do_fetch:
        fetch()
    if do_load:
        pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
        with psycopg.connect(pg_dsn) as pg:
            load(pg)
            pg.commit()
