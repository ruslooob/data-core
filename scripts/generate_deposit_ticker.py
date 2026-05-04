# -*- coding: utf-8 -*-
"""Генератор псевдо-тикера `DEPOSIT_RUONIA` для использования депозита в
стратегиях бэктеста как обычного актива.

Идея: депозит — это «акция» с фиксированной начальной ценой (1000 ₽),
которая каждый торговый день дорожает на дневную долю безрисковой ставки
RUONIA. Никакой отдельной механики начисления процентов в движке не нужно —
страт. правило `buy DEPOSIT_RUONIA` кладёт деньги «на ставку», правило
`sell DEPOSIT_RUONIA` снимает их, а между этими событиями переоценка equity
автоматически отражает рост цены актива.

Цена на торговый день t:
    price[0] = 1000
    price[t] = price[t-1] * (1 + daily_ruonia[t-1])

То есть «акция» куплена в начале t-го дня по цене price[t]; за день она
вырастет в долгу с накопленным процентом, и завтрашняя цена (t+1) уже
будет выше.

Запуск (один раз; файл идемпотентен — перезаписывает результат):
    python scripts/generate_deposit_ticker.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Подготовим импорт core.* — скрипт лежит в scripts/, движок в backend/.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import numpy as np
import pandas as pd

from core.market_data_provider import MarketDataProvider

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OUTPUT_DIR = ROOT / 'data' / 'stocks'
TICKER = 'DEPOSIT_RUONIA'
START_PRICE = 1000.0


def _build_price_series() -> pd.Series:
    market = MarketDataProvider()
    # Календарь — торговые дни IMOEX.
    imoex = market.load_market_index_prices()
    trading_dates = imoex.index

    daily_rf = market.load_daily_risk_free_rate()
    daily_rf = daily_rf.reindex(trading_dates, method='ffill').fillna(0.0)

    prices = np.empty(len(trading_dates), dtype=np.float64)
    price = START_PRICE
    for i, rate in enumerate(daily_rf.values):
        prices[i] = price
        price *= 1.0 + float(rate)
    return pd.Series(prices, index=trading_dates, name='CLOSE')


def _format_filename(start: pd.Timestamp, end: pd.Timestamp) -> str:
    return f'{TICKER}_RUONIA_1day_{start.strftime("%Y%m%d")}_{end.strftime("%Y%m%d")}.txt'


def _write_file(prices: pd.Series, path: Path) -> None:
    """Формат, ожидаемый StockDataProvider: <TICKER>;<PER>;<DATE>;<TIME>;<O>;<H>;<L>;<C>;<V>;<OPENINT>"""
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>\n')
        for date, close in prices.items():
            d = date.strftime('%Y%m%d')
            # OPEN=HIGH=LOW=CLOSE — депозит не торгуется, у него нет внутридневного спрэда.
            line = f'{TICKER};D;{d};000000;{close:.6f};{close:.6f};{close:.6f};{close:.6f};0;0\n'
            f.write(line)


def main() -> int:
    if not OUTPUT_DIR.exists():
        print(f'Папка {OUTPUT_DIR} не найдена.')
        return 1

    print(f'Генерирую псевдо-тикер {TICKER} от RUONIA, стартовая цена {START_PRICE}…')
    prices = _build_price_series()
    if prices.empty:
        print('Пустой ряд. Проверь, что MarketDataProvider возвращает RUONIA.')
        return 1

    start, end = prices.index[0], prices.index[-1]
    filename = _format_filename(start, end)
    out_path = OUTPUT_DIR / filename

    # Удаляем старые версии этого тикера (с другим диапазоном дат), чтобы не плодить дубли.
    for old in OUTPUT_DIR.glob(f'{TICKER}_*.txt'):
        if old.name != filename:
            old.unlink()
            print(f'  убран старый файл: {old.name}')

    _write_file(prices, out_path)
    print(f'  записан {out_path.name}: {len(prices)} строк')
    print(f'  цена в {start.date()}: {prices.iloc[0]:.4f}')
    print(f'  цена в {end.date()}:   {prices.iloc[-1]:.4f}')
    total_return = prices.iloc[-1] / prices.iloc[0] - 1.0
    years = (end - start).days / 365.25
    print(f'  итоговая доходность: {total_return * 100:.2f}% за {years:.1f} лет')
    return 0


if __name__ == '__main__':
    sys.exit(main())
