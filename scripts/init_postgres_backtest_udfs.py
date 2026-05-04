"""TA-функции бэктест-движка как PL/Python-UDF в Postgres.

Зависимость от max_date — через session-GUC `backtest.max_date` (имя
namespaced, Postgres допускает SET для таких без предварительного
определения). Backend перед каждым тиком делает
`SET LOCAL backtest.max_date = '<YYYY-MM-DD>'`. Если GUC пустой,
функции работают с полной историей.

Кэш данных тикера лежит в SD (per-session). Ключ — (ticker, max_date).
Один и тот же max_date в рамках сессии = один заглядывание в БД на
тикер; смена max_date при переходе к следующему тику — новый ключ,
старый кэш живёт в SD до конца сессии.

Функции:
- close_price(ticker, d)        — последняя цена ≤ d (forward-fill).
- open_price(ticker, d)         — строгое равенство, NULL если торгов не было.
- volume(ticker, d)             — строгое равенство.
- sma(ticker, d, w)             — среднее close за `w` дней СТРОГО ДО `d`.
- volume_sma(ticker, d, w)      — то же для volume.
- volatility(ticker, d, w)      — std дневных лог-доходностей за `w` дней до `d`.
- return_n_days(ticker, d, n)   — exp(Σ log_ret) − 1 за n дней до d.
- avg_price(ticker)             — средняя buy_price из portfolio_positions
                                  (TEMP TABLE текущей сессии).

Идемпотентен: CREATE OR REPLACE.
"""
from __future__ import annotations

import psycopg

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'


# Общий хелпер-блок, инжектируемый в каждый UDF: подгружает котировки
# в SD-кэш с учётом backtest.max_date и возвращает DataFrame (или None).
_CANDLES_LOADER = r"""
def _candles_for(ticker_u):
    # max_date из session-GUC: SHOW backtest.max_date вернёт строку
    # 'YYYY-MM-DD' или пустую '' если не выставлен.
    try:
        rows = plpy.execute("SHOW backtest.max_date")
        mx = rows[0]['backtest.max_date'] or ''
    except Exception:
        mx = ''
    cache_key = ('cdl', ticker_u, mx)
    if cache_key in SD:
        return SD[cache_key]
    if mx:
        plan = plpy.prepare(
            'SELECT candle_date, open, high, low, close, volume '
            'FROM stock_candles WHERE ticker = $1 AND candle_date <= $2 '
            'ORDER BY candle_date',
            ['varchar', 'date'],
        )
        rows = plpy.execute(plan, [ticker_u, mx])
    else:
        plan = plpy.prepare(
            'SELECT candle_date, open, high, low, close, volume '
            'FROM stock_candles WHERE ticker = $1 ORDER BY candle_date',
            ['varchar'],
        )
        rows = plpy.execute(plan, [ticker_u])
    if len(rows) < 1:
        SD[cache_key] = None
        return None
    import pandas as pd
    dates = pd.DatetimeIndex([r['candle_date'] for r in rows])
    df = pd.DataFrame({
        'open': [r['open'] for r in rows],
        'high': [r['high'] for r in rows],
        'low': [r['low'] for r in rows],
        'close': [r['close'] for r in rows],
        'volume': [r['volume'] for r in rows],
    }, index=dates)
    SD[cache_key] = df
    return df
"""


SQL_CLOSE_PRICE = r"""
CREATE OR REPLACE FUNCTION close_price(ticker VARCHAR, d DATE)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd
if ticker is None or d is None:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
target = pd.Timestamp(d)
filtered = df[df.index <= target]
if filtered.empty:
    return None
return float(filtered['close'].iloc[-1])
$$;
"""

SQL_OPEN_PRICE = r"""
CREATE OR REPLACE FUNCTION open_price(ticker VARCHAR, d DATE)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd
if ticker is None or d is None:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
target = pd.Timestamp(d)
if target not in df.index:
    return None
return float(df.loc[target, 'open'])
$$;
"""

SQL_VOLUME = r"""
CREATE OR REPLACE FUNCTION volume(ticker VARCHAR, d DATE)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd
if ticker is None or d is None:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
target = pd.Timestamp(d)
if target not in df.index:
    return None
v = df.loc[target, 'volume']
if v is None:
    return None
return float(v)
$$;
"""

SQL_SMA = r"""
CREATE OR REPLACE FUNCTION sma(ticker VARCHAR, d DATE, w INTEGER)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd
if ticker is None or d is None or w is None or int(w) <= 0:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
target = pd.Timestamp(d)
filtered = df[df.index < target].tail(int(w))
if len(filtered) < int(w):
    return None
return float(filtered['close'].mean())
$$;
"""

SQL_VOLUME_SMA = r"""
CREATE OR REPLACE FUNCTION volume_sma(ticker VARCHAR, d DATE, w INTEGER)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd
if ticker is None or d is None or w is None or int(w) <= 0:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
target = pd.Timestamp(d)
filtered = df[df.index < target].tail(int(w))
if len(filtered) < int(w):
    return None
return float(filtered['volume'].mean())
$$;
"""

SQL_VOLATILITY = r"""
CREATE OR REPLACE FUNCTION volatility(ticker VARCHAR, d DATE, w INTEGER)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import numpy as np
import pandas as pd
if ticker is None or d is None or w is None or int(w) <= 1:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
prices = df['close']
log_ret = np.log(prices / prices.shift(1)).dropna()
target = pd.Timestamp(d)
filtered = log_ret[log_ret.index < target].tail(int(w))
if len(filtered) < int(w):
    return None
return float(filtered.std(ddof=1))
$$;
"""

SQL_RETURN_N_DAYS = r"""
CREATE OR REPLACE FUNCTION return_n_days(ticker VARCHAR, d DATE, n INTEGER)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import math
import numpy as np
import pandas as pd
if ticker is None or d is None or n is None or int(n) <= 0:
    return None
ticker_u = ticker.upper()
""" + _CANDLES_LOADER + r"""
df = _candles_for(ticker_u)
if df is None or df.empty:
    return None
prices = df['close']
log_ret = np.log(prices / prices.shift(1)).dropna()
target = pd.Timestamp(d)
filtered = log_ret[log_ret.index < target].tail(int(n))
if len(filtered) < int(n):
    return None
return float(math.exp(filtered.sum()) - 1.0)
$$;
"""

SQL_AVG_PRICE = r"""
CREATE OR REPLACE FUNCTION avg_price(ticker VARCHAR)
RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
if ticker is None:
    return None
ticker_u = ticker.upper()
plan = plpy.prepare(
    "SELECT SUM(quantity * buy_price) / NULLIF(SUM(quantity), 0) AS avg "
    "FROM portfolio_positions WHERE ticker = $1",
    ['varchar'],
)
rows = plpy.execute(plan, [ticker_u])
if not rows:
    return None
v = rows[0]['avg']
if v is None:
    return None
return float(v)
$$;
"""


def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=True)
    try:
        with pg.cursor() as cur:
            for name, sql in [
                ('close_price', SQL_CLOSE_PRICE),
                ('open_price', SQL_OPEN_PRICE),
                ('volume', SQL_VOLUME),
                ('sma', SQL_SMA),
                ('volume_sma', SQL_VOLUME_SMA),
                ('volatility', SQL_VOLATILITY),
                ('return_n_days', SQL_RETURN_N_DAYS),
                ('avg_price', SQL_AVG_PRICE),
            ]:
                cur.execute(sql)
                print(f'  {name}: OK')
    finally:
        pg.close()


if __name__ == '__main__':
    main()
