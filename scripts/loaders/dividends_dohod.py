"""Лоадер: дивидендные выплаты по российским акциям с dohod.ru.

Стадии:
- `fetch()` — для каждого тикера, уже присутствующего в
  `dividends_all.csv` (плюс опциональный список EXTRA_TICKERS), парсит
  страницу `dohod.ru/ik/analytics/dividend/<ticker>`. Полностью
  переписывает CSV (источник отдаёт всю историю каждый раз).
  Перед записью сравнивает старое и новое по количеству выплат на
  тикер.
- `load(pg)` — читает CSV, создаёт два события в `events` на каждую
  строку: «Объявление дивидендов» (event_date = announcement_date) и
  «Выплата дивидендов» (event_date = payment_date). announce_date в
  обоих случаях — announcement_date. id события — детерминированный
  UUID5, ON CONFLICT DO NOTHING гарантирует идемпотентность.
"""
from __future__ import annotations

import re
import sys
import time
import uuid
from pathlib import Path

import json
import pandas as pd
import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[2]
DIVIDENDS_PATH = ROOT / 'data' / 'stocks' / 'dividends_all.csv'

BASE_URL = 'https://www.dohod.ru/ik/analytics/dividend'
REQUEST_DELAY_SEC = 1.0

_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000000')


# ── fetch ─────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> str | None:
    m = re.search(r'(\d{2}\.\d{2}\.\d{4})', s)
    return m.group(1) if m else None


def fetch_dividends(ticker: str) -> pd.DataFrame:
    """Загружает дивиденды одного тикера с dohod.ru."""
    url = f'{BASE_URL}/{ticker.lower()}'
    resp = requests.get(url, timeout=15)
    if resp.status_code == 404:
        print(f'  [!] {ticker}: страница не найдена на dohod.ru')
        return pd.DataFrame()
    resp.raise_for_status()
    resp.encoding = 'utf-8'

    soup = BeautifulSoup(resp.text, 'html.parser')
    tables = soup.find_all('table')

    target = None
    for t in tables:
        headers = [th.get_text(strip=True) for th in t.find_all('th')]
        if len(headers) == 4 and any('объявл' in h.lower() or 'дата' in h.lower() for h in headers):
            target = t
            break

    if target is None:
        print(f'  [!] {ticker}: таблица дивидендов не найдена')
        return pd.DataFrame()

    rows_data = []
    for row in target.find_all('tr')[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all('td')]
        if len(cells) != 4:
            continue

        announcement_raw, payment_raw, year_raw, dividend_raw = cells
        if announcement_raw.lower() == 'n/a':
            continue
        if 'прогноз' in payment_raw.lower() or 'прогноз' in announcement_raw.lower():
            continue

        announcement_date = _parse_date(announcement_raw)
        if announcement_date is None:
            continue
        payment_date = _parse_date(payment_raw)

        try:
            year = int(year_raw)
        except ValueError:
            continue

        dividend_str = dividend_raw.replace(',', '.').replace('\xa0', '')
        try:
            dividend = float(dividend_str)
        except ValueError:
            continue

        rows_data.append({
            'ticker': ticker.upper(),
            'announcement_date': announcement_date,
            'payment_date': payment_date,
            'dividend_per_share': dividend,
            'year': year,
        })

    df = pd.DataFrame(rows_data)
    print(f'  {ticker}: {len(df)} дивидендных выплат')
    return df


def _load_existing() -> pd.DataFrame:
    if not DIVIDENDS_PATH.exists():
        return pd.DataFrame(columns=['ticker', 'announcement_date', 'payment_date',
                                     'dividend_per_share', 'year'])
    return pd.read_csv(DIVIDENDS_PATH)


def _compare_with_existing(new_df: pd.DataFrame, existing_df: pd.DataFrame, ticker: str) -> dict:
    ex = existing_df[existing_df['ticker'] == ticker]
    result = {
        'ticker': ticker,
        'existing_count': len(ex),
        'new_count': len(new_df[new_df['ticker'] == ticker]),
        'matched': 0,
        'only_in_existing': 0,
        'only_in_new': 0,
    }
    if ex.empty:
        result['only_in_new'] = result['new_count']
        return result
    ex_dates = set(ex['announcement_date'].astype(str))
    new_dates = set(new_df[new_df['ticker'] == ticker]['announcement_date'].astype(str))
    result['matched'] = len(ex_dates & new_dates)
    result['only_in_existing'] = len(ex_dates - new_dates)
    result['only_in_new'] = len(new_dates - ex_dates)
    return result


def fetch(extra_tickers: list[str] | None = None) -> None:
    extra_tickers = extra_tickers or []

    existing = _load_existing()
    existing_tickers = sorted(existing['ticker'].unique().tolist())
    all_tickers = sorted(set(existing_tickers + [t.upper() for t in extra_tickers]))
    print(f'Тикеры в dividends_all.csv: {existing_tickers}')
    if extra_tickers:
        print(f'Дополнительные тикеры: {extra_tickers}')

    all_new = []
    for ticker in all_tickers:
        df = fetch_dividends(ticker)
        if not df.empty:
            all_new.append(df)
        time.sleep(REQUEST_DELAY_SEC)

    if not all_new:
        print('Ничего не загружено!')
        return

    new_df = pd.concat(all_new, ignore_index=True)

    print('\n--- Сравнение с существующим файлом ---')
    for ticker in existing_tickers:
        comp = _compare_with_existing(new_df, existing, ticker)
        status = 'OK' if comp['only_in_existing'] == 0 else 'MISMATCH'
        print(f'  {ticker}: было {comp["existing_count"]}, стало {comp["new_count"]}, '
              f'совпало {comp["matched"]}, новых {comp["only_in_new"]}, '
              f'пропало {comp["only_in_existing"]} [{status}]')

    new_df = new_df.sort_values(['ticker', 'announcement_date']).reset_index(drop=True)
    new_df.to_csv(DIVIDENDS_PATH, index=False)
    print(f'\nСохранено {len(new_df)} записей в {DIVIDENDS_PATH}')


# ── load ──────────────────────────────────────────────────────────────────

def _make_event_id(kind: str, ticker: str, date_iso: str) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, f'{kind}_{ticker}_{date_iso}'))


def load(pg) -> None:
    if not DIVIDENDS_PATH.exists():
        print(f'  {DIVIDENDS_PATH} не найден — пропускаем дивиденды')
        return
    df = pd.read_csv(DIVIDENDS_PATH, dtype={'ticker': str, 'year': str})
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
            _make_event_id('DIVIDEND_ANNOUNCEMENT', ticker, announce_iso),
            announce, announce,
            f'Объявление дивидендов {ticker}: {div:.2f} ₽ за {year} год',
            payload,
        ))
        if payment is not None:
            payment_iso = payment.isoformat()
            rows.append((
                _make_event_id('DIVIDEND_PAYMENT', ticker, payment_iso),
                payment, announce,
                f'Выплата дивидендов {ticker}: {div:.2f} ₽ за {year} год',
                payload,
            ))

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, event_date, announce_date, event, payload) '
            'VALUES (%s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            rows,
        )
    print(f'  events (дивиденды): {len(rows)} rows attempted')


# ── direct run ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='только fetch')
    parser.add_argument('--load', action='store_true', help='только load в БД')
    args = parser.parse_args()
    do_fetch = args.fetch or not args.load
    do_load = args.load or not args.fetch

    if do_fetch:
        fetch()
    if do_load:
        pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
        with psycopg.connect(pg_dsn) as pg:
            load(pg)
            pg.commit()
