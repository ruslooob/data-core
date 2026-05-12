"""Идемпотентная загрузка референсных данных в Postgres.

Схема и UDF создаются Liquibase-миграцией (`docker compose --profile migrate
run liquibase update`). Этот скрипт льёт **только данные**:

- `stocks`, `stock_candles` — из `data/stocks/<TICKER>_<NAME>_1day_*.txt`,
  с нормализацией по сплитам (`splits.json`).
- `risk_free_rate` — из `data/stocks/RUONIA_*.xlsx`.
- Накопительный счёт `SAVINGS_MIACR` — капитализованный индекс
  (start=1000) под овернайт-ставку MIACR из `mfd_rates.csv`.
  Покрывает 2000-08-01 .. сегодня, используется как безрисковый
  benchmark и источник R_f для Sharpe.
- Дивиденды — из `data/stocks/dividends_all.csv` напрямую в `events`.
  На каждую строку CSV создаётся два события: «Объявление…» (date_start
  = announce_date = announcement_date) и «Выплата…» (date_start =
  payment_date, announce_date = announcement_date). Специфика
  (ticker, dividend_per_share, year) кладётся в events.payload.

Все INSERT'ы через `ON CONFLICT DO NOTHING` — повторный запуск безопасен.

Пользовательские данные (tags, events, event_tags, precedent_queries,
research, strategies, rules, environments, backtest_results, trade_journal)
НЕ заливаются — восстанавливаются из pg_dump снапшота.

Запуск:
    python scripts/load_data_to_postgres.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from glob import glob

import pandas as pd
import psycopg

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS_DIR = os.path.join(ROOT, 'data', 'stocks')
SPLITS_PATH = os.path.join(STOCKS_DIR, 'splits.json')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

CANDLE_COLS_RAW = ['<TICKER>', '<PER>', '<DATE>', '<TIME>',
                   '<OPEN>', '<HIGH>', '<LOW>', '<CLOSE>',
                   '<VOL>', '<OPENINT>']


# ── Котировки и сплиты ─────────────────────────────────────────────────────

def _load_splits() -> dict[str, list]:
    if not os.path.exists(SPLITS_PATH):
        return {}
    with open(SPLITS_PATH, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _parse_ticker_and_name(filename: str, file_path: str) -> tuple[str, str]:
    with open(file_path, 'r', encoding='utf-8') as fh:
        fh.readline()  # заголовок
        first = fh.readline()
    ticker_from_data = first.split(';', 1)[0].strip().upper()
    base = os.path.splitext(filename)[0]
    if '_1day_' in base:
        prefix = base.split('_1day_', 1)[0]
        # Тикер из имени файла: ведущие ASCII-сегменты до первого кириллического
        parts = prefix.split('_')
        ascii_parts: list[str] = []
        for part in parts:
            if part.isascii() and part:
                ascii_parts.append(part)
            else:
                break
        ticker_from_filename = '_'.join(ascii_parts)
        # CSV-тикер берём только если имя файла его подтверждает (DEPOSIT_RUONIA_RUONIA → DEPOSIT_RUONIA)
        if prefix.upper().startswith(ticker_from_data + '_'):
            ticker = ticker_from_data
        else:
            ticker = ticker_from_filename
        name = prefix[len(ticker) + 1:] if prefix.upper().startswith(ticker + '_') else prefix
    else:
        parts = base.split('_')
        name = parts[1] if len(parts) >= 2 else ''
        ticker = ticker_from_data
    return ticker, name


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


def _load_stocks_and_candles(pg) -> None:
    splits = _load_splits()
    files = sorted(glob(os.path.join(STOCKS_DIR, '*.txt')))
    total = 0
    with pg.cursor() as cur:
        for path in files:
            filename = os.path.basename(path)
            ticker, name = _parse_ticker_and_name(filename, path)
            ticker_splits = splits.get(ticker, [])
            cur.execute(
                'INSERT INTO stocks (ticker, name, splits) VALUES (%s, %s, %s) '
                'ON CONFLICT (ticker) DO NOTHING',
                [ticker, name, json.dumps(ticker_splits)],
            )
            df = _load_normalized_candles(path, ticker_splits)
            rows = [
                (ticker, r.candle_date, r.open, r.high, r.low, r.close,
                 r.volume, r.open_interest)
                for r in df.itertuples(index=False)
            ]
            cur.executemany(
                'INSERT INTO stock_candles '
                '(ticker, candle_date, open, high, low, close, volume, open_interest) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) '
                'ON CONFLICT (ticker, candle_date) DO NOTHING',
                rows,
            )
            total += len(rows)
            print(f'  {ticker:14s} {len(rows):6d} candles  ({name})')
    print(f'  total candles attempted: {total}')


# ── RUONIA ─────────────────────────────────────────────────────────────────

def _load_ruonia(pg) -> None:
    xlsx_files = glob(os.path.join(STOCKS_DIR, 'RUONIA_*.xlsx'))
    if not xlsx_files:
        print('  RUONIA-файл не найден — пропускаем безрисковую ставку')
        return
    df = pd.read_excel(xlsx_files[0], sheet_name='RC', usecols=['DT', 'ruo'])
    df['DT'] = pd.to_datetime(df['DT']).dt.date
    df['ruo'] = pd.to_numeric(df['ruo'], errors='coerce')
    df = df.dropna(subset=['ruo']).sort_values('DT')
    rows = [(r.DT, float(r.ruo)) for r in df.itertuples(index=False)]
    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO risk_free_rate (rate_date, annual_rate_pct) '
            'VALUES (%s, %s) ON CONFLICT (rate_date) DO NOTHING',
            rows,
        )
    print(f'  risk_free_rate: {len(rows)} rows attempted')


# ── Накопительный счёт SAVINGS_MIACR ──────────────────────────────────────

_SAVINGS_TICKER = 'SAVINGS_MIACR'
_SAVINGS_NAME = 'Накопительный счёт MIACR'
_SAVINGS_INITIAL_PRICE = 1000.0
_DAYS_IN_YEAR = 365


def _load_savings_miacr(pg) -> None:
    """Капитализованный индекс под овернайт-ставку MIACR.

    Цена начинается с 1000 и растёт по формуле сложного процента между
    соседними торговыми днями `mfd_rates.csv`: за выходные применяется
    ставка предыдущего рабочего дня за фактическое число календарных
    дней. ACT/365.
    """
    csv_path = os.path.join(STOCKS_DIR, 'mfd_rates.csv')
    if not os.path.exists(csv_path):
        print(f'  {csv_path} не найден — пропускаем SAVINGS_MIACR')
        return
    df = pd.read_csv(csv_path)[['date', 'miacr_1']].dropna()
    if df.empty:
        print(f'  {csv_path}: miacr_1 пуст — пропускаем SAVINGS_MIACR')
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
            'INSERT INTO stocks (ticker, name, splits) '
            'VALUES (%s, %s, %s) ON CONFLICT (ticker) DO NOTHING',
            [_SAVINGS_TICKER, _SAVINGS_NAME, json.dumps([])],
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


# ── Дивиденды ──────────────────────────────────────────────────────────────

# Стабильный namespace для UUID5-идентификаторов событий: один и тот же
# (kind, ticker, date) → один и тот же UUID, ON CONFLICT DO NOTHING на
# повторных запусках.
_DIVIDEND_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000000')


def _make_dividend_event_id(kind: str, ticker: str, date_iso: str) -> str:
    return str(uuid.uuid5(_DIVIDEND_EVENT_NAMESPACE, f'{kind}_{ticker}_{date_iso}'))


def _load_dividends(pg) -> None:
    csv_path = os.path.join(STOCKS_DIR, 'dividends_all.csv')
    if not os.path.exists(csv_path):
        print(f'  {csv_path} не найден — пропускаем дивиденды')
        return
    df = pd.read_csv(csv_path, dtype={'ticker': str, 'year': str})
    df['announcement_date'] = pd.to_datetime(df['announcement_date'], dayfirst=True).dt.date
    df['payment_date'] = pd.to_datetime(df['payment_date'], dayfirst=True, errors='coerce').dt.date
    rows: list[tuple] = []
    for _, r in df.iterrows():
        if pd.isna(r['ticker']) or not r['ticker']:
            continue
        try:
            div = float(r['dividend_per_share'])
            year = int(r['year'])
        except (TypeError, ValueError):
            continue
        ticker = str(r['ticker']).upper()
        announce = r['announcement_date']
        payment = r['payment_date'] if pd.notna(r['payment_date']) else None
        payload = json.dumps({'ticker': ticker, 'dividend_per_share': div, 'year': year})

        announce_iso = announce.isoformat()
        rows.append((
            _make_dividend_event_id('DIVIDEND_ANNOUNCEMENT', ticker, announce_iso),
            announce, announce, None,
            f'Объявление дивидендов {ticker}: {div:.2f} ₽ за {year} год',
            payload,
        ))
        if payment is not None:
            payment_iso = payment.isoformat()
            rows.append((
                _make_dividend_event_id('DIVIDEND_PAYMENT', ticker, payment_iso),
                payment, announce, None,
                f'Выплата дивидендов {ticker}: {div:.2f} ₽ за {year} год',
                payload,
            ))

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, date_start, announce_date, date_end, event, payload) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            rows,
        )
    print(f'  events (дивиденды): {len(rows)} rows attempted')


# ── Главный сценарий ───────────────────────────────────────────────────────

def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=False)
    try:
        print('1. stocks + stock_candles (CSV → Postgres)')
        _load_stocks_and_candles(pg)
        pg.commit()

        print('2. risk_free_rate (RUONIA xlsx → Postgres)')
        _load_ruonia(pg)
        pg.commit()

        print('3. SAVINGS_MIACR — накопительный счёт под MIACR (CSV → stock_candles)')
        _load_savings_miacr(pg)
        pg.commit()

        print('4. dividends (CSV → Postgres)')
        _load_dividends(pg)
        pg.commit()

        with pg.cursor() as cur:
            print('\nfinal counts:')
            for tbl in ('stocks', 'stock_candles', 'risk_free_rate'):
                cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                print(f'  {tbl:24s} {cur.fetchone()[0]}')
            cur.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE event LIKE 'Объявление дивидендов %%' OR event LIKE 'Выплата дивидендов %%'"
            )
            print(f'  events (дивиденды)       {cur.fetchone()[0]}')
    finally:
        pg.close()


if __name__ == '__main__':
    main()
