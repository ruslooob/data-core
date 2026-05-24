"""Выгружает с MOEX ISS перечень ценных бумаг фондового рынка и связанных эмитентов.

Двухпроходный:
  Pass 1 — батч-листинг `/iss/securities.json?engine=stock&market=shares`
           (тикеры, ИНН, ОКПО эмитентов, базовые поля бумаги).
  Pass 2 — поштучно `/iss/securities/{ticker}.json`, обогащает каждую бумагу
           недостающими полями (LATNAME, ISSUEDATE, ISSUESIZE, FACEVALUE,
           FACEUNIT, LISTLEVEL).

Результат — два сырых CSV в data/stocks/. В БД не пишет (заливку делает
scripts/load_data_to_postgres.py).

См. docs/drafts/SPEC_CORP_DISCLOSURE_DRAFT.md, этап 2.
"""
from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Iterator

import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'stocks')

LIST_ENDPOINT = 'https://iss.moex.com/iss/securities.json'
LIST_PARAMS = {'iss.meta': 'off', 'engine': 'stock', 'market': 'shares', 'limit': '100'}

DETAIL_ENDPOINT_TEMPLATE = 'https://iss.moex.com/iss/securities/{ticker}.json'
DETAIL_PARAMS = {'iss.meta': 'off'}

# Поля, которые забираем из секции `description` карточки бумаги.
DETAIL_FIELDS = ('LATNAME', 'ISSUEDATE', 'ISSUESIZE', 'FACEVALUE', 'FACEUNIT', 'LISTLEVEL')

# Колонки выходных CSV — соответствуют будущим колонкам таблиц.
SECURITY_COLUMNS = [
    'ticker', 'emitter_id', 'isin', 'regnumber',
    'full_name', 'short_name', 'latname',
    'security_type', 'list_level',
    'issue_size', 'face_value', 'face_unit', 'issue_date',
    'primary_boardid',
]
EMITTER_COLUMNS = ['emitter_id', 'inn', 'okpo', 'title']

# Спот-чек после Pass 1: знакомые эмитенты, проверенные руками при ресёрче.
KNOWN_EMITTER_IDS = {'LKOH': 770, 'SBER': 484, 'SBERP': 484, 'GAZP': 711}

# Параллелизм Pass 2: ISS не блокирует на 10 потоков, скорость ~10x.
PASS2_WORKERS = 10


def _fetch_listing() -> Iterator[dict]:
    """Pass 1: пагинированный обход батч-листинга.

    Тянет страницы, пока сервер возвращает непустую страницу. Курсорная
    секция в ответе нестабильна для этого endpoint, поэтому опираемся
    на пустую страницу как сигнал конца.
    """
    start = 0
    while True:
        params = dict(LIST_PARAMS, start=str(start))
        r = requests.get(LIST_ENDPOINT, params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        sec = j['securities']
        cols, data = sec['columns'], sec['data']
        if not data:
            return
        for row in data:
            yield dict(zip(cols, row))
        start += len(data)


def _split_listing(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Разделяет батч-выгрузку на список бумаг с российским эмитентом и список эмитентов.

    P0: пропускаем бумаги без emitter_id или без ИНН (иностранные DR,
    фиксинги, индексы) — для них нет российского эмитента, события на
    e-disclosure тоже не загружаются.
    """
    securities: list[dict] = []
    emitters_map: dict[int, dict] = {}
    for r in rows:
        emitter_id = r.get('emitent_id')
        inn = r.get('emitent_inn')
        if emitter_id is None or not inn:
            continue
        securities.append({
            'ticker': r['secid'],
            'emitter_id': emitter_id,
            'isin': r.get('isin'),
            'regnumber': r.get('regnumber'),
            'full_name': r.get('name'),
            'short_name': r.get('shortname'),
            'security_type': r.get('type'),
            'primary_boardid': r.get('primary_boardid'),
            # Pass 2 заполнит:
            'latname': None,
            'list_level': None,
            'issue_size': None,
            'face_value': None,
            'face_unit': None,
            'issue_date': None,
        })
        if emitter_id not in emitters_map:
            emitters_map[emitter_id] = {
                'emitter_id': emitter_id,
                'inn': inn,
                'okpo': r.get('emitent_okpo'),
                'title': r['emitent_title'],
            }
    return securities, list(emitters_map.values())


def _fetch_detail(ticker: str, session: requests.Session) -> dict:
    """Pass 2: одна бумага. Возвращает dict с шестью полями из description."""
    r = session.get(
        DETAIL_ENDPOINT_TEMPLATE.format(ticker=ticker),
        params=DETAIL_PARAMS, timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    desc = j.get('description', {})
    cols = desc.get('columns', [])
    rows = desc.get('data', [])
    name_idx = cols.index('name') if 'name' in cols else None
    value_idx = cols.index('value') if 'value' in cols else None
    extracted: dict = {f: None for f in DETAIL_FIELDS}
    if name_idx is None or value_idx is None:
        return extracted
    for row in rows:
        n = row[name_idx]
        if n in DETAIL_FIELDS:
            extracted[n] = row[value_idx]
    return {
        'latname': extracted['LATNAME'],
        'list_level': extracted['LISTLEVEL'],
        'issue_size': extracted['ISSUESIZE'],
        'face_value': extracted['FACEVALUE'],
        'face_unit': extracted['FACEUNIT'],
        'issue_date': extracted['ISSUEDATE'],
    }


def _enrich(securities: list[dict]) -> None:
    """Pass 2: параллельное обогащение каждой бумаги. Мутирует входной список."""
    session = requests.Session()
    total = len(securities)
    done = 0
    with ThreadPoolExecutor(max_workers=PASS2_WORKERS) as pool:
        futures = {pool.submit(_fetch_detail, s['ticker'], session): s for s in securities}
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                s.update(fut.result())
            except Exception as e:
                raise RuntimeError(f'Pass 2 упал на тикере {s["ticker"]}: {e}') from e
            done += 1
            if done % 100 == 0 or done == total:
                print(f'  Pass 2: {done}/{total} тикеров обогащены')


def _sanity(securities: list[dict], emitters: list[dict]) -> None:
    seen_inns: set[str] = set()
    for e in emitters:
        inn = str(e['inn'])
        if not inn.isdigit():
            raise ValueError(f'ИНН не цифровой: emitter_id={e["emitter_id"]} inn={inn!r}')
        if len(inn) not in (10, 12):
            raise ValueError(
                f'ИНН неправильной длины: emitter_id={e["emitter_id"]} inn={inn} (len={len(inn)})'
            )
        if inn in seen_inns:
            raise ValueError(f'Дубль ИНН в выгрузке эмитентов: {inn}')
        seen_inns.add(inn)
        if not e['title']:
            raise ValueError(f'Пустой title у эмитента {e["emitter_id"]}')

    seen_tickers: set[str] = set()
    for s in securities:
        if s['ticker'] in seen_tickers:
            raise ValueError(f'Дубль тикера: {s["ticker"]}')
        seen_tickers.add(s['ticker'])
        if not isinstance(s['emitter_id'], int):
            raise ValueError(f'emitter_id не integer: {s["ticker"]} {s["emitter_id"]!r}')


def _cross_validate(securities: list[dict]) -> None:
    """Спот-чек: знакомые эмитенты должны совпадать с тем, что мы видели руками."""
    by_ticker = {s['ticker']: s for s in securities}
    misses = []
    for ticker, expected_emitter_id in KNOWN_EMITTER_IDS.items():
        s = by_ticker.get(ticker)
        if s is None:
            misses.append(f'{ticker} отсутствует в выгрузке')
            continue
        if s['emitter_id'] != expected_emitter_id:
            misses.append(
                f'{ticker}: emitter_id={s["emitter_id"]}, ожидался {expected_emitter_id}'
            )
    if misses:
        raise ValueError('Cross-validation провален:\n  ' + '\n  '.join(misses))
    print('  cross-validation OK: ' + ', '.join(
        f'{t}={KNOWN_EMITTER_IDS[t]}' for t in KNOWN_EMITTER_IDS
    ))


def _write_csv(rows: list[dict], path: str, columns: list[str]) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: ('' if r.get(c) is None else r.get(c)) for c in columns})


def _is_fresh(path: str) -> bool:
    """Файл считается свежим, если изменялся сегодня."""
    if not os.path.exists(path):
        return False
    mtime_day = date.fromtimestamp(os.path.getmtime(path))
    return mtime_day == date.today()


def main() -> None:
    sec_path = os.path.join(OUT_DIR, 'moex_securities.csv')
    em_path = os.path.join(OUT_DIR, 'moex_emitters.csv')

    if _is_fresh(sec_path) and _is_fresh(em_path):
        print('Файлы уже обновлены сегодня — выгрузка пропущена (идемпотентность).')
        print(f'  {sec_path}')
        print(f'  {em_path}')
        return

    print(f'Pass 1: батч-листинг {LIST_ENDPOINT}')
    rows = list(_fetch_listing())
    print(f'  получено строк (с учётом всех типов): {len(rows)}')

    securities, emitters = _split_listing(rows)
    print(f'  бумаги с российским эмитентом: {len(securities)}')
    print(f'  уникальных эмитентов: {len(emitters)}')

    print(f'Pass 2: поштучное обогащение карточек ({PASS2_WORKERS} потоков)')
    _enrich(securities)

    print('Sanity-проверки…')
    _sanity(securities, emitters)
    _cross_validate(securities)

    _write_csv(securities, sec_path, SECURITY_COLUMNS)
    _write_csv(emitters, em_path, EMITTER_COLUMNS)
    print('Записано:')
    print(f'  {sec_path}  ({len(securities)} строк)')
    print(f'  {em_path}  ({len(emitters)} строк)')


if __name__ == '__main__':
    main()
