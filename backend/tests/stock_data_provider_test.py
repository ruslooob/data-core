"""Тесты StockDataProvider после миграции с CSV на Postgres.

Используем живой тикер LKOH (всегда присутствует в БД, длинная история).
Конкретные торговые/нерабочие даты выбраны из заведомо известного
диапазона: 2022-12-16 — пятница (торговый день), 2022-12-17 — суббота
(биржа закрыта). max_date проверяется по факту: ряд не должен
выходить за установленный потолок.

Удалены тесты, устаревшие концептуально:
- raw vs normalized сравнения (в Postgres котировки уже нормализованы
  при загрузке, параметр normalized=False игнорируется).
- TEST_SPLIT-фикстура (CSV-файлы и splits.json больше не источник).
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.stock_data_provider import StockDataProvider

TICKER = 'LKOH'
EXPECTED_COLUMNS = ['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL']
TRADING_DAY = '2022-12-16'  # пятница
WEEKEND_DAY = '2022-12-17'  # суббота


@pytest.fixture
def provider() -> StockDataProvider:
    return StockDataProvider()


# === Happy path ===

def test_returns_expected_columns(provider):
    df = provider.get_candles(TICKER)
    assert list(df.columns) == EXPECTED_COLUMNS


def test_returns_expected_dtypes(provider):
    df = provider.get_candles(TICKER)
    assert pd.api.types.is_datetime64_any_dtype(df['DATE'])
    for col in ['OPEN', 'HIGH', 'LOW', 'CLOSE']:
        assert pd.api.types.is_float_dtype(df[col])
    assert pd.api.types.is_numeric_dtype(df['VOL'])


def test_rows_sorted_by_date(provider):
    df = provider.get_candles(TICKER)
    assert df['DATE'].is_monotonic_increasing


def test_has_sequential_index(provider):
    df = provider.get_candles(TICKER)
    assert list(df.index) == list(range(len(df)))


# === Регистр тикера ===

@pytest.mark.parametrize('ticker', ['lkoh', 'LKOH', 'LkOh'])
def test_ticker_is_case_insensitive(provider, ticker):
    df = provider.get_candles(ticker)
    assert len(df) > 0


# === Границы дат ===

def test_start_date_is_inclusive(provider):
    df = provider.get_candles(TICKER, start_date=TRADING_DAY)
    assert df.iloc[0]['DATE'] == pd.Timestamp(TRADING_DAY)


def test_end_date_is_inclusive(provider):
    df = provider.get_candles(TICKER, start_date='2022-12-01', end_date=TRADING_DAY)
    assert df.iloc[-1]['DATE'] == pd.Timestamp(TRADING_DAY)


def test_single_day_on_trading_day_returns_one_row(provider):
    df = provider.get_candles(TICKER, start_date=TRADING_DAY, end_date=TRADING_DAY)
    assert len(df) == 1
    assert df.iloc[0]['DATE'] == pd.Timestamp(TRADING_DAY)


def test_single_day_on_weekend_returns_empty_with_columns(provider):
    df = provider.get_candles(TICKER, start_date=WEEKEND_DAY, end_date=WEEKEND_DAY)
    assert len(df) == 0
    assert list(df.columns) == EXPECTED_COLUMNS


def test_range_outside_data_returns_empty_with_columns(provider):
    df = provider.get_candles(TICKER, start_date='2099-01-01', end_date='2099-12-31')
    assert len(df) == 0
    assert list(df.columns) == EXPECTED_COLUMNS


def test_only_start_date_keeps_tail(provider):
    df = provider.get_candles(TICKER, start_date=TRADING_DAY)
    assert df.iloc[0]['DATE'] == pd.Timestamp(TRADING_DAY)


def test_only_end_date_keeps_head(provider):
    df = provider.get_candles(TICKER, end_date='2002-12-31')
    assert len(df) > 0
    assert df.iloc[-1]['DATE'] <= pd.Timestamp('2002-12-31')


# === Ошибки ===

def test_start_after_end_raises_value_error(provider):
    with pytest.raises(ValueError):
        provider.get_candles(TICKER, start_date='2020-01-10', end_date='2020-01-05')


def test_unknown_ticker_raises_value_error(provider):
    with pytest.raises(ValueError):
        provider.get_candles('NOTAREAL')


def test_invalid_start_date_raises_value_error(provider):
    with pytest.raises(ValueError):
        provider.get_candles(TICKER, start_date='not-a-date')


def test_invalid_end_date_raises_value_error(provider):
    with pytest.raises(ValueError):
        provider.get_candles(TICKER, end_date='2020-13-45')


# === max_date ===

def test_max_date_caps_end_of_series():
    p = StockDataProvider(max_date=pd.Timestamp(TRADING_DAY).date())
    df = p.get_candles(TICKER)
    assert df['DATE'].max() <= pd.Timestamp(TRADING_DAY)


def test_max_date_takes_priority_over_end_date_if_stricter():
    p = StockDataProvider(max_date=pd.Timestamp(TRADING_DAY).date())
    df = p.get_candles(TICKER, end_date='2025-01-01')
    assert df['DATE'].max() <= pd.Timestamp(TRADING_DAY)
