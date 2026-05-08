"""Загрузчик ставок MIBID/MIBOR/MIACR ЦБ РФ с mfd.ru в CSV.

Источник: https://mfd.ru/credits/centrobank/?selectedDate=DD.MM.YYYY

На каждый рабочий день (пн-пт) делается один HTTP-запрос; парсится
таблица 6 сроков (1, 7, 30, 90, 180, 360 дней) × 3 ставки (MIBID,
MIBOR, MIACR). Выходные пропускаются.

Идемпотентность: если CSV уже существует, читается последняя дата
и парсинг продолжается со следующей. Чтобы перезалить с нуля —
удалить CSV.

Запуск:
    python scripts/load_mfd_rates.py [--start DD.MM.YYYY] [--end DD.MM.YYYY]
По умолчанию: 01.08.2000 — сегодня.

Выходной CSV: data/stocks/mfd_rates.csv
Колонки: date, {mibid|mibor|miacr}_{1|7|30|90|180|360}
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, 'data', 'stocks', 'mfd_rates.csv')
TENORS = (1, 7, 30, 90, 180, 360)
RATE_TYPES = ('mibid', 'mibor', 'miacr')
COLUMNS = ['date'] + [f'{rt}_{t}' for t in TENORS for rt in RATE_TYPES]

REQUEST_DELAY_SEC = 0.25  # пауза между запросами, чтобы не злить mfd.ru
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


def fetch_rates_for_date(d: date) -> dict[int, dict[str, float | None]] | None:
    """Один HTTP-запрос на дату. None если страница без таблицы."""
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


def workday_iter(start: date, end: date):
    """Yield все будние даты включительно [start, end]."""
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


def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%d.%m.%Y').date()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=_parse_date, default=date(2000, 8, 1))
    parser.add_argument('--end', type=_parse_date, default=date.today())
    parser.add_argument(
        '--force-start',
        action='store_true',
        help='использовать --start как есть, игнорируя последнюю дату в CSV '
             '(нужно для перезаписи диапазона; добавляет к существующему CSV)',
    )
    args = parser.parse_args()

    last_in_csv = _last_date_in_csv(CSV_PATH)
    file_exists = last_in_csv is not None
    start = args.start
    if last_in_csv is not None and not args.force_start:
        start = max(start, last_in_csv + timedelta(days=1))
    end = args.end

    if start > end:
        print(f'Нечего догружать: последняя дата в CSV {last_in_csv}, конец диапазона {end}')
        return

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    workdays = list(workday_iter(start, end))
    print(f'Парсинг {len(workdays)} рабочих дней с {start} по {end}')
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
                rates = fetch_rates_for_date(d)
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


if __name__ == '__main__':
    main()
