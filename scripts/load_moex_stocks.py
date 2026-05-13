"""Инкрементальное обновление котировок акций через ISS API.

Пополняет существующие данные новыми днями из ISS Мосбиржи. Не заменяет
Finam-файлы — у ISS часто нет данных до 2013 года, и старая история
живёт только в Finam-выгрузках.

Алгоритм для каждого тикера:

1. `last_date = SELECT MAX(candle_date) FROM stock_candles WHERE ticker = X`.
2. Если NULL — initial load (новый тикер, IPO).
3. Иначе — overlap-load: запрашиваем 7 последних торговых дней БД
   + всё, что после, до сегодня.
4. Дедупликация по дате (берём строку с максимальным NUMTRADES, что
   соответствует главному режиму торгов для конкретной даты).
5. Sanity-проверки.
6. Overlap-проверка: 7 точек, которые уже есть в БД, должны
   совпадать с тем, что отдаёт ISS сейчас.
7. Запись в `data/stocks/<TICKER>_<имя>_1day.txt` — единый накопленный
   файл по тикеру. Имя стабильное, диапазон дат в имени не фигурирует.

См. docs/SPEC_LOADERS.md.
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
from datetime import date
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = REPO_ROOT / 'data' / 'stocks'

# В корне проекта импорт core.postgres_db не доступен из scripts/,
# поэтому DSN захардкожен здесь (так же, как в core/postgres_db.py).
PG_DSN = os.environ.get(
    'DATA_CORE_PG_DSN',
    'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres',
)

ISS_URL = (
    'https://iss.moex.com/iss/history/engines/stock/markets/shares/'
    'securities/{ticker}.json'
)

# Тикеры, которые НЕ являются акциями и которые этот загрузчик не трогает.
NON_STOCK_TICKERS = {
    # Индексы
    'IMOEX', 'RGBITR', 'RGBI', 'MCFTR', 'RTSI',
    # Драгметаллы и их прокси
    'GOLDCB', 'GOLDVIM', 'SILV', 'TGLD',
    # Облигационные ETF
    'SBGB', 'SBGB_ETF',
    # Синтетика
    'SAVINGS_MIACR',
    # Overnight-ставки
    'MIBID_1D', 'MIBOR_1D', 'MIACR_1D',
}

FINAM_HEADER = (
    '<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>'
)

ISS_FIELDS = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'NUMTRADES')

PAGE_LIMIT = 100
REQUEST_TIMEOUT_SEC = 30
RETRY_PAUSE_SEC = 2
MAX_RETRIES = 3

# Sanity-границы для акций (см. SPEC_LOADERS.md).
PRICE_MIN = 1e-4
PRICE_MAX = 1e7

OVERLAP_POINTS = 7
OVERLAP_TOLERANCE_PCT = 0.005  # 0.5% — допуск для overlap-проверки


class SanityError(Exception):
    pass


class OverlapError(Exception):
    pass


def _request(url: str, params: dict) -> dict:
    full = f'{url}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(full, headers={'User-Agent': 'data-core/1.0'})
    last_err: Exception | None = None
    for _ in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as r:
                return json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(RETRY_PAUSE_SEC)
    raise RuntimeError(f'ISS unreachable: {last_err}')


def fetch_iss_shares(ticker: str, from_date: date | None) -> list[dict]:
    """Скачивает котировки акции из ISS. Возвращает список словарей по
    нужным полям."""
    rows: list[dict] = []
    start = 0
    params_base = {'iss.meta': 'off'}
    if from_date is not None:
        params_base['from'] = from_date.isoformat()
    while True:
        params = {**params_base, 'start': start, 'limit': PAGE_LIMIT}
        payload = _request(ISS_URL.format(ticker=ticker), params)
        block = payload.get('history', {})
        cols = block.get('columns', [])
        data = block.get('data', [])
        if not data:
            break
        try:
            idx = {f: cols.index(f) for f in ISS_FIELDS}
        except ValueError as e:
            raise RuntimeError(f'{ticker}: ISS вернул колонки без поля: {e}') from e
        for r in data:
            rows.append({f: r[idx[f]] for f in ISS_FIELDS})
        start += PAGE_LIMIT
        time.sleep(0.1)
    return rows


def dedupe_by_max_numtrades(rows: list[dict]) -> list[dict]:
    """На каждую дату оставляем строку с максимальным NUMTRADES —
    это соответствует главному режиму торгов для конкретной даты."""
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r['TRADEDATE']
        existing = by_date.get(d)
        if existing is None or (r['NUMTRADES'] or 0) > (existing['NUMTRADES'] or 0):
            by_date[d] = r
    return [by_date[d] for d in sorted(by_date)]


def sanity_check(rows: list[dict], ticker: str, last_date: date | None) -> None:
    today = date.today()
    seen_dates: set[str] = set()
    for r in rows:
        d_str = r['TRADEDATE']
        if d_str in seen_dates:
            raise SanityError(f'{ticker}: дубль даты {d_str}')
        seen_dates.add(d_str)

        # Окно дат
        from datetime import date as _date
        d = _date.fromisoformat(d_str)
        if d > today:
            raise SanityError(f'{ticker}: дата в будущем: {d_str}')

        # Цены
        for fld in ('OPEN', 'HIGH', 'LOW', 'CLOSE'):
            v = r[fld]
            if v is None:
                continue
            if v <= 0:
                raise SanityError(f'{ticker} {d_str}: {fld} ≤ 0: {v}')
            if v < PRICE_MIN or v > PRICE_MAX:
                raise SanityError(
                    f'{ticker} {d_str}: {fld} вне диапазона '
                    f'[{PRICE_MIN}, {PRICE_MAX}]: {v}'
                )
        h, l = r['HIGH'], r['LOW']
        if h is not None and l is not None and h < l:
            raise SanityError(f'{ticker} {d_str}: HIGH < LOW ({h} < {l})')


def overlap_check(rows: list[dict], db_overlap: list[tuple], ticker: str) -> None:
    """Сверяет 7 точек, уже имеющихся в БД, с тем, что отдаёт ISS сейчас.
    db_overlap — список (candle_date, open, close), отсортированный по date ASC."""
    by_date = {r['TRADEDATE']: r for r in rows}
    for d_db, open_db, close_db in db_overlap:
        d_str = d_db.isoformat()
        if d_str not in by_date:
            raise OverlapError(
                f'{ticker}: дата {d_str} есть в БД, но не в ответе ISS'
            )
        r = by_date[d_str]
        for fld_iss, val_db, fld_name in [('OPEN', open_db, 'open'),
                                           ('CLOSE', close_db, 'close')]:
            val_iss = r[fld_iss]
            if val_iss is None or val_db is None:
                continue
            diff = abs(float(val_iss) - float(val_db)) / float(val_db)
            if diff > OVERLAP_TOLERANCE_PCT:
                raise OverlapError(
                    f'{ticker} {d_str}: {fld_name} БД={val_db} '
                    f'ISS={val_iss} (расхождение {diff:.2%})'
                )


def _find_ticker_file(ticker: str) -> Path | None:
    """Находит единственный файл тикера `<TICKER>*_1day.txt` в data/stocks/.
    Первая ASCII-часть имени должна совпадать с ticker. Если ничего нет —
    None (новый тикер)."""
    candidates: list[Path] = []
    for path in STOCKS_DIR.glob(f'{ticker}*_1day.txt'):
        prefix = path.name[:-len('_1day.txt')]
        first_ascii = prefix.split('_', 1)[0]
        if first_ascii == ticker:
            candidates.append(path)
    if not candidates:
        return None
    if len(candidates) > 1:
        raise RuntimeError(
            f'{ticker}: несколько файлов в data/stocks/, ожидался один: '
            f'{[p.name for p in candidates]}'
        )
    return candidates[0]


def _read_ticker_file(path: Path) -> dict[str, list[str]]:
    by_date: dict[str, list[str]] = {}
    with path.open('r', encoding='utf-8') as fh:
        next(fh, None)  # header
        for line in fh:
            parts = line.rstrip('\n').split(';')
            if len(parts) < 10:
                continue
            by_date[parts[2]] = parts
    return by_date


def write_ticker_file(ticker: str, rows: list[dict]) -> tuple[Path, int]:
    """Пополняет единый файл тикера новой дельтой ISS. Имя файла
    стабильное: `<TICKER>_<имя>_1day.txt` (или `<TICKER>_1day.txt` для
    новых тикеров без cyrillic-имени)."""
    if not rows:
        raise ValueError(f'{ticker}: пустая выдача')

    def _fmt(v) -> str:
        return '0' if v is None else str(v)

    existing_path = _find_ticker_file(ticker)
    if existing_path is not None:
        by_date = _read_ticker_file(existing_path)
        prefix = existing_path.name[:-len('_1day.txt')]
    else:
        by_date = {}
        prefix = ticker

    for r in rows:
        iso = r['TRADEDATE'].replace('-', '')
        by_date[iso] = [
            ticker, 'D', iso, '000000',
            _fmt(r['OPEN']), _fmt(r['HIGH']), _fmt(r['LOW']), _fmt(r['CLOSE']),
            _fmt(r['VOLUME']), '0',
        ]

    sorted_dates = sorted(by_date)
    new_filename = f'{prefix}_1day.txt'
    new_path = STOCKS_DIR / new_filename

    with new_path.open('w', encoding='utf-8') as fh:
        fh.write(FINAM_HEADER + '\n')
        for d in sorted_dates:
            fh.write(';'.join(by_date[d]) + '\n')

    if existing_path is not None and existing_path.name != new_filename:
        existing_path.unlink()
    return new_path, len(sorted_dates)


def fetch_last_date(con, ticker: str) -> date | None:
    row = con.execute(
        'SELECT MAX(candle_date) FROM stock_candles WHERE ticker = %s',
        [ticker],
    ).fetchone()
    return row[0] if row else None


def fetch_overlap_from_db(con, ticker: str) -> list[tuple]:
    rows = con.execute(
        'SELECT candle_date, open, close FROM stock_candles '
        'WHERE ticker = %s ORDER BY candle_date DESC LIMIT %s',
        [ticker, OVERLAP_POINTS],
    ).fetchall()
    return list(reversed(rows))  # ASC


def list_existing_stock_tickers(con) -> list[str]:
    rows = con.execute('SELECT ticker FROM stocks ORDER BY ticker').fetchall()
    return [r[0] for r in rows if r[0] not in NON_STOCK_TICKERS]


def _iso_to_date(iso8: str) -> date:
    return date.fromisoformat(f'{iso8[:4]}-{iso8[4:6]}-{iso8[6:]}')


def update_ticker(con, ticker: str) -> None:
    """Единый файл тикера — state всей накопленной истории по тикеру
    (Finam + ISS, после миграции). БД используется только для
    overlap-проверки связности."""
    existing_path = _find_ticker_file(ticker)
    existing_rows = _read_ticker_file(existing_path) if existing_path else {}
    last_db_date = fetch_last_date(con, ticker)

    if not existing_rows:
        from_date = None
        print(f'  {ticker}: initial ISS load (нет файла, без from)')
    else:
        sorted_iso = sorted(existing_rows)
        idx = max(0, len(sorted_iso) - OVERLAP_POINTS)
        from_date = _iso_to_date(sorted_iso[idx])
        last_file_date = _iso_to_date(sorted_iso[-1])
        print(
            f'  {ticker}: incremental ISS load от {from_date} '
            f'(в файле {len(existing_rows)} строк до {last_file_date})'
        )

    rows = fetch_iss_shares(ticker, from_date)
    if not rows:
        print(f'  {ticker}: ISS не отдал ни одной строки — пропуск')
        return

    rows = dedupe_by_max_numtrades(rows)

    try:
        sanity_check(rows, ticker, last_db_date)
    except SanityError as e:
        print(f'  {ticker}: SANITY FAIL — {e}', file=sys.stderr)
        raise

    if last_db_date is not None:
        db_overlap = fetch_overlap_from_db(con, ticker)
        try:
            overlap_check(rows, db_overlap, ticker)
        except OverlapError as e:
            print(f'  {ticker}: OVERLAP FAIL — {e}', file=sys.stderr)
            raise

    path, total_in_file = write_ticker_file(ticker, rows)
    new_dates_vs_db = [
        r['TRADEDATE'] for r in rows
        if last_db_date is None or date.fromisoformat(r['TRADEDATE']) > last_db_date
    ]
    print(
        f'  {ticker}: ISS вернул {len(rows)} строк '
        f'({rows[0]["TRADEDATE"]} … {rows[-1]["TRADEDATE"]}), '
        f'новых дней относительно БД: {len(new_dates_vs_db)}, '
        f'в файле теперь {total_in_file} -> {path.name}'
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Инкрементально обновляет котировки акций через ISS API.',
    )
    parser.add_argument(
        'tickers', nargs='*',
        help='Список тикеров. По умолчанию — все акции из stocks, кроме индексов/ETF/синтетики.',
    )
    args = parser.parse_args()

    with psycopg.connect(PG_DSN, autocommit=True) as con:
        tickers = args.tickers if args.tickers else list_existing_stock_tickers(con)
        print(f'будем обновлять {len(tickers)} тикеров')
        failures: list[str] = []
        for ticker in tickers:
            try:
                update_ticker(con, ticker)
            except (SanityError, OverlapError, RuntimeError) as e:
                failures.append(ticker)
                print(f'  {ticker}: остановлен — {e}', file=sys.stderr)
        if failures:
            print(f'\n{len(failures)} тикеров завершились ошибкой: {failures}',
                  file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
