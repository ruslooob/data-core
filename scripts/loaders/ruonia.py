"""Лоадер: безрисковая ставка RUONIA из xlsx-дампа ЦБ.

Только `load(pg)`: исходный xlsx `data/stocks/RUONIA_*.xlsx` сейчас
лежит руками — выгрузка с cbr.ru пока не автоматизирована. TODO
добавить `fetch()`, тянущий с открытой страницы статистики ЦБ
(`https://cbr.ru/hd_base/ruonia/`), когда дойдут руки.

`load(pg)` читает первый найденный `RUONIA_*.xlsx`, лист `RC`,
колонки `DT` и `ruo`, льёт в таблицу `risk_free_rate` с
ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import os
import sys
from glob import glob

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STOCKS_DIR = os.path.join(ROOT, 'data', 'stocks')


def load(pg) -> None:
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


if __name__ == '__main__':
    import psycopg

    pg_dsn = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
    with psycopg.connect(pg_dsn) as pg:
        load(pg)
        pg.commit()
