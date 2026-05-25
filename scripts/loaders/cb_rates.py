"""Лоадер: решения ЦБ РФ по ключевой ставке.

Стадии:
- `fetch()` — парсит cbr.ru/hd_base/KeyRate/, схлопывает посуточный ряд
  до дат изменения ставки. Дописывает в `data/macro/cb_rates.csv`
  инкрементально (от последней даты в файле). Ставка рефинансирования
  (1992–2015) не грузится: cbr.ru через hd_base-интерфейс эту страницу
  больше не отдаёт. Кодировка ответа: cp1251.
- `load(pg)` — читает CSV и создаёт события `CB_RATE_DECISION` в `events`
  с приближением `announcement_date = effective_date - 1 BD`. Тег
  `CB_RATE_DECISION` без тегов-тикеров (макрособытие). Идентификатор
  события — детерминированный UUID5 от (rate_type, effective_iso).
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(ROOT, 'data', 'macro', 'cb_rates.csv')
COLUMNS = ['effective_date', 'rate_pct', 'rate_type']

KEY_RATE_HISTORY_START = date(2013, 9, 17)
KEY_RATE_URL = (
    'https://www.cbr.ru/hd_base/KeyRate/'
    '?UniDbQuery.Posted=True&UniDbQuery.From={start}&UniDbQuery.To={end}'
)
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3

_ROW_RE = re.compile(
    r'<tr>\s*<td>(?P<date>\d{2}\.\d{2}\.\d{4})</td>\s*'
    r'<td>(?P<rate>[\d,]+)</td>\s*</tr>'
)

_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000002')


# ── fetch ─────────────────────────────────────────────────────────────────

def _fetch_html(start: date, end: date) -> str:
    url = KEY_RATE_URL.format(
        start=start.strftime('%d.%m.%Y'),
        end=end.strftime('%d.%m.%Y'),
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as r:
                return r.read().decode('cp1251', errors='replace')
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f'failed after {MAX_RETRIES} retries: {last_err}')


def _parse_daily_rates(html: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for m in _ROW_RE.finditer(html):
        d = datetime.strptime(m.group('date'), '%d.%m.%Y').date()
        r = float(m.group('rate').replace(',', '.'))
        out.append((d, r))
    return out


def _extract_change_dates(daily: list[tuple[date, float]]) -> list[tuple[date, float]]:
    if not daily:
        return []
    ascending = sorted(daily, key=lambda x: x[0])
    changes: list[tuple[date, float]] = [ascending[0]]
    for d, r in ascending[1:]:
        if r != changes[-1][1]:
            changes.append((d, r))
    return changes


def _last_date_in_csv(path: str, rate_type: str) -> date | None:
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != COLUMNS:
            raise ValueError(f'CSV-заголовок не совпадает: {header}')
        last: str | None = None
        for row in reader:
            if not row or row[2] != rate_type:
                continue
            last = row[0]
    return date.fromisoformat(last) if last else None


def fetch(start: date = KEY_RATE_HISTORY_START, end: date | None = None) -> None:
    end = end or date.today()
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    last_in_csv = _last_date_in_csv(CSV_PATH, 'key')
    file_exists = os.path.exists(CSV_PATH)

    fetch_start = min(start, last_in_csv) if last_in_csv is not None else start
    fetch_end = end

    if fetch_start > fetch_end:
        print(f'Нечего догружать: последняя дата в CSV {last_in_csv}, конец диапазона {fetch_end}')
        return

    print(f'Запрос cbr.ru/hd_base/KeyRate/ за {fetch_start} … {fetch_end}')
    html = _fetch_html(fetch_start, fetch_end)
    daily = _parse_daily_rates(html)
    if not daily:
        raise RuntimeError('таблица пуста или не распарсилась')
    changes = _extract_change_dates(daily)
    print(f'  посуточных строк: {len(daily)}, дат изменения: {len(changes)}')

    if last_in_csv is not None:
        changes = [(d, r) for d, r in changes if d > last_in_csv]
        print(f'  новых дат изменения после {last_in_csv}: {len(changes)}')

    if not changes:
        print('Нет новых решений — CSV не меняется.')
        return

    mode = 'a' if file_exists else 'w'
    with open(CSV_PATH, mode, encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(COLUMNS)
        for d, r in changes:
            writer.writerow([d.isoformat(), f'{r:g}', 'key'])
    print(f'Готово. Дописано {len(changes)} строк в {CSV_PATH}')


# ── load ──────────────────────────────────────────────────────────────────

def _shift_business_day(d: date, offset: int) -> date:
    """Сдвиг на N рабочих дней (без учёта праздников).

    Приближение announcement_date решения ЦБ как `effective_date - 1 BD`.
    Точная дата пресс-релиза лежит на cbr.ru/dkp/decisions/ — отдельная итерация.
    """
    return (pd.Timestamp(d) + pd.tseries.offsets.BDay(offset)).date()


def _format_event_text(rate_type: str, rate: float, prev: float | None, direction: str) -> str:
    name = 'ключевой ставки' if rate_type == 'key' else 'ставки рефинансирования'
    if direction == 'initial':
        return f'Установление {name}: {rate:g}%'
    if direction == 'hold':
        return f'Сохранение {name} на уровне {rate:g}%'
    arrow = '↑' if direction == 'hike' else '↓'
    return f'Изменение {name}: {prev:g}% → {rate:g}% {arrow}'


def _make_event_id(rate_type: str, effective_iso: str) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, f'CB_RATE_DECISION_{rate_type}_{effective_iso}'))


def load(pg) -> None:
    if not os.path.exists(CSV_PATH):
        print(f'  {CSV_PATH} не найден — пропускаем ставку ЦБ')
        return
    df = pd.read_csv(CSV_PATH, dtype={'rate_type': str})
    df['effective_date'] = pd.to_datetime(df['effective_date']).dt.date
    df['rate_pct'] = pd.to_numeric(df['rate_pct'])
    df = df.sort_values(['rate_type', 'effective_date']).reset_index(drop=True)

    event_rows: list[tuple] = []
    tag_rows: list[tuple] = []
    for rate_type, group in df.groupby('rate_type', sort=False):
        prev_rate: float | None = None
        for _, r in group.iterrows():
            effective = r['effective_date']
            rate = float(r['rate_pct'])
            if prev_rate is None:
                direction = 'initial'
                change_bp = None
            elif rate > prev_rate:
                direction = 'hike'
                change_bp = int(round((rate - prev_rate) * 100))
            elif rate < prev_rate:
                direction = 'cut'
                change_bp = int(round((rate - prev_rate) * 100))
            else:
                direction = 'hold'
                change_bp = 0

            announce = _shift_business_day(effective, -1)
            event_id = _make_event_id(rate_type, effective.isoformat())
            payload = json.dumps({
                'rate_type': rate_type,
                'rate_pct': rate,
                'rate_pct_prev': prev_rate,
                'change_bp': change_bp,
                'direction': direction,
                'effective_date': effective.isoformat(),
            })
            event_text = _format_event_text(rate_type, rate, prev_rate, direction)
            event_rows.append((event_id, announce, announce, None, event_text, payload))
            tag_rows.append((event_id, 'CB_RATE_DECISION'))
            prev_rate = rate

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, date_start, announce_date, date_end, event, payload) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            event_rows,
        )
        cur.executemany(
            'INSERT INTO event_tags (event_id, tag_code) VALUES (%s, %s) '
            'ON CONFLICT (event_id, tag_code) DO NOTHING',
            tag_rows,
        )
    print(f'  events (ЦБ ставка): {len(event_rows)} attempted')


# ── direct run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    import psycopg

    def _parse_arg_date(s: str) -> date:
        return datetime.strptime(s, '%d.%m.%Y').date()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='только fetch')
    parser.add_argument('--load', action='store_true', help='только load в БД')
    parser.add_argument('--start', type=_parse_arg_date, default=KEY_RATE_HISTORY_START)
    parser.add_argument('--end', type=_parse_arg_date, default=date.today())
    args = parser.parse_args()
    do_fetch = args.fetch or not args.load
    do_load = args.load or not args.fetch

    if do_fetch:
        fetch(args.start, args.end)
    if do_load:
        pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
        with psycopg.connect(pg_dsn) as pg:
            load(pg)
            pg.commit()
