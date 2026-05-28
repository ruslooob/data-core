"""Лоадер: сплиты акций из ручного CSV `data/stocks/splits.csv`.

Только `load(pg)`: CSV пополняется руками по результатам ручного
аудита (см. `scripts/ops/check_splits.py` — сканер подозрительных
скачков цены). TODO добавить `fetch()` с ISS, когда появится надёжная
ручка истории корпоративных действий.

`load(pg)` создаёт события `STOCK_SPLIT` в `events` (id = детерминированный
UUID5 от ticker + date) и связки в `event_tags`: тег `STOCK_SPLIT`
плюс company-тег тикера. Запускается **до** загрузки свечей: нормализация
котировок читает сплиты обратно из БД, чтобы пересчитать цены до даты
сплита в единый масштаб.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPLITS_CSV = os.path.join(ROOT, 'data', 'stocks', 'splits.csv')

_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000001')


def _make_event_id(ticker: str, date_iso: str) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, f'STOCK_SPLIT_{ticker}_{date_iso}'))


def load(pg) -> None:
    """Сплиты из splits.csv в `events` + связки event_tags.

    Фильтрация по двум множествам: тикер должен быть в `stocks`
    и иметь company-тег в `tags`.
    """
    if not os.path.exists(SPLITS_CSV):
        print(f'  {SPLITS_CSV} не найден — пропускаем сплиты')
        return
    df = pd.read_csv(SPLITS_CSV, dtype={'ticker': str, 'split_date': str})
    df['split_date'] = pd.to_datetime(df['split_date']).dt.date
    df['ratio'] = pd.to_numeric(df['ratio'])

    with pg.cursor() as cur:
        cur.execute('SELECT ticker FROM stocks')
        known_tickers = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT code FROM tags WHERE type = 'company'")
        company_tags = {r[0] for r in cur.fetchall()}

    event_rows: list[tuple] = []
    tag_rows: list[tuple] = []
    skipped: list[str] = []
    for _, r in df.iterrows():
        ticker = str(r['ticker']).upper()
        if ticker not in known_tickers:
            skipped.append(f'{ticker} (нет в stocks)')
            continue
        if ticker not in company_tags:
            skipped.append(f'{ticker} (нет company-тега)')
            continue
        d = r['split_date']
        ratio = float(r['ratio'])
        event_id = _make_event_id(ticker, d.isoformat())
        payload = json.dumps({'ticker': ticker, 'ratio': ratio})
        event_text = (
            f'Сплит акций {ticker} {ratio:g}:1' if ratio >= 1
            else f'Обратный сплит акций {ticker} 1:{1/ratio:g}'
        )
        event_rows.append((event_id, d, d, event_text, payload))
        tag_rows.append((event_id, 'STOCK_SPLIT'))
        tag_rows.append((event_id, ticker))

    if not event_rows:
        print(f'  events (сплиты): 0 (пропущено: {", ".join(skipped) or "—"})')
        return

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, event_date, announce_date, event, payload) '
            'VALUES (%s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            event_rows,
        )
        cur.executemany(
            'INSERT INTO event_tags (event_id, tag_code) VALUES (%s, %s) '
            'ON CONFLICT (event_id, tag_code) DO NOTHING',
            tag_rows,
        )
    print(
        f'  events (сплиты): {len(event_rows)} attempted, '
        f'event_tags: {len(tag_rows)} attempted, '
        f'пропущено: {len(skipped)}'
    )


if __name__ == '__main__':
    import psycopg

    pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
    with psycopg.connect(pg_dsn) as pg:
        load(pg)
        pg.commit()
