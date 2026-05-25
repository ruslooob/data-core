"""Лоадер: ставки межбанковского рынка с mfd.ru → синтетический SAVINGS_MIACR.

Стадии:
- `fetch()` — для каждого рабочего дня скачивает страницу
  `mfd.ru/credits/centrobank/?selectedDate=...`, парсит таблицу
  6 сроков (1, 7, 30, 90, 180, 360 дней) × 3 ставки (MIBID, MIBOR,
  MIACR). Сохраняет в `data/stocks/mfd_rates.csv`. Идемпотентно:
  читает последнюю дату в CSV и продолжает со следующего рабочего дня.
- `load(pg)` — генерирует синтетический тикер `SAVINGS_MIACR` из
  овернайт-ставки MIACR (тенор=1, ACT/365, сложный процент с
  начальной ценой 1000). Используется как безрисковый бенчмарк и
  источник R_f для Sharpe.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(ROOT, 'data', 'stocks', 'mfd_rates.csv')

TENORS = (1, 7, 30, 90, 180, 360)
RATE_TYPES = ('mibid', 'mibor', 'miacr')
COLUMNS = ['date'] + [f'{rt}_{t}' for t in TENORS for rt in RATE_TYPES]

REQUEST_DELAY_SEC = 0.25
MAX_RETRIES = 3

_TABLE_RE = re.compile(r'<th>MIBID</th>.*?</table>', re.DOTALL)
_ROW_RE = re.compile(
    r'<tr>\s*'
    r'<td[^>]*>(?P<tenor>\d+)</td>\s*'
    r'<td[^>]*>(?P<mibid>.*?)</td>\s*'
    r'<td[^>]*>(?P<mibor>.*?)</td>\s*'
    r'<td[^>]*>(?P<miacr>.*?)</td>\s*'
    r'</tr>',
    re.DOTALL,
)

_SAVINGS_TICKER = 'SAVINGS_MIACR'
_SAVINGS_NAME = 'Накопительный счёт MIACR'
_SAVINGS_INITIAL_PRICE = 1000.0
_DAYS_IN_YEAR = 365


# ── fetch ─────────────────────────────────────────────────────────────────

def _parse_value(s: str) -> float | None:
    if 'N/A' in s or 'mfd-na' in s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_rates_for_date(d: date) -> dict[int, dict[str, float | None]] | None:
    url = f'https://mfd.ru/credits/centrobank/?selectedDate={d.strftime("%d.%m.%Y")}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode('utf-8', errors='replace')
            break
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f'failed after {MAX_RETRIES} retries: {last_err}')

    m = _TABLE_RE.search(html)
    if not m:
        return None
    table = m.group(0)
    result: dict[int, dict[str, float | None]] = {}
    for row in _ROW_RE.finditer(table):
        result[int(row.group('tenor'))] = {
            'mibid': _parse_value(row.group('mibid')),
            'mibor': _parse_value(row.group('mibor')),
            'miacr': _parse_value(row.group('miacr')),
        }
    return result if result else None


def _workday_iter(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _row_for(d: date, rates: dict[int, dict[str, float | None]]) -> list:
    row: list = [d.isoformat()]
    for t in TENORS:
        cell = rates.get(t, {})
        for rt in RATE_TYPES:
            v = cell.get(rt)
            row.append('' if v is None else f'{v:g}')
    return row


def _last_date_in_csv(path: str) -> date | None:
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != COLUMNS:
            raise ValueError(f'CSV-заголовок не совпадает: {header}')
        last: str | None = None
        for r in reader:
            if r:
                last = r[0]
    return date.fromisoformat(last) if last else None


def fetch(start: date = date(2000, 8, 1), end: date | None = None,
          force_start: bool = False) -> None:
    end = end or date.today()
    last_in_csv = _last_date_in_csv(CSV_PATH)
    file_exists = last_in_csv is not None
    fetch_start = start
    if last_in_csv is not None and not force_start:
        fetch_start = max(start, last_in_csv + timedelta(days=1))

    if fetch_start > end:
        print(f'Нечего догружать: последняя дата в CSV {last_in_csv}, конец диапазона {end}')
        return

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    workdays = list(_workday_iter(fetch_start, end))
    print(f'Парсинг {len(workdays)} рабочих дней с {fetch_start} по {end}')
    if file_exists:
        print(f'Догружаем к существующему CSV (последняя дата {last_in_csv})')
    else:
        print(f'Создаём новый CSV: {CSV_PATH}')

    mode = 'a' if file_exists else 'w'
    with open(CSV_PATH, mode, encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(COLUMNS)

        n_with_data = 0
        n_empty = 0
        for i, d in enumerate(workdays):
            try:
                rates = _fetch_rates_for_date(d)
            except Exception as e:
                print(f'  [{i + 1}/{len(workdays)}] {d}: ОШИБКА {e}', flush=True)
                continue
            if rates is None:
                n_empty += 1
            else:
                writer.writerow(_row_for(d, rates))
                n_with_data += 1
                f.flush()
            if (i + 1) % 50 == 0 or i == len(workdays) - 1:
                print(
                    f'  [{i + 1}/{len(workdays)}] {d}  '
                    f'данные={n_with_data}, пусто={n_empty}',
                    flush=True,
                )
            time.sleep(REQUEST_DELAY_SEC)

    print(f'\nГотово. CSV: {CSV_PATH}')
    print(f'  записано строк: {n_with_data}')
    print(f'  пропущено пустых: {n_empty}')


# ── load ──────────────────────────────────────────────────────────────────

def load(pg) -> None:
    """Капитализованный индекс под овернайт-ставку MIACR.

    Цена начинается с 1000 и растёт по формуле сложного процента между
    соседними торговыми днями `mfd_rates.csv`: за выходные применяется
    ставка предыдущего рабочего дня за фактическое число календарных
    дней. ACT/365.
    """
    if not os.path.exists(CSV_PATH):
        print(f'  {CSV_PATH} не найден — пропускаем SAVINGS_MIACR')
        return
    df = pd.read_csv(CSV_PATH)[['date', 'miacr_1']].dropna()
    if df.empty:
        print(f'  {CSV_PATH}: miacr_1 пуст — пропускаем SAVINGS_MIACR')
        return
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.sort_values('date').reset_index(drop=True)

    prices = [_SAVINGS_INITIAL_PRICE]
    for i in range(1, len(df)):
        prev_rate = float(df.miacr_1.iloc[i - 1])
        days = (df.date.iloc[i] - df.date.iloc[i - 1]).days
        prices.append(prices[-1] * (1 + prev_rate / 100 * days / _DAYS_IN_YEAR))

    with pg.cursor() as cur:
        cur.execute(
            'INSERT INTO stocks (ticker, name) VALUES (%s, %s) '
            'ON CONFLICT (ticker) DO NOTHING',
            [_SAVINGS_TICKER, _SAVINGS_NAME],
        )
        rows = [
            (_SAVINGS_TICKER, df.date.iloc[i], p, p, p, p, 0.0, None)
            for i, p in enumerate(prices)
        ]
        cur.executemany(
            'INSERT INTO stock_candles '
            '(ticker, candle_date, open, high, low, close, volume, open_interest) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) '
            'ON CONFLICT (ticker, candle_date) DO NOTHING',
            rows,
        )
    print(
        f'  {_SAVINGS_TICKER:<14} {len(rows):6d} candles  '
        f'({_SAVINGS_NAME}, P[0]={_SAVINGS_INITIAL_PRICE:.0f} → P[-1]={prices[-1]:.2f})'
    )


# ── direct run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    import psycopg

    def _parse_arg_date(s: str) -> date:
        return datetime.strptime(s, '%d.%m.%Y').date()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='только fetch')
    parser.add_argument('--load', action='store_true', help='только load в БД')
    parser.add_argument('--start', type=_parse_arg_date, default=date(2000, 8, 1))
    parser.add_argument('--end', type=_parse_arg_date, default=date.today())
    parser.add_argument('--force-start', action='store_true',
                        help='игнорировать последнюю дату в CSV')
    args = parser.parse_args()
    do_fetch = args.fetch or not args.load
    do_load = args.load or not args.fetch

    if do_fetch:
        fetch(args.start, args.end, args.force_start)
    if do_load:
        pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
        with psycopg.connect(pg_dsn) as pg:
            load(pg)
            pg.commit()
