"""Cross-validation: ISS Мосбиржа vs локальные Finam-выгрузки.

Сверяет 10 тикеров × 10 sample-дат: open и close должны совпадать с
допуском 0.5%. Сравнение идёт с RAW-ценами Finam-файлов (а не с
БД-значениями), потому что в БД лежат скорректированные на сплиты
цены, а ISS отдаёт сырые.

Скрипт одноразовый — после успешного прохождения удаляется отдельным
коммитом. См. docs/SPEC_LOADERS.md, раздел "Cross-validation".
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = REPO_ROOT / 'data' / 'stocks'

ISS_URL = (
    'https://iss.moex.com/iss/history/engines/stock/markets/shares/'
    'securities/{ticker}.json'
)

TICKERS = ['LKOH', 'SBER', 'GAZP', 'GMKN', 'NVTK', 'ROSN', 'MGNT', 'TATN', 'CHMF', 'MTSS']
DATES = [
    '2005-06-15', '2008-03-14', '2010-09-15', '2012-04-16', '2014-11-14',
    '2016-02-15', '2018-07-13', '2020-10-15', '2022-12-15', '2024-05-15',
]

TOLERANCE_PCT = 0.005  # 0.5%


def _request(url: str, params: dict) -> dict:
    full = f'{url}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(full, headers={'User-Agent': 'data-core/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_iss_one_day(ticker: str, date: str) -> tuple[float, float] | None:
    """Возвращает (open, close) с ISS на конкретную дату — или None."""
    payload = _request(
        ISS_URL.format(ticker=ticker),
        {'from': date, 'till': date, 'marketprice_board': 1, 'iss.meta': 'off'},
    )
    block = payload.get('history', {})
    cols = block.get('columns', [])
    data = block.get('data', [])
    if not data:
        return None
    op_idx = cols.index('OPEN')
    cl_idx = cols.index('CLOSE')
    row = data[0]
    if row[op_idx] is None or row[cl_idx] is None:
        return None
    return float(row[op_idx]), float(row[cl_idx])


def fetch_finam_one_day(ticker: str, date: str) -> tuple[float, float] | None:
    """Возвращает (open, close) из локального Finam-файла на дату."""
    iso = date.replace('-', '')
    pattern = str(STOCKS_DIR / f'{ticker}_*_1day_*.txt')
    files = glob.glob(pattern)
    if not files:
        return None
    path = files[0]
    with open(path, 'r', encoding='utf-8') as fh:
        next(fh)  # заголовок
        for line in fh:
            parts = line.strip().split(';')
            if len(parts) < 10:
                continue
            d = parts[2]
            if d != iso:
                continue
            try:
                return float(parts[4]), float(parts[7])  # OPEN, CLOSE
            except ValueError:
                return None
    return None


def main() -> None:
    ok = 0
    skip = 0
    fail = 0
    for ticker in TICKERS:
        for date in DATES:
            finam = fetch_finam_one_day(ticker, date)
            iss = fetch_iss_one_day(ticker, date)
            time.sleep(0.1)
            if finam is None and iss is None:
                skip += 1
                continue
            if finam is None:
                print(f'  SKIP {ticker} {date}: нет в Finam')
                skip += 1
                continue
            if iss is None:
                print(f'  SKIP {ticker} {date}: нет в ISS')
                skip += 1
                continue
            fopen, fclose = finam
            iopen, iclose = iss
            open_diff = abs(fopen - iopen) / fopen
            close_diff = abs(fclose - iclose) / fclose
            if open_diff > TOLERANCE_PCT or close_diff > TOLERANCE_PCT:
                print(
                    f'  FAIL {ticker} {date} | '
                    f'open Finam={fopen} ISS={iopen} ({open_diff:.2%}) | '
                    f'close Finam={fclose} ISS={iclose} ({close_diff:.2%})'
                )
                fail += 1
            else:
                ok += 1

    print()
    print(f'OK   : {ok}')
    print(f'SKIP : {skip}')
    print(f'FAIL : {fail}')
    if fail:
        print('\nРасхождение — стоп. Реализация load_moex_stocks.py заблокирована.')
        sys.exit(1)
    print('\nCross-validation прошёл. Можно реализовывать load_moex_stocks.py.')


if __name__ == '__main__':
    main()
