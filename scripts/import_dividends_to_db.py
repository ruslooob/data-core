"""Импорт дивидендов из data/stocks/dividends_all.csv в data/db/data-core.duckdb.

На каждую запись создаётся ДВА события:
    - объявление (на announcement_date) с тегом DIVIDEND_ANNOUNCEMENT
    - выплата    (на payment_date)      с тегом DIVIDEND_PAYMENT

Каждое событие также тегируется тикером компании. Тег компании имеет
type='company' и name из имени файла котировок (TICKER_Name_1day_*.txt).
Тег топика (DIVIDEND_ANNOUNCEMENT / DIVIDEND_PAYMENT) имеет type='topic'.

Идемпотентен: повторный запуск не плодит дубликатов. Стабильность через
uuid5(NAMESPACE, '<kind>_<ticker>_<iso_date>') и ON CONFLICT DO NOTHING.

Запуск: python scripts/import_dividends_to_db.py
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from glob import glob
from pathlib import Path

import duckdb
import pandas as pd

# Windows-консоль может быть в cp1251 — заворачиваем stdout/stderr в utf-8.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
DIVIDENDS_FILE = ROOT / 'data' / 'stocks' / 'dividends_all.csv'
STOCKS_DIR = ROOT / 'data' / 'stocks'
DB_FILE = ROOT / 'data' / 'db' / 'data-core.duckdb'

NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000000')

TAG_DIVIDEND_ANNOUNCEMENT = 'DIVIDEND_ANNOUNCEMENT'
TAG_DIVIDEND_PAYMENT = 'DIVIDEND_PAYMENT'


def make_event_id(kind: str, ticker: str, date_iso: str) -> str:
    """Стабильный UUID для пары (kind, ticker, date) — гарантирует идемпотентность."""
    return str(uuid.uuid5(NAMESPACE, f"{kind}_{ticker}_{date_iso}"))


def find_company_name(ticker: str) -> str:
    """Ищет имя компании в имени файла котировок: TICKER_Name_1day_*.txt → Name."""
    pattern = str(STOCKS_DIR / f"{ticker.upper()}_*.txt")
    for path in sorted(glob(pattern)):
        base = os.path.basename(path)
        parts = base.split('_')
        if len(parts) >= 2 and parts[0] == ticker.upper():
            return parts[1]
    return ''


def main() -> None:
    if not DB_FILE.exists():
        print(f'Ошибка: {DB_FILE} не существует. Сначала запустите migrate_csv_to_duckdb.py.')
        sys.exit(1)

    div = pd.read_csv(
        DIVIDENDS_FILE,
        dtype={'ticker': str, 'announcement_date': str,
               'payment_date': str, 'year': str},
    )
    div['announcement_date'] = pd.to_datetime(
        div['announcement_date'], dayfirst=True, errors='coerce',
    )
    div['payment_date'] = pd.to_datetime(
        div['payment_date'], dayfirst=True, errors='coerce',
    )

    con = duckdb.connect(str(DB_FILE))

    existing_event_ids = {r[0] for r in con.execute("SELECT id FROM events").fetchall()}
    existing_tag_keys = {(r[0], r[1]) for r in con.execute("SELECT code, type FROM tags").fetchall()}
    existing_pairs = {
        (r[0], r[1])
        for r in con.execute("SELECT event_id, tag_code FROM event_tags").fetchall()
    }

    new_events: list[tuple] = []
    new_tags: list[tuple] = []
    new_pairs: list[tuple] = []

    # Топик-теги
    for code in (TAG_DIVIDEND_ANNOUNCEMENT, TAG_DIVIDEND_PAYMENT):
        if (code, 'topic') not in existing_tag_keys:
            new_tags.append((code, '', 'topic'))
            existing_tag_keys.add((code, 'topic'))

    for _, row in div.iterrows():
        ticker_raw = row['ticker']
        if pd.isna(ticker_raw) or not ticker_raw:
            continue
        ticker = str(ticker_raw).upper()

        if (ticker, 'company') not in existing_tag_keys:
            new_tags.append((ticker, find_company_name(ticker), 'company'))
            existing_tag_keys.add((ticker, 'company'))

        try:
            amount = float(row['dividend_per_share'])
        except (TypeError, ValueError):
            amount = None
        year = row['year'] if pd.notna(row['year']) else ''

        for kind, topic_tag, date_value in (
            ('DIVIDEND_ANNOUNCEMENT', TAG_DIVIDEND_ANNOUNCEMENT, row['announcement_date']),
            ('DIVIDEND_PAYMENT',      TAG_DIVIDEND_PAYMENT,      row['payment_date']),
        ):
            if pd.isna(date_value):
                continue
            iso = date_value.strftime('%Y-%m-%d')
            event_id = make_event_id(kind, ticker, iso)

            if event_id not in existing_event_ids:
                amount_str = f"{amount:.2f}" if amount is not None else '?'
                action = 'Объявление' if kind == 'DIVIDEND_ANNOUNCEMENT' else 'Выплата'
                year_part = f' за {year} год' if year else ''
                new_events.append((
                    event_id,
                    iso,
                    None,
                    f"{action} дивидендов {ticker}: {amount_str} ₽{year_part}",
                ))
                existing_event_ids.add(event_id)

            for tag_code in (ticker, topic_tag):
                if (event_id, tag_code) not in existing_pairs:
                    new_pairs.append((event_id, tag_code))
                    existing_pairs.add((event_id, tag_code))

    try:
        con.execute("BEGIN")
        if new_tags:
            con.executemany(
                "INSERT INTO tags (code, name, type) VALUES (?, ?, ?)",
                new_tags,
            )
        if new_events:
            con.executemany(
                "INSERT INTO events (id, date_start, date_end, event) VALUES (?, ?, ?, ?)",
                new_events,
            )
        if new_pairs:
            con.executemany(
                "INSERT INTO event_tags (event_id, tag_code) VALUES (?, ?)",
                new_pairs,
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    print(f"Тегов добавлено:    {len(new_tags)}")
    print(f"Событий добавлено:  {len(new_events)}")
    print(f"Связей добавлено:   {len(new_pairs)}")


if __name__ == '__main__':
    main()
