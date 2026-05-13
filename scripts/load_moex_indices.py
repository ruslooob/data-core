"""Парсит исторические значения индексов Мосбиржи через ISS API.

Использование:
    python scripts/load_moex_indices.py                # дефолтный список
    python scripts/load_moex_indices.py RGBITR         # один тикер
    python scripts/load_moex_indices.py RGBITR MCFTR

Кладёт результат в `data/stocks/<TICKER>_<safe_name>_1day.txt`
в Finam-формате — этот формат `scripts/load_data_to_postgres.py` уже
умеет читать без изменений.

Идемпотентно: повторный запуск перезаписывает файл индекса, удалив
старые копии с другим диапазоном дат. Загрузка в БД позже сделает
INSERT ... ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = REPO_ROOT / 'data' / 'stocks'

ISS_URL = (
    'https://iss.moex.com/iss/history/engines/stock/markets/index/'
    'securities/{ticker}.json'
)

# Поля Finam-формата (порядок важен — он же в _load_normalized_candles).
FINAM_HEADER = (
    '<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>'
)

# Поля ISS-ответа, которые забираем.
ISS_FIELDS = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VALUE')

DEFAULT_INDICES = ['RGBITR', 'RGBI', 'MCFTR', 'RTSI']

PAGE_LIMIT = 100
REQUEST_TIMEOUT_SEC = 30
RETRY_PAUSE_SEC = 2
MAX_RETRIES = 3


def _fetch_page(ticker: str, start: int) -> dict:
    params = urllib.parse.urlencode({
        'start': start, 'limit': PAGE_LIMIT, 'iss.meta': 'off',
    })
    url = f'{ISS_URL.format(ticker=ticker)}?{params}'
    req = urllib.request.Request(url, headers={'User-Agent': 'data-core/1.0'})
    last_err: Exception | None = None
    for _ in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as r:
                return json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(RETRY_PAUSE_SEC)
    raise RuntimeError(f'ISS unreachable for {ticker} (start={start}): {last_err}')


def fetch_history(ticker: str) -> tuple[list[list], str]:
    """Скачивает всю историю индекса. Возвращает (rows, shortname).

    rows — список [TRADEDATE, OPEN, HIGH, LOW, CLOSE, VALUE] в порядке возрастания дат.
    shortname — короткое имя индекса из ISS (для имени файла).
    """
    rows: list[list] = []
    shortname = ticker
    start = 0
    while True:
        payload = _fetch_page(ticker, start)
        block = payload.get('history', {})
        cols = block.get('columns', [])
        data = block.get('data', [])
        if not data:
            break
        if 'SHORTNAME' in cols:
            name_idx = cols.index('SHORTNAME')
            short = data[0][name_idx]
            if short:
                shortname = short
        try:
            field_idx = {f: cols.index(f) for f in ISS_FIELDS}
        except ValueError as e:
            raise RuntimeError(
                f'{ticker}: ISS вернул колонки без ожидаемого поля: {e}'
            ) from e
        for r in data:
            rows.append([r[field_idx[f]] for f in ISS_FIELDS])
        start += PAGE_LIMIT
        time.sleep(0.1)  # вежливость к ISS
    rows.sort(key=lambda r: r[0])
    return rows, shortname


def _safe_filename_part(s: str) -> str:
    """Превращает SHORTNAME в часть имени файла: пробелы → _, отбрасываем
    только символы, ломающие Windows-имена. Кириллицу оставляем — её
    `_parse_ticker_and_name` корректно обрабатывает."""
    s = s.replace(' ', '_')
    bad = '<>:"/\\|?*'
    return ''.join(c for c in s if c not in bad)


def _format_value(v) -> str:
    if v is None:
        return '0'
    return str(v)


def _remove_old_copies(ticker: str, keep: str) -> None:
    """Удаляет файлы того же тикера с другим именем (например, если у ISS
    изменился SHORTNAME, прежний файл стал устаревшим)."""
    for old in glob.glob(str(STOCKS_DIR / f'{ticker}*_1day.txt')):
        if os.path.basename(old) == keep:
            continue
        prefix = os.path.basename(old)[:-len('_1day.txt')]
        first_ascii = prefix.split('_', 1)[0]
        if first_ascii == ticker:
            os.remove(old)


def write_finam(ticker: str, shortname: str, rows: list[list]) -> Path:
    if not rows:
        raise ValueError(f'{ticker}: пустая история')
    name_part = _safe_filename_part(shortname) or ticker
    filename = f'{ticker}_{name_part}_1day.txt'
    path = STOCKS_DIR / filename
    _remove_old_copies(ticker, keep=filename)
    with path.open('w', encoding='utf-8') as fh:
        fh.write(FINAM_HEADER + '\n')
        for r in rows:
            tradedate, o, h, l, c, value = r
            line = ';'.join([
                ticker, 'D', tradedate.replace('-', ''), '000000',
                _format_value(o), _format_value(h), _format_value(l), _format_value(c),
                _format_value(value), '0',
            ])
            fh.write(line + '\n')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Скачивает исторические значения индексов Мосбиржи через ISS API.',
    )
    parser.add_argument(
        'tickers', nargs='*', default=DEFAULT_INDICES,
        help=f'Список тикеров. По умолчанию: {" ".join(DEFAULT_INDICES)}',
    )
    args = parser.parse_args()
    STOCKS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for ticker in args.tickers:
        print(f'fetching {ticker} ...', flush=True)
        try:
            rows, shortname = fetch_history(ticker)
        except Exception as e:
            print(f'  {ticker}: ошибка — {e}', file=sys.stderr)
            failures.append(ticker)
            continue
        if not rows:
            print(f'  {ticker}: пустой ответ — пропускаем')
            failures.append(ticker)
            continue
        path = write_finam(ticker, shortname, rows)
        print(f'  {ticker}: {len(rows)} строк, {rows[0][0]} … {rows[-1][0]} -> {path.name}')
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
