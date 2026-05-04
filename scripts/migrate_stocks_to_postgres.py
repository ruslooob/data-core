"""Загрузка котировок и безрисковой ставки в Postgres.

Источники:
- `data/stocks/<TICKER>_<Name>_1day_*.txt` — OHLCV-файлы (включая IMOEX);
  формат `<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>`.
- `data/stocks/splits.json` — карта ticker → list of splits.
- `data/stocks/RUONIA_*.xlsx` — RUONIA (% годовых).

Создаёт три таблицы в Postgres:
- `stocks(ticker, name, splits)` — реестр тикеров с краткой справкой и
  списком сплитов (для archival/инспекции).
- `stock_candles(ticker, candle_date, open, high, low, close, volume,
  open_interest)` — котировки **уже нормализованные** по сплитам.
  Логика нормализации идентична `_load_normalized_candles` из
  StockDataProvider: накопительный ADJ_FACTOR от поздних сплитов к
  ранним; OHLC делится, VOL умножается. Это позволяет UDF в Postgres
  читать чистые значения без лишней логики.
- `risk_free_rate(rate_date, annual_rate_pct)` — RUONIA в % годовых.

Идемпотентен: дропает таблицы и перезаливает данные. Запуск:
    python scripts/migrate_stocks_to_postgres.py
"""
from __future__ import annotations

import json
import os
import sys
from glob import glob

import pandas as pd
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS_DIR = os.path.join(ROOT, 'data', 'stocks')
SPLITS_PATH = os.path.join(STOCKS_DIR, 'splits.json')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'


DDL_STOCKS = """
    CREATE TABLE stocks (
        ticker  VARCHAR PRIMARY KEY,
        name    VARCHAR,
        splits  JSONB
    )
"""

DDL_STOCK_CANDLES = """
    CREATE TABLE stock_candles (
        ticker        VARCHAR NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE,
        candle_date   DATE    NOT NULL,
        open          DOUBLE PRECISION,
        high          DOUBLE PRECISION,
        low           DOUBLE PRECISION,
        close         DOUBLE PRECISION,
        volume        DOUBLE PRECISION,
        open_interest DOUBLE PRECISION,
        PRIMARY KEY (ticker, candle_date)
    )
"""

DDL_RISK_FREE_RATE = """
    CREATE TABLE risk_free_rate (
        rate_date        DATE PRIMARY KEY,
        annual_rate_pct  DOUBLE PRECISION NOT NULL
    )
"""

DDL_DIVIDENDS = """
    CREATE TABLE dividends (
        ticker              VARCHAR NOT NULL,
        announcement_date   DATE    NOT NULL,
        payment_date        DATE,
        dividend_per_share  DOUBLE PRECISION NOT NULL,
        year                INTEGER NOT NULL,
        PRIMARY KEY (ticker, announcement_date, year)
    )
"""

CANDLE_COLS_RAW = ['<TICKER>', '<PER>', '<DATE>', '<TIME>',
                   '<OPEN>', '<HIGH>', '<LOW>', '<CLOSE>',
                   '<VOL>', '<OPENINT>']


def _drop_all(pg) -> None:
    with pg.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS stock_candles CASCADE')
        cur.execute('DROP TABLE IF EXISTS stocks CASCADE')
        cur.execute('DROP TABLE IF EXISTS risk_free_rate CASCADE')
        cur.execute('DROP TABLE IF EXISTS dividends CASCADE')


def _create_schema(pg) -> None:
    with pg.cursor() as cur:
        cur.execute(DDL_STOCKS)
        cur.execute(DDL_STOCK_CANDLES)
        cur.execute(DDL_RISK_FREE_RATE)
        cur.execute(DDL_DIVIDENDS)


def _parse_filename(filename: str) -> tuple[str, str]:
    """Из `LKOH_Лукойл_1day_*.txt` → ('LKOH', 'Лукойл').
    Имя содержит уникод; читаем filename как есть."""
    base = os.path.splitext(filename)[0]
    parts = base.split('_')
    if len(parts) < 2:
        return parts[0].upper(), ''
    return parts[0].upper(), parts[1]


def _load_candles_df(path: str, splits: list[dict]) -> pd.DataFrame:
    """Загружает котировки и нормализует их по списку сплитов.

    Алгоритм идентичен `_load_normalized_candles` в StockDataProvider:
    для каждой строки накопительно умножаем ADJ_FACTOR на ratio тех
    сплитов, чья дата позже даты строки; затем OHLC = OHLC / ADJ_FACTOR,
    VOL = VOL * ADJ_FACTOR.
    """
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


def _load_splits() -> dict[str, list]:
    if not os.path.exists(SPLITS_PATH):
        return {}
    with open(SPLITS_PATH, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _migrate_stocks_and_candles(pg) -> int:
    splits = _load_splits()
    files = sorted(glob(os.path.join(STOCKS_DIR, '*.txt')))
    inserted_candles = 0
    with pg.cursor() as cur:
        for path in files:
            filename = os.path.basename(path)
            ticker, name = _parse_filename(filename)
            ticker_splits = splits.get(ticker, [])
            cur.execute(
                'INSERT INTO stocks (ticker, name, splits) VALUES (%s, %s, %s) '
                'ON CONFLICT (ticker) DO NOTHING',
                [ticker, name, json.dumps(ticker_splits)],
            )
            df = _load_candles_df(path, ticker_splits)
            rows = [
                (ticker, r.candle_date, r.open, r.high, r.low, r.close,
                 r.volume, r.open_interest)
                for r in df.itertuples(index=False)
            ]
            cur.executemany(
                """
                INSERT INTO stock_candles
                  (ticker, candle_date, open, high, low, close, volume, open_interest)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, candle_date) DO NOTHING
                """,
                rows,
            )
            inserted_candles += len(rows)
            print(f'  {ticker:12s} {len(rows):6d} candles  ({name})')
    return inserted_candles


def _migrate_ruonia(pg) -> int:
    xlsx_files = glob(os.path.join(STOCKS_DIR, 'RUONIA_*.xlsx'))
    if not xlsx_files:
        print('  нет файла RUONIA_*.xlsx, пропускаем безрисковую ставку')
        return 0
    if len(xlsx_files) > 1:
        print(f'  предупреждение: найдено {len(xlsx_files)} RUONIA-файлов, беру первый: {xlsx_files[0]}')
    df = pd.read_excel(xlsx_files[0], sheet_name='RC', usecols=['DT', 'ruo'])
    df['DT'] = pd.to_datetime(df['DT']).dt.date
    df['ruo'] = pd.to_numeric(df['ruo'], errors='coerce')
    df = df.dropna(subset=['ruo']).sort_values('DT')
    rows = [(r.DT, float(r.ruo)) for r in df.itertuples(index=False)]
    with pg.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO risk_free_rate (rate_date, annual_rate_pct)
            VALUES (%s, %s) ON CONFLICT (rate_date) DO NOTHING
            """,
            rows,
        )
    return len(rows)


def _migrate_dividends(pg) -> int:
    csv_path = os.path.join(STOCKS_DIR, 'dividends_all.csv')
    if not os.path.exists(csv_path):
        print(f'  нет файла {csv_path}, пропускаем')
        return 0
    df = pd.read_csv(csv_path, dtype={'ticker': str, 'year': str})
    df['announcement_date'] = pd.to_datetime(df['announcement_date'], dayfirst=True).dt.date
    df['payment_date'] = pd.to_datetime(df['payment_date'], dayfirst=True, errors='coerce').dt.date
    rows = []
    for _, r in df.iterrows():
        if pd.isna(r['ticker']) or not r['ticker']:
            continue
        try:
            div = float(r['dividend_per_share'])
        except (TypeError, ValueError):
            continue
        try:
            year = int(r['year'])
        except (TypeError, ValueError):
            continue
        rows.append((
            str(r['ticker']).upper(),
            r['announcement_date'],
            r['payment_date'] if pd.notna(r['payment_date']) else None,
            div,
            year,
        ))
    with pg.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dividends
              (ticker, announcement_date, payment_date, dividend_per_share, year)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ticker, announcement_date, year) DO NOTHING
            """,
            rows,
        )
    return len(rows)


def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=False)
    try:
        print('drop tables')
        _drop_all(pg)
        pg.commit()

        print('create schema')
        _create_schema(pg)
        pg.commit()

        print('migrate stocks + candles:')
        n_candles = _migrate_stocks_and_candles(pg)
        pg.commit()
        print(f'total candles inserted: {n_candles}')

        print('migrate RUONIA:')
        n_rates = _migrate_ruonia(pg)
        pg.commit()
        print(f'risk_free_rate rows: {n_rates}')

        print('migrate dividends:')
        n_div = _migrate_dividends(pg)
        pg.commit()
        print(f'dividends rows: {n_div}')

        with pg.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM stocks')
            print(f'stocks rows: {cur.fetchone()[0]}')
            cur.execute('SELECT COUNT(*) FROM stock_candles')
            print(f'stock_candles rows: {cur.fetchone()[0]}')
            cur.execute('SELECT COUNT(*) FROM risk_free_rate')
            print(f'risk_free_rate rows: {cur.fetchone()[0]}')
            cur.execute('SELECT COUNT(*) FROM dividends')
            print(f'dividends rows: {cur.fetchone()[0]}')
    finally:
        pg.close()


if __name__ == '__main__':
    if not os.path.exists(STOCKS_DIR):
        print(f'stocks dir не найден: {STOCKS_DIR}', file=sys.stderr)
        sys.exit(1)
    main()
