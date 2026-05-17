"""Загрузчик ключевой ставки ЦБ РФ с cbr.ru в CSV.

Источник: https://www.cbr.ru/hd_base/KeyRate/?UniDbQuery.Posted=True&
          UniDbQuery.From=DD.MM.YYYY&UniDbQuery.To=DD.MM.YYYY
Кодировка ответа: cp1251.

Страница отдаёт посуточный ряд: одна строка на каждый календарный день,
значение ставки повторяется до следующего изменения. Парсер дедуплицирует
подряд равные значения и оставляет только **даты изменения ставки** —
именно это нужно для events.

Ставка рефинансирования (1992–2015) **не грузится**: cbr.ru через
hd_base-интерфейс эту страницу больше не отдаёт. См. `todo.md` и план
`~/.claude/plans/functional-gathering-boot.md`.

Идемпотентность: если CSV уже существует, читается последняя дата и
парсинг продолжается со следующего дня. Чтобы перезалить с нуля —
удалить CSV.

Запуск:
    python scripts/load_cb_rates.py [--start DD.MM.YYYY] [--end DD.MM.YYYY]
По умолчанию: 17.09.2013 — сегодня (полная история ключевой ставки).

Выходной CSV: data/macro/cb_rates.csv
Колонки: effective_date (ISO), rate_pct (float), rate_type ('key').
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
from datetime import date, datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    """Парсит таблицу cbr.ru → список (дата, ставка) по убыванию даты."""
    out: list[tuple[date, float]] = []
    for m in _ROW_RE.finditer(html):
        d = datetime.strptime(m.group('date'), '%d.%m.%Y').date()
        r = float(m.group('rate').replace(',', '.'))
        out.append((d, r))
    return out


def _extract_change_dates(
    daily: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    """Из посуточного ряда оставляет только даты изменения ставки.

    На входе ряд по убыванию (как отдаёт cbr.ru). Возвращает по
    возрастанию: каждая точка — первый день, когда установлено новое
    значение ставки.
    """
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


def _parse_arg_date(s: str) -> date:
    return datetime.strptime(s, '%d.%m.%Y').date()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=_parse_arg_date, default=KEY_RATE_HISTORY_START)
    parser.add_argument('--end', type=_parse_arg_date, default=date.today())
    args = parser.parse_args()

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    last_in_csv = _last_date_in_csv(CSV_PATH, 'key')
    file_exists = os.path.exists(CSV_PATH)

    # Запрашиваем шире на 30 дней назад относительно последней даты в БД —
    # хватает, чтобы поймать предыдущее значение для проверки изменения.
    if last_in_csv is not None:
        fetch_start = min(args.start, last_in_csv)
    else:
        fetch_start = args.start
    fetch_end = args.end

    if fetch_start > fetch_end:
        print(f'Нечего догружать: последняя дата в CSV {last_in_csv}, конец диапазона {fetch_end}')
        return

    print(f'Запрос cbr.ru/hd_base/KeyRate/ за {fetch_start} … {fetch_end}')
    html = _fetch_html(fetch_start, fetch_end)
    daily = _parse_daily_rates(html)
    if not daily:
        print('ОШИБКА: таблица пуста или не распарсилась')
        sys.exit(1)
    changes = _extract_change_dates(daily)
    print(f'  посуточных строк: {len(daily)}, дат изменения: {len(changes)}')

    # При инкременте — отрезаем уже залитую часть.
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


if __name__ == '__main__':
    main()
