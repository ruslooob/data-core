"""Лоадер: котировки акций и индексов Мосбиржи.

Стадии:
- `fetch_stocks()` — инкрементально пополняет файлы акций через ISS
  ручку `/iss/history/engines/stock/markets/shares/securities/{ticker}`.
  Алгоритм: `last_date` из stock_candles → запрос с overlap=7 дней →
  sanity → overlap-check (значения из БД должны совпадать с тем, что
  ISS отдаёт сейчас, допуск 0.5%) → перезапись единого
  `data/stocks/<TICKER>_<имя>_1day.txt` (Finam-формат). НЕ заменяет
  Finam-выгрузки, а **дополняет** их.
- `fetch_indices()` — полностью перезаписывает файлы индексов через
  ISS ручку `/iss/history/engines/stock/markets/index/securities/{ticker}`.
  Дефолтный список: RGBITR, RGBI, MCFTR, RTSI. Пишет в тот же
  Finam-формат, чтобы `load()` подхватил их единым glob'ом.
- `fetch()` — wrapper: вызывает `fetch_stocks()` и `fetch_indices()`
  подряд.
- `load(pg)` — общая заливка для всего, что лежит в
  `data/stocks/*.txt`: метаданные тикеров в `stocks` + свечи в
  `stock_candles` с нормализацией по сплитам из `events`. Нормализация
  читает сплиты обратно из БД, поэтому `stock_splits.load(pg)` должен
  выполниться **до** этого.

См. docs/SPEC_LOADERS.md.
"""
from __future__ import annotations

import glob as glob_mod
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from glob import glob
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[2]
STOCKS_DIR = ROOT / 'data' / 'stocks'

FINAM_HEADER = (
    '<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>'
)
CANDLE_COLS_RAW = ['<TICKER>', '<PER>', '<DATE>', '<TIME>',
                   '<OPEN>', '<HIGH>', '<LOW>', '<CLOSE>',
                   '<VOL>', '<OPENINT>']

ISS_STOCKS_URL = (
    'https://iss.moex.com/iss/history/engines/stock/markets/shares/'
    'securities/{ticker}.json'
)
ISS_INDEX_URL = (
    'https://iss.moex.com/iss/history/engines/stock/markets/index/'
    'securities/{ticker}.json'
)
ISS_STOCK_FIELDS = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE',
                    'VOLUME', 'NUMTRADES', 'SHORTNAME')
ISS_INDEX_FIELDS = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VALUE')

PAGE_LIMIT = 100
REQUEST_TIMEOUT_SEC = 30
RETRY_PAUSE_SEC = 2
MAX_RETRIES = 3

# Sanity-границы для акций (см. SPEC_LOADERS.md). Индексы не проверяем —
# у них шире диапазон по природе.
PRICE_MIN = 1e-4
PRICE_MAX = 1e7

OVERLAP_POINTS = 7
OVERLAP_TOLERANCE_PCT = 0.005

DEFAULT_INDICES = ['RGBITR', 'RGBI', 'MCFTR', 'RTSI']

# Тикеры, которые НЕ являются акциями и которые fetch_stocks() пропускает.
NON_STOCK_TICKERS = {
    'IMOEX', 'RGBITR', 'RGBI', 'MCFTR', 'RTSI',
    'GOLDCB', 'GOLDVIM', 'SILV', 'TGLD',
    'SBGB', 'SBGB_ETF',
    'SAVINGS_MIACR',
    'MIBID_1D', 'MIBOR_1D', 'MIACR_1D',
}


class SanityError(Exception):
    pass


class OverlapError(Exception):
    pass


# ── общие хелперы HTTP/файлов ─────────────────────────────────────────────

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


def _safe_filename_part(s: str) -> str:
    s = s.replace(' ', '_')
    bad = '<>:"/\\|?*'
    return ''.join(c for c in s if c not in bad)


def _iso_to_date(iso8: str) -> date:
    return date.fromisoformat(f'{iso8[:4]}-{iso8[4:6]}-{iso8[6:]}')


# ── fetch: акции (инкрементальный режим с overlap-check) ──────────────────

def _fetch_iss_shares(ticker: str, from_date: date | None) -> tuple[list[dict], str | None]:
    rows: list[dict] = []
    shortname: str | None = None
    start = 0
    params_base = {'iss.meta': 'off'}
    if from_date is not None:
        params_base['from'] = from_date.isoformat()
    while True:
        params = {**params_base, 'start': start, 'limit': PAGE_LIMIT}
        payload = _request(ISS_STOCKS_URL.format(ticker=ticker), params)
        block = payload.get('history', {})
        cols = block.get('columns', [])
        data = block.get('data', [])
        if not data:
            break
        try:
            idx = {f: cols.index(f) for f in ISS_STOCK_FIELDS}
        except ValueError as e:
            raise RuntimeError(f'{ticker}: ISS вернул колонки без поля: {e}') from e
        for r in data:
            rows.append({f: r[idx[f]] for f in ISS_STOCK_FIELDS})
        if shortname is None and data[0][idx['SHORTNAME']]:
            shortname = data[0][idx['SHORTNAME']]
        start += PAGE_LIMIT
        time.sleep(0.1)
    return rows, shortname


def _dedupe_by_max_numtrades(rows: list[dict]) -> list[dict]:
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r['TRADEDATE']
        existing = by_date.get(d)
        if existing is None or (r['NUMTRADES'] or 0) > (existing['NUMTRADES'] or 0):
            by_date[d] = r
    return [by_date[d] for d in sorted(by_date)]


def _sanity_check_stocks(rows: list[dict], ticker: str) -> None:
    today = date.today()
    seen_dates: set[str] = set()
    for r in rows:
        d_str = r['TRADEDATE']
        if d_str in seen_dates:
            raise SanityError(f'{ticker}: дубль даты {d_str}')
        seen_dates.add(d_str)
        d = date.fromisoformat(d_str)
        if d > today:
            raise SanityError(f'{ticker}: дата в будущем: {d_str}')
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


def _overlap_check(rows: list[dict], db_overlap: list[tuple], ticker: str) -> None:
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
        next(fh, None)
        for line in fh:
            parts = line.rstrip('\n').split(';')
            if len(parts) < 10:
                continue
            by_date[parts[2]] = parts
    return by_date


def _write_stock_ticker_file(ticker: str, rows: list[dict],
                             shortname: str | None = None) -> tuple[Path, int]:
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
        name_part = _safe_filename_part(shortname) if shortname else ''
        prefix = f'{ticker}_{name_part}' if name_part else ticker

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


def _fetch_last_date(con, ticker: str) -> date | None:
    row = con.execute(
        'SELECT MAX(candle_date) FROM stock_candles WHERE ticker = %s',
        [ticker],
    ).fetchone()
    return row[0] if row else None


def _fetch_overlap_from_db(con, ticker: str) -> list[tuple]:
    rows = con.execute(
        'SELECT candle_date, open, close FROM stock_candles '
        'WHERE ticker = %s ORDER BY candle_date DESC LIMIT %s',
        [ticker, OVERLAP_POINTS],
    ).fetchall()
    return list(reversed(rows))


def _list_existing_stock_tickers(con) -> list[str]:
    rows = con.execute('SELECT ticker FROM stocks ORDER BY ticker').fetchall()
    return [r[0] for r in rows if r[0] not in NON_STOCK_TICKERS]


def _update_stock_ticker(con, ticker: str) -> None:
    existing_path = _find_ticker_file(ticker)
    existing_rows = _read_ticker_file(existing_path) if existing_path else {}
    last_db_date = _fetch_last_date(con, ticker)

    if not existing_rows:
        from_date = None
        print(f'  {ticker}: initial ISS load (нет файла, без from)')
    else:
        sorted_iso = sorted(existing_rows)
        idx_overlap = max(0, len(sorted_iso) - OVERLAP_POINTS)
        from_date = _iso_to_date(sorted_iso[idx_overlap])
        last_file_date = _iso_to_date(sorted_iso[-1])
        print(
            f'  {ticker}: incremental ISS load от {from_date} '
            f'(в файле {len(existing_rows)} строк до {last_file_date})'
        )

    rows, shortname = _fetch_iss_shares(ticker, from_date)
    if not rows:
        print(f'  {ticker}: ISS не отдал ни одной строки — пропуск')
        return
    rows = _dedupe_by_max_numtrades(rows)
    _sanity_check_stocks(rows, ticker)
    if last_db_date is not None:
        db_overlap = _fetch_overlap_from_db(con, ticker)
        _overlap_check(rows, db_overlap, ticker)

    path, total_in_file = _write_stock_ticker_file(ticker, rows, shortname=shortname)
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


def fetch_stocks(tickers: list[str] | None = None) -> None:
    """Инкрементально обновляет котировки акций. По умолчанию — все
    тикеры из stocks, кроме индексов/ETF/синтетики.

    Частичные сбои (отдельные тикеры — делистинг, недоступность ISS-карточки)
    логируются как WARNING и не останавливают прогон. Это позволяет
    оркестратору продолжить с другими источниками; «застрявшие» тикеры
    видны в выводе и разбираются вручную.
    """
    import psycopg

    pg_dsn = os.environ.get(
        'DATA_CORE_PG_DSN',
        'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres',
    )
    with psycopg.connect(pg_dsn, autocommit=True) as con:
        target = tickers if tickers else _list_existing_stock_tickers(con)
        print(f'будем обновлять {len(target)} тикеров (акции)')
        failures: list[str] = []
        for ticker in target:
            try:
                _update_stock_ticker(con, ticker)
            except (SanityError, OverlapError, RuntimeError) as e:
                failures.append(ticker)
                print(f'  {ticker}: пропущен — {e}', file=sys.stderr)
        if failures:
            print(f'\nWARNING: {len(failures)} тикеров пропущено: {failures}',
                  file=sys.stderr)


# ── fetch: индексы (полная перезапись истории) ────────────────────────────

def _fetch_index_page(ticker: str, start: int) -> dict:
    params = {'start': start, 'limit': PAGE_LIMIT, 'iss.meta': 'off'}
    return _request(ISS_INDEX_URL.format(ticker=ticker), params)


def _fetch_index_history(ticker: str) -> tuple[list[list], str]:
    rows: list[list] = []
    shortname = ticker
    start = 0
    while True:
        payload = _fetch_index_page(ticker, start)
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
            field_idx = {f: cols.index(f) for f in ISS_INDEX_FIELDS}
        except ValueError as e:
            raise RuntimeError(
                f'{ticker}: ISS вернул колонки без ожидаемого поля: {e}'
            ) from e
        for r in data:
            rows.append([r[field_idx[f]] for f in ISS_INDEX_FIELDS])
        start += PAGE_LIMIT
        time.sleep(0.1)
    rows.sort(key=lambda r: r[0])
    return rows, shortname


def _remove_old_copies(ticker: str, keep: str) -> None:
    for old in glob_mod.glob(str(STOCKS_DIR / f'{ticker}*_1day.txt')):
        if os.path.basename(old) == keep:
            continue
        prefix = os.path.basename(old)[:-len('_1day.txt')]
        first_ascii = prefix.split('_', 1)[0]
        if first_ascii == ticker:
            os.remove(old)


def _write_index_finam(ticker: str, shortname: str, rows: list[list]) -> Path:
    if not rows:
        raise ValueError(f'{ticker}: пустая история')

    def _fmt(v) -> str:
        return '0' if v is None else str(v)

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
                _fmt(o), _fmt(h), _fmt(l), _fmt(c),
                _fmt(value), '0',
            ])
            fh.write(line + '\n')
    return path


def fetch_indices(tickers: list[str] | None = None) -> None:
    """Полная перезапись истории индексов. По умолчанию — список
    DEFAULT_INDICES."""
    target = tickers if tickers else DEFAULT_INDICES
    STOCKS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for ticker in target:
        print(f'fetching {ticker} (index) ...', flush=True)
        try:
            rows, shortname = _fetch_index_history(ticker)
        except Exception as e:
            print(f'  {ticker}: ошибка — {e}', file=sys.stderr)
            failures.append(ticker)
            continue
        if not rows:
            print(f'  {ticker}: пустой ответ — пропускаем')
            failures.append(ticker)
            continue
        path = _write_index_finam(ticker, shortname, rows)
        print(f'  {ticker}: {len(rows)} строк, {rows[0][0]} … {rows[-1][0]} -> {path.name}')
    if failures:
        raise RuntimeError(f'{len(failures)} индексов завершились ошибкой: {failures}')


def fetch() -> None:
    """Объединяющий wrapper: акции + индексы."""
    print('== fetch: акции (incremental ISS) ==')
    fetch_stocks()
    print('== fetch: индексы (full history ISS) ==')
    fetch_indices()


# ── load: общая заливка всего, что лежит в data/stocks/*.txt ──────────────

def _parse_ticker_and_name(filename: str, file_path: str) -> tuple[str, str]:
    with open(file_path, 'r', encoding='utf-8') as fh:
        fh.readline()
        first = fh.readline()
    ticker_from_data = first.split(';', 1)[0].strip().upper()
    base = os.path.splitext(filename)[0]

    # Канонический формат имени: <prefix>_1day.txt.
    # Файлы без `_1day` — это тестовые фикстуры (TEST.txt и т.п.),
    # из них берём тикер из данных, name пустой.
    if base.endswith('_1day'):
        prefix = base[:-len('_1day')]
    else:
        return ticker_from_data, ''

    parts = prefix.split('_')
    ascii_parts: list[str] = []
    for part in parts:
        if part.isascii() and part:
            ascii_parts.append(part)
        else:
            break
    ticker_from_filename = '_'.join(ascii_parts)
    if prefix.upper().startswith(ticker_from_data + '_') or prefix.upper() == ticker_from_data:
        ticker = ticker_from_data
    else:
        ticker = ticker_from_filename or ticker_from_data
    if prefix.upper().startswith(ticker.upper() + '_'):
        name = prefix[len(ticker) + 1:]
    elif prefix.upper() == ticker.upper():
        name = ''
    else:
        name = prefix
    return ticker, name


def _fetch_splits_from_events(pg, ticker: str) -> list[dict]:
    """Сплиты тикера из таблицы `events` — нужны для нормализации цен."""
    with pg.cursor() as cur:
        cur.execute(
            "SELECT e.event_date, (e.payload->>'ratio')::float "
            "FROM events e "
            "JOIN event_tags et ON et.event_id = e.id "
            "WHERE et.tag_code = 'STOCK_SPLIT' "
            "  AND e.payload->>'ticker' = %s "
            "ORDER BY e.event_date",
            [ticker.upper()],
        )
        rows = cur.fetchall()
    return [{'split_date': d.isoformat(), 'ratio': float(r)} for d, r in rows]


def _load_normalized_candles(path: str, splits: list[dict]) -> pd.DataFrame:
    df = pd.read_csv(path, sep=';', dtype=str)
    if list(df.columns) != CANDLE_COLS_RAW:
        raise ValueError(f'неожиданные столбцы в {path}: {list(df.columns)}')
    df = df.rename(columns={
        '<DATE>': 'date_str',
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<VOL>': 'volume', '<OPENINT>': 'open_interest',
    })
    df['candle_date'] = pd.to_datetime(df['date_str'], format='%Y%m%d')
    for col in ['open', 'high', 'low', 'close', 'volume', 'open_interest']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if splits:
        adj = pd.Series(1.0, index=df.index)
        for ev in sorted(splits, key=lambda e: e['split_date']):
            split_ts = pd.to_datetime(ev['split_date'])
            ratio = float(ev['ratio'])
            adj.loc[df['candle_date'] < split_ts] *= ratio
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col] / adj
        df['volume'] = df['volume'] * adj
    df['candle_date'] = df['candle_date'].dt.date
    return df[['candle_date', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]


def load_metadata(pg) -> None:
    """Метаданные тикеров из имён файлов в `data/stocks/*.txt` → таблица `stocks`.

    Идёт **до** обогащения эмитентами (moex_securities) и до сплитов:
    создаёт записи stocks, которые остальные шаги дополняют.
    """
    files = sorted(glob(os.path.join(str(STOCKS_DIR), '*.txt')))
    with pg.cursor() as cur:
        for path in files:
            filename = os.path.basename(path)
            ticker, name = _parse_ticker_and_name(filename, path)
            cur.execute(
                'INSERT INTO stocks (ticker, name) VALUES (%s, %s) '
                'ON CONFLICT (ticker) DO NOTHING',
                [ticker, name],
            )
    print(f'  stocks: {len(files)} files processed')


def load_candles(pg) -> None:
    """INSERT свечей с нормализацией по сплитам, прочитанным из `events`.

    Запускается после загрузки сплитов — иначе нормализация будет
    пустой и цены до даты сплита получатся в исходном масштабе.
    """
    files = sorted(glob(os.path.join(str(STOCKS_DIR), '*.txt')))
    total_new = 0
    with pg.cursor() as cur:
        for path in files:
            filename = os.path.basename(path)
            ticker, name = _parse_ticker_and_name(filename, path)
            ticker_splits = _fetch_splits_from_events(pg, ticker)
            cur.execute(
                'SELECT MAX(candle_date) FROM stock_candles WHERE ticker = %s',
                [ticker],
            )
            last_date_row = cur.fetchone()
            last_date = last_date_row[0] if last_date_row else None

            df = _load_normalized_candles(path, ticker_splits)
            # В БД уже есть всё до last_date включительно — отправляем только дельту.
            if last_date is not None:
                df_new = df[df['candle_date'] > last_date]
            else:
                df_new = df
            rows = [
                (ticker, r.candle_date, r.open, r.high, r.low, r.close,
                 r.volume, r.open_interest)
                for r in df_new.itertuples(index=False)
            ]
            if rows:
                cur.executemany(
                    'INSERT INTO stock_candles '
                    '(ticker, candle_date, open, high, low, close, volume, open_interest) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) '
                    'ON CONFLICT (ticker, candle_date) DO NOTHING',
                    rows,
                )
            total_new += len(rows)
            print(
                f'  {ticker:14s} {len(rows):6d} new candles '
                f'(in file: {len(df)}, in DB up to: {last_date}, splits: {len(ticker_splits)}) ({name})'
            )
    print(f'  total new candles inserted: {total_new}')


def load(pg) -> None:
    """Удобный wrapper для прямого запуска модуля: метаданные + свечи
    одним вызовом. В оркестраторе `load_all_data.py` стадии разнесены —
    между ними должны выполниться `moex_securities.load` и
    `stock_splits.load`.
    """
    print('-- metadata --')
    load_metadata(pg)
    print('-- candles --')
    load_candles(pg)


# ── direct run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-stocks', action='store_true',
                        help='только fetch акций (incremental)')
    parser.add_argument('--fetch-indices', action='store_true',
                        help='только fetch индексов (full history)')
    parser.add_argument('--fetch', action='store_true',
                        help='fetch акций + индексов')
    parser.add_argument('--load', action='store_true', help='только load в БД')
    args = parser.parse_args()

    any_fetch = args.fetch or args.fetch_stocks or args.fetch_indices
    do_load = args.load or not any_fetch

    if args.fetch:
        fetch()
    else:
        if args.fetch_stocks:
            fetch_stocks()
        if args.fetch_indices:
            fetch_indices()

    if do_load:
        pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
        with psycopg.connect(pg_dsn) as pg:
            load(pg)
            pg.commit()
