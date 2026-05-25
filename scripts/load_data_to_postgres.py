"""Идемпотентная загрузка референсных данных в Postgres.

Схема и UDF создаются Liquibase-миграцией (`docker compose --profile migrate
run liquibase update`). Этот скрипт льёт **только данные**:

- `stocks` — метаданные тикеров из имён файлов `data/stocks/<TICKER>_<NAME>_1day.txt`.
- `emitters` + расширение `stocks` (ISIN, тип, листинг, объём выпуска и т.д.) —
  из `data/stocks/moex_securities.csv` и `data/stocks/moex_emitters.csv`
  (готовятся `scripts/load_moex_securities_list.py`). Обогащаются только
  тикеры, уже существующие в `stocks`; синтетические инструменты
  (SAVINGS_MIACR и пр.) пропускаются.
- Сплиты акций — из `data/stocks/splits.csv` в `events` как `STOCK_SPLIT`,
  с тегами {STOCK_SPLIT, <ticker>}. Заливаются **до** свечей: нормализация
  цен в `_load_stocks_and_candles` читает сплиты обратно из `events`.
- `stock_candles` — из `data/stocks/<TICKER>_<NAME>_1day.txt`,
  с нормализацией по сплитам из БД.
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
- Решения ЦБ по ключевой ставке — из `data/macro/cb_rates.csv` в `events`
  как `CB_RATE_DECISION` (`announcement_date = effective_date - 1 BD`,
  payload содержит ставку до/после и направление).
- Корпоративные раскрытия с e-disclosure.ru — из `data/events/edisclosure_*.json`
  (готовятся `scripts/load_edisclosure_events.py`). Каждое событие — строка
  в `events` с детерминированным id `edisc:<pseudoGUID>`. Связи: тег типа
  события (`REPORT_IFRS`/`REPORT_RSBU_ANNUAL`/`BUYBACK_ANNOUNCE`/`BUYBACK_EXECUTE`)
  плюс тег на каждую бумагу эмитента (дублирование тегов для эмитента
  с несколькими бумагами — осознанное решение, см. SPEC_CORP_DISCLOSURE).

Все INSERT'ы через `ON CONFLICT DO NOTHING` — повторный запуск безопасен.

Пользовательские данные (tags, events, event_tags, precedent_queries,
research, strategies, rules, environments, backtest_results, trade_journal)
НЕ заливаются — восстанавливаются из pg_dump снапшота. **Исключение**:
event_tags для дивидендных, сплит- и ЦБ-событий — детерминированные сидовые
связки, не пользовательские, поэтому заливаются здесь.

Запуск:
    python scripts/load_data_to_postgres.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import uuid
from datetime import date
from glob import glob

import pandas as pd
import psycopg

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS_DIR = os.path.join(ROOT, 'data', 'stocks')
SPLITS_CSV = os.path.join(STOCKS_DIR, 'splits.csv')
CB_RATES_CSV = os.path.join(ROOT, 'data', 'macro', 'cb_rates.csv')
MOEX_SECURITIES_CSV = os.path.join(STOCKS_DIR, 'moex_securities.csv')
MOEX_EMITTERS_CSV = os.path.join(STOCKS_DIR, 'moex_emitters.csv')
EDISCLOSURE_EVENTS_GLOB = os.path.join(ROOT, 'data', 'events', 'edisclosure', '*.json')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

CANDLE_COLS_RAW = ['<TICKER>', '<PER>', '<DATE>', '<TIME>',
                   '<OPEN>', '<HIGH>', '<LOW>', '<CLOSE>',
                   '<VOL>', '<OPENINT>']


# ── Сплиты: чтение обратно из events для нормализации свечей ───────────────

def _fetch_splits_from_events(pg, ticker: str) -> list[dict]:
    """Сплиты тикера из таблицы `events` в формате,
    совместимом с `_load_normalized_candles`.
    """
    with pg.cursor() as cur:
        cur.execute(
            "SELECT e.date_start, (e.payload->>'ratio')::float "
            "FROM events e "
            "JOIN event_tags et ON et.event_id = e.id "
            "WHERE et.tag_code = 'STOCK_SPLIT' "
            "  AND e.payload->>'ticker' = %s "
            "ORDER BY e.date_start",
            [ticker.upper()],
        )
        rows = cur.fetchall()
    return [{'split_date': d.isoformat(), 'ratio': float(r)} for d, r in rows]


def _parse_ticker_and_name(filename: str, file_path: str) -> tuple[str, str]:
    with open(file_path, 'r', encoding='utf-8') as fh:
        fh.readline()  # заголовок
        first = fh.readline()
    ticker_from_data = first.split(';', 1)[0].strip().upper()
    base = os.path.splitext(filename)[0]

    # Канонический формат имени: <prefix>_1day.txt.
    # Файлы без `_1day` — это тестовые фикстуры (TEST.txt, TEST_SPLIT.txt),
    # из них берём тикер из данных, name пустой.
    if base.endswith('_1day'):
        prefix = base[:-len('_1day')]
    else:
        return ticker_from_data, ''

    # Тикер из имени файла: ведущие ASCII-сегменты до первого кириллического.
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


def _load_stocks_metadata(pg) -> None:
    """INSERT тикеров в `stocks` (без свечей, без сплитов)."""
    files = sorted(glob(os.path.join(STOCKS_DIR, '*.txt')))
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


def _load_stocks_candles(pg) -> None:
    """INSERT свечей с нормализацией по сплитам, прочитанным из `events`.

    Запускается **после** `_load_stock_splits` — иначе нормализация
    будет пустой и цены до даты сплита получатся в исходном масштабе.
    """
    files = sorted(glob(os.path.join(STOCKS_DIR, '*.txt')))
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
            # Конфликты по (ticker, date) с этим фильтром невозможны, ON CONFLICT
            # оставлен как страховка от гонок.
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


# ── MOEX securities + emitters ─────────────────────────────────────────────

def _load_moex_securities_and_emitters(pg) -> None:
    """Заливает эмитентов и обогащает карточки бумаг из MOEX-снапшота.

    Порядок: сначала emitters (FK-цель), потом UPDATE по stocks.
    Обогащаются только тикеры, уже присутствующие в stocks (что есть
    в БД, но нет в MOEX-выгрузке — например, синтетический
    SAVINGS_MIACR — остаются с emitter_id IS NULL).
    """
    if not os.path.exists(MOEX_SECURITIES_CSV) or not os.path.exists(MOEX_EMITTERS_CSV):
        print('  MOEX-снапшот отсутствует — пропускаем эмитентов и расширение stocks')
        return

    with open(MOEX_SECURITIES_CSV, encoding='utf-8') as fh:
        all_secs = list(csv.DictReader(fh))
    with open(MOEX_EMITTERS_CSV, encoding='utf-8') as fh:
        all_emits = {e['emitter_id']: e for e in csv.DictReader(fh)}

    with pg.cursor() as cur:
        cur.execute('SELECT ticker FROM stocks')
        known_tickers = {r[0] for r in cur.fetchall()}

    enrichable = [s for s in all_secs if s['ticker'] in known_tickers]
    needed_emitter_ids = {s['emitter_id'] for s in enrichable}
    relevant_emitters = [all_emits[eid] for eid in needed_emitter_ids if eid in all_emits]

    emitter_rows = [
        (int(e['emitter_id']), e['inn'], e['okpo'] or None, e['title'])
        for e in relevant_emitters
    ]
    security_rows = [
        (
            int(s['emitter_id']),
            s['isin'] or None,
            s['regnumber'] or None,
            s['full_name'] or None,
            s['short_name'] or None,
            s['latname'] or None,
            s['security_type'] or None,
            int(s['list_level']) if s['list_level'] else None,
            int(s['issue_size']) if s['issue_size'] else None,
            float(s['face_value']) if s['face_value'] else None,
            s['face_unit'] or None,
            s['issue_date'] or None,
            s['primary_boardid'] or None,
            s['ticker'],
        )
        for s in enrichable
    ]

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO emitters (emitter_id, inn, okpo, title) '
            'VALUES (%s, %s, %s, %s) ON CONFLICT (emitter_id) DO NOTHING',
            emitter_rows,
        )
        cur.executemany(
            'UPDATE stocks SET '
            'emitter_id = %s, isin = %s, regnumber = %s, '
            'full_name = %s, short_name = %s, latname = %s, '
            'security_type = %s, list_level = %s, issue_size = %s, '
            'face_value = %s, face_unit = %s, issue_date = %s, '
            'primary_boardid = %s '
            'WHERE ticker = %s',
            security_rows,
        )

    print(f'  emitters: {len(emitter_rows)} attempted')
    print(f'  stocks обогащено: {len(enrichable)} (из {len(known_tickers)} в БД)')

    moex_tickers = {s['ticker'] for s in all_secs}
    not_in_moex = sorted(known_tickers - moex_tickers)
    if not_in_moex:
        print(f'  без MOEX-карточки (emitter_id останется NULL): {", ".join(not_in_moex)}')


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
            'INSERT INTO stocks (ticker, name) VALUES (%s, %s) '
            'ON CONFLICT (ticker) DO NOTHING',
            [_SAVINGS_TICKER, _SAVINGS_NAME],
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


# ── UUID5-namespace на каждый класс событий ───────────────────────────────
# Один и тот же набор атрибутов (ticker/date/...) даёт один и тот же UUID,
# ON CONFLICT DO NOTHING обеспечивает идемпотентность повторных запусков.

_DIVIDEND_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000000')
_STOCK_SPLIT_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000001')
_CB_RATE_EVENT_NAMESPACE = uuid.UUID('00dc6acf-fc00-4000-8000-000000000002')


def _make_dividend_event_id(kind: str, ticker: str, date_iso: str) -> str:
    return str(uuid.uuid5(_DIVIDEND_EVENT_NAMESPACE, f'{kind}_{ticker}_{date_iso}'))


def _make_split_event_id(ticker: str, date_iso: str) -> str:
    return str(uuid.uuid5(_STOCK_SPLIT_EVENT_NAMESPACE, f'STOCK_SPLIT_{ticker}_{date_iso}'))


def _make_cb_rate_event_id(rate_type: str, effective_iso: str) -> str:
    return str(uuid.uuid5(_CB_RATE_EVENT_NAMESPACE, f'CB_RATE_DECISION_{rate_type}_{effective_iso}'))


# ── Сплиты акций ───────────────────────────────────────────────────────────

def _load_stock_splits(pg) -> None:
    """Сплиты из `data/stocks/splits.csv` в `events` + связки event_tags.

    Запускается **до** `_load_stocks_candles`: нормализация свечей
    читает сплиты обратно из events. Фильтрация по двум множествам:
    тикер должен быть в `stocks` и иметь company-тег в `tags`.
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
        event_id = _make_split_event_id(ticker, d.isoformat())
        payload = json.dumps({'ticker': ticker, 'ratio': ratio})
        event_text = (
            f'Сплит акций {ticker} {ratio:g}:1' if ratio >= 1
            else f'Обратный сплит акций {ticker} 1:{1/ratio:g}'
        )
        event_rows.append((event_id, d, d, None, event_text, payload))
        tag_rows.append((event_id, 'STOCK_SPLIT'))
        tag_rows.append((event_id, ticker))

    if not event_rows:
        print(f'  events (сплиты): 0 (пропущено: {", ".join(skipped) or "—"})')
        return

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, date_start, announce_date, date_end, event, payload) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb) '
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


# ── Решения ЦБ по ставке ──────────────────────────────────────────────────

def _shift_business_day(d: date, offset: int) -> date:
    """Сдвиг на N рабочих дней (без учёта праздников).

    Используется только для приближения announcement_date решения ЦБ
    как `effective_date - 1 BD`. Точная дата пресс-релиза лежит на
    `cbr.ru/dkp/decisions/` — отдельная итерация.
    """
    return (pd.Timestamp(d) + pd.tseries.offsets.BDay(offset)).date()


def _format_cb_event_text(rate_type: str, rate: float, prev: float | None, direction: str) -> str:
    name = 'ключевой ставки' if rate_type == 'key' else 'ставки рефинансирования'
    if direction == 'initial':
        return f'Установление {name}: {rate:g}%'
    if direction == 'hold':
        return f'Сохранение {name} на уровне {rate:g}%'
    arrow = '↑' if direction == 'hike' else '↓'
    return f'Изменение {name}: {prev:g}% → {rate:g}% {arrow}'


def _load_cb_rates(pg) -> None:
    if not os.path.exists(CB_RATES_CSV):
        print(f'  {CB_RATES_CSV} не найден — пропускаем ставку ЦБ')
        return
    df = pd.read_csv(CB_RATES_CSV, dtype={'rate_type': str})
    df['effective_date'] = pd.to_datetime(df['effective_date']).dt.date
    df['rate_pct'] = pd.to_numeric(df['rate_pct'])
    df = df.sort_values(['rate_type', 'effective_date']).reset_index(drop=True)

    event_rows: list[tuple] = []
    tag_rows: list[tuple] = []
    for rate_type, group in df.groupby('rate_type', sort=False):
        prev_rate: float | None = None
        for _, r in group.iterrows():
            effective = r['effective_date']
            rate = float(r['rate_pct'])
            if prev_rate is None:
                direction = 'initial'
                change_bp = None
            elif rate > prev_rate:
                direction = 'hike'
                change_bp = int(round((rate - prev_rate) * 100))
            elif rate < prev_rate:
                direction = 'cut'
                change_bp = int(round((rate - prev_rate) * 100))
            else:
                direction = 'hold'
                change_bp = 0

            announce = _shift_business_day(effective, -1)
            event_id = _make_cb_rate_event_id(rate_type, effective.isoformat())
            payload = json.dumps({
                'rate_type': rate_type,
                'rate_pct': rate,
                'rate_pct_prev': prev_rate,
                'change_bp': change_bp,
                'direction': direction,
                'effective_date': effective.isoformat(),
            })
            event_text = _format_cb_event_text(rate_type, rate, prev_rate, direction)
            event_rows.append((event_id, announce, announce, None, event_text, payload))
            tag_rows.append((event_id, 'CB_RATE_DECISION'))
            prev_rate = rate

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events '
            '(id, date_start, announce_date, date_end, event, payload) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            event_rows,
        )
        cur.executemany(
            'INSERT INTO event_tags (event_id, tag_code) VALUES (%s, %s) '
            'ON CONFLICT (event_id, tag_code) DO NOTHING',
            tag_rows,
        )
    print(f'  events (ЦБ ставка): {len(event_rows)} attempted')


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


# ── Корпоративные раскрытия с e-disclosure ────────────────────────────────

# Нормализованный текст eventName → код нашего тега. Нормализация:
# схлопывание любой последовательности пробельных символов в один пробел
# плюс strip. Это снимает реальный дубль на портале — «…стоимость или
# ⎵⎵котировки…» с двойным пробелом vs одинарным. Эмитенты, чей тип
# события не присутствует в словаре, остаются в JSON на диске и в БД
# не попадают — расширение словаря не требует перезагрузки с e-disclosure.
EDISCLOSURE_EVENT_NAME_TO_TAG: dict[str, str] = {
    # REPORT_IFRS — зонтик над тремя регуляторными формами одной сущности
    # (раскрытие отчётности по международному / консолидированному стандарту);
    # эмитенты переключались между ними по мере смены положений ЦБ, но для
    # event-study это один и тот же тип события.
    'Раскрытие эмитентом бухгалтерской отчетности в стандартах МСФО или US GAAP':
        'REPORT_IFRS',
    'Раскрытие эмитентом консолидированной финансовой отчетности':
        'REPORT_IFRS',
    'Раскрытие эмитентом сводной бухгалтерской (консолидированной финансовой) отчетности':
        'REPORT_IFRS',
    'Раскрытие эмитентом ежеквартального отчета':
        'REPORT_QUARTERLY',
    'Раскрытие в сети Интернет годовой бухгалтерской отчетности':
        'REPORT_RSBU_ANNUAL',
    'Принятие решения о приобретении размещённых эмитентом акций':
        'BUYBACK_ANNOUNCE',
    'Принятие решения о приобретении размещенных эмитентом акций':  # без «ё»
        'BUYBACK_ANNOUNCE',
    'Приобретение эмитентом собственных голосующих акций (долей) или депозитарных расписок на акции эмитента':
        'BUYBACK_EXECUTE',
    # Buyback через подконтрольную организацию — для event-study неотличим
    # от прямого выкупа эмитентом, кладётся под тот же тег.
    'Приобретение подконтрольной эмитенту организацией голосующих акций (долей) эмитента или депозитарных расписок на акции эмитента':
        'BUYBACK_EXECUTE',
    # SPO — отчуждение собственных или казначейских акций (продажа в рынок).
    # Симметрично BUYBACK_EXECUTE по экономическому смыслу, реакция котировок
    # обратная. Покрывает оба варианта — самим эмитентом и через подконтрольную.
    'Отчуждение эмитентом собственных голосующих акций (долей) или депозитарных расписок на акции эмитента':
        'SPO',
    'Отчуждение подконтрольной эмитенту организацией голосующих акций (долей) эмитента или депозитарных расписок на акции эмитента':
        'SPO',
}


def _normalize_event_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name).strip()


def _load_edisclosure_events(pg) -> None:
    """Заливает корпоративные события из data/events/edisclosure_*.json.

    На каждое событие: одна строка в `events` (id = `edisc:<pseudoGUID>`),
    плюс связи в `event_tags` — тег типа события и теги всех бумаг
    эмитента из stocks. Параллельно заполняется emitters.e_disclosure_company_id.
    """
    files = sorted(glob(EDISCLOSURE_EVENTS_GLOB))
    if not files:
        print('  Нет файлов edisclosure_*.json — пропускаем')
        return

    with pg.cursor() as cur:
        cur.execute("SELECT code FROM tags WHERE type = 'company'")
        company_tags = {r[0] for r in cur.fetchall()}
        cur.execute(
            'SELECT emitter_id, ticker FROM stocks WHERE emitter_id IS NOT NULL'
        )
        tickers_by_emitter: dict[int, list[str]] = {}
        for emitter_id, ticker in cur.fetchall():
            if ticker in company_tags:
                tickers_by_emitter.setdefault(emitter_id, []).append(ticker)

    event_rows: list[tuple] = []
    tag_rows: list[tuple] = []
    company_id_updates: dict[int, int] = {}  # emitter_id → e_disclosure_company_id
    unknown_types: dict[str, str] = {}  # event_name → пример-файл
    files_without_tickers: list[str] = []

    for path in files:
        with open(path, encoding='utf-8') as fh:
            snap = json.load(fh)
        inn = snap['inn']
        emitter_id = snap['emitter_id']
        tickers = tickers_by_emitter.get(emitter_id, [])
        if not tickers:
            files_without_tickers.append(os.path.basename(path))
            continue

        for raw in snap['events']:
            event_name = _normalize_event_name(raw['eventName'])
            tag = EDISCLOSURE_EVENT_NAME_TO_TAG.get(event_name)
            if tag is None:
                unknown_types.setdefault(event_name, os.path.basename(path))
                continue
            pseudo_guid = raw['pseudoGUID']
            event_id = f'edisc:{pseudo_guid}'
            event_date = raw['eventDate'][:10]
            pub_date = raw['pubDate'][:10]
            payload = json.dumps({
                'pseudoGUID': pseudo_guid,
                'inn': inn,
                'emitter_id': emitter_id,
                'company_id_edisclosure': raw.get('companyID'),
                'agency': raw.get('agency'),
            })
            event_rows.append((event_id, event_date, pub_date, None, event_name, payload))
            tag_rows.append((event_id, tag))
            for ticker in tickers:
                tag_rows.append((event_id, ticker))

            cid = raw.get('companyID')
            if cid is not None and emitter_id not in company_id_updates:
                company_id_updates[emitter_id] = cid

    with pg.cursor() as cur:
        cur.executemany(
            'INSERT INTO events (id, date_start, announce_date, date_end, event, payload) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb) '
            'ON CONFLICT (id) DO NOTHING',
            event_rows,
        )
        cur.executemany(
            'INSERT INTO event_tags (event_id, tag_code) VALUES (%s, %s) '
            'ON CONFLICT (event_id, tag_code) DO NOTHING',
            tag_rows,
        )
        cur.executemany(
            'UPDATE emitters SET e_disclosure_company_id = %s '
            'WHERE emitter_id = %s AND e_disclosure_company_id IS NULL',
            [(cid, eid) for eid, cid in company_id_updates.items()],
        )

    print(f'  events (e-disclosure): {len(event_rows)} attempted, '
          f'event_tags: {len(tag_rows)} attempted, '
          f'company_id обновлено у {len(company_id_updates)} эмитентов')
    if files_without_tickers:
        print(f'  пропущено файлов (эмитент не в stocks): {len(files_without_tickers)}')
    if unknown_types:
        print(f'  WARNING: {len(unknown_types)} неизвестных типов событий:')
        for name, fname in list(unknown_types.items())[:5]:
            print(f'    "{name[:80]}" ({fname})')


# ── Главный сценарий ───────────────────────────────────────────────────────

def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=False)
    try:
        print('1. stocks metadata (filename → Postgres)')
        _load_stocks_metadata(pg)
        pg.commit()

        print('2. MOEX securities + emitters (CSV → emitters, UPDATE stocks)')
        _load_moex_securities_and_emitters(pg)
        pg.commit()

        print('3. stock splits (splits.csv → events)')
        _load_stock_splits(pg)
        pg.commit()

        print('4. stock_candles (CSV → Postgres, нормализация по сплитам из events)')
        _load_stocks_candles(pg)
        pg.commit()

        print('5. risk_free_rate (RUONIA xlsx → Postgres)')
        _load_ruonia(pg)
        pg.commit()

        print('6. SAVINGS_MIACR — накопительный счёт под MIACR (CSV → stock_candles)')
        _load_savings_miacr(pg)
        pg.commit()

        print('7. dividends (CSV → events)')
        _load_dividends(pg)
        pg.commit()

        print('8. ЦБ ключевая ставка (cb_rates.csv → events)')
        _load_cb_rates(pg)
        pg.commit()

        print('9. e-disclosure corporate events (JSON → events + event_tags)')
        _load_edisclosure_events(pg)
        pg.commit()

        with pg.cursor() as cur:
            print('\nfinal counts:')
            for tbl in ('stocks', 'stock_candles', 'risk_free_rate', 'emitters'):
                cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                print(f'  {tbl:24s} {cur.fetchone()[0]}')
            cur.execute('SELECT COUNT(*) FROM stocks WHERE emitter_id IS NULL')
            print(f'  stocks без эмитента      {cur.fetchone()[0]}')
            cur.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE event LIKE 'Объявление дивидендов %%' OR event LIKE 'Выплата дивидендов %%'"
            )
            print(f'  events (дивиденды)       {cur.fetchone()[0]}')
            cur.execute(
                "SELECT COUNT(*) FROM event_tags WHERE tag_code = 'STOCK_SPLIT'"
            )
            print(f'  events (сплиты)          {cur.fetchone()[0]}')
            cur.execute(
                "SELECT COUNT(*) FROM event_tags WHERE tag_code = 'CB_RATE_DECISION'"
            )
            print(f'  events (ЦБ ставка)       {cur.fetchone()[0]}')
            cur.execute(
                "SELECT tag_code, COUNT(*) FROM event_tags et "
                "JOIN tags t ON t.code = et.tag_code "
                "WHERE t.type = 'corporate_disclosure' "
                "GROUP BY tag_code ORDER BY tag_code"
            )
            for tag, n in cur.fetchall():
                print(f'  events ({tag:20s}) {n}')
    finally:
        pg.close()


if __name__ == '__main__':
    main()
