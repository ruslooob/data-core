import os

import pandas as pd
import pytest

from core import stock_data_provider

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'stocks')
EXPECTED_COLUMNS = ['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL']


@pytest.fixture(autouse=True)
def patch_stock_paths(monkeypatch):
    monkeypatch.setattr(stock_data_provider, 'STOCKS_FOLDER', FIXTURES_DIR)
    monkeypatch.setattr(
        stock_data_provider, '_SPLITS_PATH',
        os.path.join(FIXTURES_DIR, 'splits.json'),
    )


# === Happy path ===

def test_returns_expected_columns():
    df = stock_data_provider.get_candles('TEST', normalized=False)
    assert list(df.columns) == EXPECTED_COLUMNS


def test_returns_expected_dtypes():
    df = stock_data_provider.get_candles('TEST', normalized=False)
    assert pd.api.types.is_datetime64_any_dtype(df['DATE'])
    for col in ['OPEN', 'HIGH', 'LOW', 'CLOSE']:
        assert pd.api.types.is_float_dtype(df[col])
    assert pd.api.types.is_numeric_dtype(df['VOL'])


def test_rows_sorted_by_date():
    df = stock_data_provider.get_candles('TEST', normalized=False)
    assert df['DATE'].is_monotonic_increasing


def test_has_sequential_index():
    df = stock_data_provider.get_candles('TEST', normalized=False)
    assert list(df.index) == list(range(len(df)))


# === Регистр тикера ===

@pytest.mark.parametrize('ticker', ['test', 'TEST', 'TeSt'])
def test_ticker_is_case_insensitive(ticker):
    df = stock_data_provider.get_candles(ticker, normalized=False)
    assert len(df) == 10


# === Границы дат ===

def test_start_date_is_inclusive():
    df = stock_data_provider.get_candles('TEST', normalized=False, start_date='2020-01-02')
    assert df.iloc[0]['DATE'] == pd.Timestamp('2020-01-02')


def test_end_date_is_inclusive():
    df = stock_data_provider.get_candles('TEST', normalized=False, end_date='2020-01-15')
    assert df.iloc[-1]['DATE'] == pd.Timestamp('2020-01-15')


def test_single_day_on_trading_day_returns_one_row():
    df = stock_data_provider.get_candles(
        'TEST', normalized=False, start_date='2020-01-06', end_date='2020-01-06',
    )
    assert len(df) == 1
    assert df.iloc[0]['DATE'] == pd.Timestamp('2020-01-06')


def test_single_day_on_weekend_returns_empty_with_columns():
    # 2020-01-04 — суббота (нет в фикстуре)
    df = stock_data_provider.get_candles(
        'TEST', normalized=False, start_date='2020-01-04', end_date='2020-01-04',
    )
    assert len(df) == 0
    assert list(df.columns) == EXPECTED_COLUMNS


def test_range_outside_data_returns_empty_with_columns():
    df = stock_data_provider.get_candles(
        'TEST', normalized=False, start_date='2025-01-01', end_date='2025-12-31',
    )
    assert len(df) == 0
    assert list(df.columns) == EXPECTED_COLUMNS


def test_only_start_date_keeps_tail():
    df = stock_data_provider.get_candles('TEST', normalized=False, start_date='2020-01-10')
    assert df.iloc[0]['DATE'] == pd.Timestamp('2020-01-10')
    assert df.iloc[-1]['DATE'] == pd.Timestamp('2020-01-15')


def test_only_end_date_keeps_head():
    df = stock_data_provider.get_candles('TEST', normalized=False, end_date='2020-01-07')
    assert df.iloc[0]['DATE'] == pd.Timestamp('2020-01-02')
    assert df.iloc[-1]['DATE'] == pd.Timestamp('2020-01-07')


# === Ошибки ===

def test_start_after_end_raises_value_error():
    with pytest.raises(ValueError):
        stock_data_provider.get_candles(
            'TEST', normalized=False, start_date='2020-01-10', end_date='2020-01-05',
        )


def test_unknown_ticker_raises_value_error():
    with pytest.raises(ValueError):
        stock_data_provider.get_candles('NOTAREAL', normalized=False)


def test_invalid_start_date_raises_value_error():
    with pytest.raises(ValueError):
        stock_data_provider.get_candles('TEST', normalized=False, start_date='not-a-date')


def test_invalid_end_date_raises_value_error():
    with pytest.raises(ValueError):
        stock_data_provider.get_candles('TEST', normalized=False, end_date='2020-13-45')


# === Сплиты ===

def test_raw_prices_differ_before_and_after_split():
    df = stock_data_provider.get_candles('TEST_SPLIT', normalized=False)
    pre = df[df['DATE'] < pd.Timestamp('2020-01-08')]
    post = df[df['DATE'] >= pd.Timestamp('2020-01-08')]
    assert (pre['CLOSE'] == 100.0).all()
    assert (post['CLOSE'] == 50.0).all()
    assert (pre['VOL'] == 1000).all()
    assert (post['VOL'] == 2000).all()


def test_normalized_prices_are_uniform_across_split():
    df = stock_data_provider.get_candles('TEST_SPLIT', normalized=True)
    for col in ['OPEN', 'HIGH', 'LOW', 'CLOSE']:
        assert (df[col] == 50.0).all()
    assert (df['VOL'] == 2000.0).all()
