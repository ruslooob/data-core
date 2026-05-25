"""Оркестратор загрузки референсных данных в Postgres.

Один прогон обновляет всё, что нужно для работы стека: тикеры, эмитенты,
сплиты, свечи, дивиденды, ставки ЦБ, RUONIA, синтетический SAVINGS_MIACR
и корпоративные раскрытия с e-disclosure.

Архитектура: один модуль на источник в `scripts/loaders/`. Каждый
определяет до двух стадий — `fetch()` (внешний API → файл в `data/`)
и `load(pg)` (файл → Postgres через `ON CONFLICT DO NOTHING`).
Подробнее — `docs/SPEC_LOADERS.md`.

Запуск:
    python scripts/load_all_data.py                            # всё
    python scripts/load_all_data.py --only moex_stocks,cb_rates
    python scripts/load_all_data.py --list                     # список лоадеров
    python scripts/load_all_data.py --skip-fetch               # только load из файлов
    python scripts/load_all_data.py --only-fetch               # только fetch
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

# scripts/ — не пакет (нет __init__.py на верхнем уровне); чтобы
# импортировать модули из scripts/loaders/, добавляем sys.path-указатель
# на корень репозитория, а импорт делаем относительно него.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import psycopg  # noqa: E402

from loaders import (  # noqa: E402
    cb_rates,
    dividends_dohod,
    edisclosure_events,
    mfd_rates,
    moex_securities,
    moex_stocks,
    ruonia,
    stock_splits,
)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'


@dataclass
class LoaderEntry:
    name: str
    fetch: Callable[[], None] | None = None
    load_stages: list[tuple[str, Callable[[object], None]]] = field(default_factory=list)
    description: str = ''


# Источник истины для порядка загрузки. Зависимости зашиты порядком
# (формальный DAG для 8 источников — overengineering).
#
# Порядок load-стадий объясняется так:
# 1. moex_stocks.load_metadata     — создаёт записи в stocks (нужны всем дальше)
# 2. moex_securities.load          — UPDATE stocks по emitter_id (нужно edisclosure)
# 3. stock_splits.load             — split-events (нужны для нормализации цен)
# 4. moex_stocks.load_candles      — свечи с нормализацией по сплитам
# 5. mfd_rates.load                — синтетический SAVINGS_MIACR в stocks+candles
# 6. ruonia.load                   — независимая таблица risk_free_rate
# 7. dividends_dohod.load          — events дивидендов
# 8. cb_rates.load                 — events решений ЦБ
# 9. edisclosure_events.load       — корпоративные раскрытия (нужны emitters)
LOADERS: list[LoaderEntry] = [
    LoaderEntry(
        name='moex_stocks',
        fetch=moex_stocks.fetch,
        load_stages=[
            ('metadata', moex_stocks.load_metadata),
            ('candles',  moex_stocks.load_candles),
        ],
        description='Котировки акций и индексов Мосбиржи',
    ),
    LoaderEntry(
        name='moex_securities',
        fetch=moex_securities.fetch,
        load_stages=[('load', moex_securities.load)],
        description='Перечень бумаг и эмитентов Мосбиржи',
    ),
    LoaderEntry(
        name='stock_splits',
        fetch=None,
        load_stages=[('load', stock_splits.load)],
        description='Сплиты акций (ручной CSV)',
    ),
    LoaderEntry(
        name='mfd_rates',
        fetch=mfd_rates.fetch,
        load_stages=[('load', mfd_rates.load)],
        description='MIBID/MIBOR/MIACR с mfd.ru → синтетический SAVINGS_MIACR',
    ),
    LoaderEntry(
        name='ruonia',
        fetch=None,
        load_stages=[('load', ruonia.load)],
        description='Безрисковая ставка RUONIA (ручной XLSX)',
    ),
    LoaderEntry(
        name='dividends_dohod',
        fetch=dividends_dohod.fetch,
        load_stages=[('load', dividends_dohod.load)],
        description='Дивидендные выплаты с dohod.ru',
    ),
    LoaderEntry(
        name='cb_rates',
        fetch=cb_rates.fetch,
        load_stages=[('load', cb_rates.load)],
        description='Решения ЦБ по ключевой ставке',
    ),
    LoaderEntry(
        name='edisclosure_events',
        fetch=edisclosure_events.fetch,
        load_stages=[('load', edisclosure_events.load)],
        description='Корпоративные раскрытия с e-disclosure.ru',
    ),
]

# Глобальный порядок load-стадий через все лоадеры. Каждая запись
# (loader_name, stage_name) — потому что у moex_stocks стадии разнесены
# другими лоадерами по середине.
LOAD_ORDER: list[tuple[str, str]] = [
    ('moex_stocks',        'metadata'),
    ('moex_securities',    'load'),
    ('stock_splits',       'load'),
    ('moex_stocks',        'candles'),
    ('mfd_rates',          'load'),
    ('ruonia',             'load'),
    ('dividends_dohod',    'load'),
    ('cb_rates',           'load'),
    ('edisclosure_events', 'load'),
]


def _by_name(name: str) -> LoaderEntry:
    for ldr in LOADERS:
        if ldr.name == name:
            return ldr
    raise KeyError(f'неизвестный лоадер: {name}')


def _print_list() -> None:
    print('Доступные лоадеры (порядок load — снизу LOAD_ORDER):\n')
    for ldr in LOADERS:
        has_fetch = 'да ' if ldr.fetch else 'нет'
        stages = ', '.join(s for s, _ in ldr.load_stages)
        print(f'  {ldr.name:22s}  fetch={has_fetch}  load=[{stages}]  — {ldr.description}')


def _run_fetches(selected: list[str]) -> list[str]:
    """Запускает fetch для каждого выбранного лоадера. Ошибки отдельных
    источников не валят прогон — возвращается список сбойных имён,
    оркестратор продолжает с оставшимися источниками. Так частичная
    недоступность одного API не блокирует обновление всех остальных.
    """
    failed: list[str] = []
    for name in selected:
        ldr = _by_name(name)
        if ldr.fetch is None:
            print(f'== fetch: {name} — нет стадии (TODO), пропуск ==')
            continue
        print(f'== fetch: {name} ==')
        try:
            ldr.fetch()
        except Exception as e:
            failed.append(name)
            print(f'\nWARNING fetch {name} упал: {e!r} — продолжаем без него',
                  file=sys.stderr)
    return failed


def _run_loads(selected_names: set[str], pg) -> None:
    for loader_name, stage_name in LOAD_ORDER:
        if loader_name not in selected_names:
            continue
        ldr = _by_name(loader_name)
        for sname, fn in ldr.load_stages:
            if sname != stage_name:
                continue
            label = loader_name if sname == 'load' else f'{loader_name}.{sname}'
            print(f'== load: {label} ==')
            fn(pg)
            pg.commit()


def _parse_only(raw: str | None) -> list[str]:
    if not raw:
        return [ldr.name for ldr in LOADERS]
    requested = [x.strip() for x in raw.split(',') if x.strip()]
    known = {ldr.name for ldr in LOADERS}
    unknown = [r for r in requested if r not in known]
    if unknown:
        raise SystemExit(
            f'Неизвестные лоадеры: {unknown}. '
            f'Доступные: {sorted(known)}.'
        )
    return requested


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', help='CSV-список лоадеров (см. --list)')
    parser.add_argument('--list', action='store_true', help='показать доступные лоадеры')
    parser.add_argument('--skip-fetch', action='store_true',
                        help='пропустить fetch, только load из существующих файлов')
    parser.add_argument('--only-fetch', action='store_true',
                        help='только fetch, без заливки в БД')
    args = parser.parse_args()

    if args.list:
        _print_list()
        return

    if args.skip_fetch and args.only_fetch:
        raise SystemExit('--skip-fetch и --only-fetch несовместимы')

    selected = _parse_only(args.only)
    selected_set = set(selected)

    do_fetch = not args.skip_fetch
    do_load = not args.only_fetch

    if do_fetch:
        _run_fetches(selected)

    if do_load:
        with psycopg.connect(PG_DSN, autocommit=False) as pg:
            _run_loads(selected_set, pg)

            print('\nfinal counts:')
            with pg.cursor() as cur:
                for tbl in ('stocks', 'stock_candles', 'risk_free_rate', 'emitters'):
                    cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                    print(f'  {tbl:24s} {cur.fetchone()[0]}')
                cur.execute('SELECT COUNT(*) FROM stocks WHERE emitter_id IS NULL')
                print(f'  stocks без эмитента      {cur.fetchone()[0]}')
                cur.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE event LIKE 'Объявление дивидендов %%' "
                    "   OR event LIKE 'Выплата дивидендов %%'"
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


if __name__ == '__main__':
    main()
