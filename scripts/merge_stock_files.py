"""Разовая миграция: объединяет Finam-файл и ISS-файл в один.

Для каждого тикера, у которого в `data/stocks/` лежат и Finam-файл
(`<TICKER>_<кириллическое_имя>_1day_<from>_<till>.txt`), и ISS-файл
(`<TICKER>_ISS_1day_<from>_<till>.txt`):

1. Прочитать оба, сложить строки в `{iso_date: parts}`.
2. При конфликте дат — приоритет ISS (более свежий, авторитетный источник).
3. Инвариант: `len(merged) >= max(len(finam), len(iss))` — данных
   не потеряли. Иначе сразу exit(1), файлы не трогаем.
4. Записать объединение в файл с Finam-именем (чтобы `stocks.name`
   остался читаемым), но с till-датой = `max(finam_till, iss_till)`.
5. Удалить старые Finam и ISS файлы.

После этой миграции `load_moex_stocks.py` уже не различает Finam/ISS,
работает с единственным файлом по тикеру.

См. docs/SPEC_LOADERS.md.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = REPO_ROOT / 'data' / 'stocks'

FINAM_HEADER = (
    '<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>'
)


def _read_finam(path: Path) -> dict[str, list[str]]:
    by_date: dict[str, list[str]] = {}
    with path.open('r', encoding='utf-8') as fh:
        next(fh, None)  # header
        for line in fh:
            parts = line.rstrip('\n').split(';')
            if len(parts) < 10:
                continue
            by_date[parts[2]] = parts
    return by_date


def _ticker_from_finam_name(filename: str) -> str:
    """Из 'LKOH_ЛУКОЙЛ_1day_...txt' извлекает 'LKOH' — первая ASCII-часть до '_'."""
    base = filename.split('_1day_', 1)[0]
    parts = base.split('_')
    ascii_parts: list[str] = []
    for p in parts:
        if p.isascii() and p:
            ascii_parts.append(p)
        else:
            break
    return '_'.join(ascii_parts)


def _list_finam_files() -> dict[str, Path]:
    """Возвращает {ticker: Finam-file path}. Игнорирует ISS-файлы."""
    out: dict[str, Path] = {}
    for path in sorted(STOCKS_DIR.glob('*_1day_*.txt')):
        name = path.name
        if '_ISS_1day_' in name:
            continue
        ticker = _ticker_from_finam_name(name)
        if not ticker:
            continue
        out[ticker] = path
    return out


def _find_iss_file(ticker: str) -> Path | None:
    candidates = list(STOCKS_DIR.glob(f'{ticker}_ISS_1day_*.txt'))
    return candidates[0] if candidates else None


def merge_one(ticker: str, finam_path: Path) -> tuple[int, int, int]:
    """Объединяет Finam и ISS файлы тикера, возвращает (len_finam, len_iss, len_merged).
    Если ISS-файла нет — оставляет Finam как есть и возвращает (len_finam, 0, len_finam)."""
    finam_rows = _read_finam(finam_path)
    iss_path = _find_iss_file(ticker)
    if iss_path is None:
        return len(finam_rows), 0, len(finam_rows)

    iss_rows = _read_finam(iss_path)

    # Приоритет ISS при конфликте дат
    merged = dict(finam_rows)
    merged.update(iss_rows)

    # Инвариант: данных не теряем
    if len(merged) < max(len(finam_rows), len(iss_rows)):
        raise RuntimeError(
            f'{ticker}: объединение УМЕНЬШИЛО размер '
            f'(finam={len(finam_rows)} iss={len(iss_rows)} merged={len(merged)})'
        )

    # Новое имя файла — стабильное, без диапазона дат.
    finam_base = finam_path.stem  # без .txt
    if finam_base.endswith('_1day'):
        prefix = finam_base[:-len('_1day')]
    else:
        prefix = finam_base
    new_filename = f'{prefix}_1day.txt'
    new_path = STOCKS_DIR / new_filename

    # Все строки приводим к консистентному виду: TICKER, D, date, time, OHLCV, OPENINT
    # parts[0] (TICKER) — могут отличаться регистром/префиксом в исходниках.
    sorted_rows = []
    for d in sorted_dates:
        parts = list(merged[d])
        parts[0] = ticker  # унифицируем тикер
        sorted_rows.append(';'.join(parts))

    with new_path.open('w', encoding='utf-8') as fh:
        fh.write(FINAM_HEADER + '\n')
        for line in sorted_rows:
            fh.write(line + '\n')

    # Удалить исходники, кроме случая, когда новое имя совпадает с одним из них
    for old in (finam_path, iss_path):
        if old.name != new_filename:
            old.unlink()

    return len(finam_rows), len(iss_rows), len(merged)


def main() -> None:
    finam_files = _list_finam_files()
    if not finam_files:
        print('Finam-файлов не найдено — нечего сливать')
        return

    print(f'найдено {len(finam_files)} тикеров с Finam-файлами')
    merged_count = 0
    untouched_count = 0
    for ticker, finam_path in finam_files.items():
        try:
            n_f, n_i, n_m = merge_one(ticker, finam_path)
        except RuntimeError as e:
            print(f'  {ticker}: {e}', file=sys.stderr)
            sys.exit(1)
        if n_i == 0:
            print(f'  {ticker}: ISS-файла нет — оставлен как есть ({n_f} строк)')
            untouched_count += 1
        else:
            print(f'  {ticker}: finam={n_f}, iss={n_i}, merged={n_m}')
            merged_count += 1
    print()
    print(f'merged : {merged_count}')
    print(f'kept   : {untouched_count}')


if __name__ == '__main__':
    main()
