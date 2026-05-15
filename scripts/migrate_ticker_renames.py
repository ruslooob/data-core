"""Одноразовая миграция тикеров после реорганизаций эмитентов и опечаток в Finam-выгрузках.

Что делает:

1. Опечатки в Finam (C↔S в кириллической транслитерации):
   CNGS → SNGS (Сургутнефтегаз обыкновенные)
   CPBE → SPBE (СПБ Биржа)

2. Реорганизации (старый делистнут, новый торгуется как МКПАО):
   TCSG → T   (Т-Технологии)
   HHRU → HEAD (Хэдхантер)
   CIAN → CNRU (Циан)
   FIVE → X5  (Корпоративный центр ИКС 5)  + удаление дубля FIVE_X5 из БД
   AGRO → RAGR (Группа Русагро) + дозагрузка старой истории AGRO с ISS

Для каждой пары: переименование файла в data/stocks/, замена тикера в первой
колонке внутри файла, перенос stock_candles в БД под новым тикером, удаление
старой записи в stocks.

Для AGRO/RAGR дополнительно: вытащить с ISS всю историю AGRO (до 2025-02-17 —
первого дня торгов RAGR на МосБирже), записать как RAGR-историю и заинсёртить
в stock_candles, так как существующий файл RAGR содержит только период
2025-02-17 .. 2025-09-05 (новое юрлицо).

Скрипт идемпотентный — повторный запуск ничего не сломает.
После прогона удалить отдельным коммитом (см. SPEC_LOADERS).
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))
from load_moex_stocks import (
    FINAM_HEADER,
    PG_DSN,
    STOCKS_DIR,
    _safe_filename_part,
    dedupe_by_max_numtrades,
    fetch_iss_shares,
)

# (old, new, shortname, fullname)
PAIRS: list[tuple[str, str, str, str]] = [
    ('CNGS', 'SNGS', 'Сургнфгз', 'Сургутнефтегаз ПАО акции об.'),
    ('CPBE', 'SPBE', 'СПБ Биржа', 'СПБ Биржа ао'),
    ('TCSG', 'T', 'Т-Техно ао', 'Т-Технологии МКПАО ао'),
    ('HHRU', 'HEAD', 'Хэдхантер', 'МКПАО Хэдхантер'),
    ('CIAN', 'CNRU', 'iЦиан', 'МКПАО "Циан"'),
    ('FIVE', 'X5', 'КЦ ИКС 5', 'Корпоративный центр ИКС 5'),
    ('AGRO', 'RAGR', 'Русагро', 'Группа Русагро'),
]

AGRO_CUTOFF_ISO = '2025-02-17'  # первый день торгов RAGR на МосБирже


def _find_old_file(old_ticker: str) -> Path | None:
    """Ищет файл со старым тикером по маске `<OLD>_*_1day.txt`."""
    matches = list(STOCKS_DIR.glob(f'{old_ticker}_*_1day.txt'))
    if not matches:
        return None
    if len(matches) > 1:
        raise RuntimeError(f'{old_ticker}: найдено несколько файлов: {[p.name for p in matches]}')
    return matches[0]


def _rewrite_simple(old_path: Path, new_ticker: str, new_shortname: str) -> Path:
    """Создаёт новый файл с заменой первой колонки на new_ticker.
    Удаляет старый файл."""
    new_name = f'{new_ticker}_{_safe_filename_part(new_shortname)}_1day.txt'
    new_path = STOCKS_DIR / new_name
    with old_path.open('r', encoding='utf-8') as fin, new_path.open('w', encoding='utf-8') as fout:
        header = fin.readline()
        fout.write(header)
        for line in fin:
            parts = line.rstrip('\n').split(';')
            parts[0] = new_ticker
            fout.write(';'.join(parts) + '\n')
    if old_path != new_path:
        old_path.unlink()
    return new_path


def _format_iss_row(ticker: str, r: dict) -> str:
    """Преобразует строку из ISS в формат Finam (10 столбцов через ';')."""
    iso = r['TRADEDATE'].replace('-', '')
    fmt = lambda v: '0' if v is None else str(v)  # noqa: E731
    fields = [ticker, 'D', iso, '000000',
              fmt(r['OPEN']), fmt(r['HIGH']), fmt(r['LOW']), fmt(r['CLOSE']),
              fmt(r['VOLUME']), '0']
    return ';'.join(fields)


def _write_agro_ragr_file(agro_old_rows: list[dict], new_ticker: str, new_shortname: str) -> Path:
    """Склейка: старая AGRO история (с ISS, до cutoff) + существующие RAGR-строки из файла."""
    cutoff_compact = AGRO_CUTOFF_ISO.replace('-', '')
    old_path = _find_old_file('AGRO')
    existing_lines: list[str] = []
    if old_path is not None:
        with old_path.open('r', encoding='utf-8') as fin:
            fin.readline()
            for line in fin:
                parts = line.rstrip('\n').split(';')
                if parts[2] >= cutoff_compact:
                    parts[0] = new_ticker
                    existing_lines.append(';'.join(parts))

    new_path = STOCKS_DIR / f'{new_ticker}_{_safe_filename_part(new_shortname)}_1day.txt'
    with new_path.open('w', encoding='utf-8') as fout:
        fout.write(FINAM_HEADER + '\n')
        for r in agro_old_rows:
            fout.write(_format_iss_row(new_ticker, r) + '\n')
        for line in existing_lines:
            fout.write(line + '\n')

    if old_path is not None and old_path != new_path:
        old_path.unlink()
    return new_path


def main() -> None:
    print('=== Шаг 1: достаём с ISS старую историю AGRO ===')
    agro_rows_all, _ = fetch_iss_shares('AGRO', None)
    agro_rows_all = dedupe_by_max_numtrades(agro_rows_all)
    agro_old_rows = [r for r in agro_rows_all if r['TRADEDATE'] < AGRO_CUTOFF_ISO]
    print(f'  ISS вернул {len(agro_rows_all)} строк, '
          f'до cutoff {AGRO_CUTOFF_ISO}: {len(agro_old_rows)} строк')
    if agro_old_rows:
        print(f'  диапазон AGRO old: {agro_old_rows[0]["TRADEDATE"]} .. {agro_old_rows[-1]["TRADEDATE"]}')

    print('\n=== Шаг 2: миграция БД (одна транзакция) ===')
    with psycopg.connect(PG_DSN) as con:
        with con.cursor() as cur:
            # Дубль FIVE_X5
            cur.execute('DELETE FROM stock_candles WHERE ticker = %s', ['FIVE_X5'])
            print(f'  дубль FIVE_X5: удалено {cur.rowcount} свечей')
            cur.execute('DELETE FROM stocks WHERE ticker = %s', ['FIVE_X5'])
            print(f'  дубль FIVE_X5: удалена stocks-строка ({cur.rowcount})')

            # Все пары
            for old, new, shortname, _fullname in PAIRS:
                cur.execute(
                    'INSERT INTO stocks (ticker, name, splits) '
                    'VALUES (%s, %s, %s::jsonb) ON CONFLICT (ticker) DO NOTHING',
                    [new, shortname, '[]'],
                )
                inserted_stocks = cur.rowcount
                cur.execute(
                    'UPDATE stock_candles SET ticker = %s WHERE ticker = %s',
                    [new, old],
                )
                moved = cur.rowcount
                cur.execute('DELETE FROM stocks WHERE ticker = %s', [old])
                deleted = cur.rowcount
                print(f'  {old:5} → {new:5}: stocks INSERT={inserted_stocks}, '
                      f'candles UPDATE={moved}, stocks DELETE={deleted}')

            # AGRO old history → RAGR
            inserted_agro = 0
            for r in agro_old_rows:
                cur.execute(
                    'INSERT INTO stock_candles '
                    '(ticker, candle_date, open, high, low, close, volume, open_interest) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, 0) ON CONFLICT DO NOTHING',
                    ['RAGR', r['TRADEDATE'], r['OPEN'], r['HIGH'],
                     r['LOW'], r['CLOSE'], r['VOLUME']],
                )
                inserted_agro += cur.rowcount
            print(f'  AGRO старая история → RAGR: вставлено {inserted_agro} свечей')

        con.commit()

    print('\n=== Шаг 3: переименование файлов ===')
    for old, new, shortname, _fullname in PAIRS:
        if old == 'AGRO':
            new_path = _write_agro_ragr_file(agro_old_rows, new, shortname)
            print(f'  AGRO → RAGR: написан {new_path.name}')
        else:
            old_path = _find_old_file(old)
            if old_path is None:
                print(f'  {old} → {new}: старый файл уже отсутствует (skip)')
                continue
            new_path = _rewrite_simple(old_path, new, shortname)
            print(f'  {old:5} → {new:5}: {new_path.name}')

    print('\nГотово. Дальше:')
    print('  1) python scripts/load_moex_stocks.py — догрузить хвосты с ISS')
    print('  2) python scripts/load_data_to_postgres.py — залить новые свечи в БД')


if __name__ == '__main__':
    main()
