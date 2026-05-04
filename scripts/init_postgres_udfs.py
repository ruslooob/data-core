"""Регистрация PL/Python-UDF для PQL: car, vol_ratio, volume_ratio.

Создаёт три функции в Postgres:
- `car(ticker, event_date, model, window_before, window_after, estimation,
       outlier_threshold, max_date)` — CAR через EventStudy.
- `vol_ratio(ticker, event_date, window_before, window_after, max_date)` —
  отношение волатильностей до/после события.
- `volume_ratio(ticker, event_date, window_before, window_after, max_date)` —
  отношение средних объёмов после/до.

Все три имеют параметры со значениями по умолчанию, поэтому в SQL можно
звать `car('LKOH', '2022-12-16')` или `car('LKOH', '2022-12-16', 'capm', 5, 5, 200, NULL, '2025-09-05')`.

`max_date` — последняя видимая дата (включительно); используется бэктестом
для no-lookahead. NULL = вся история.

Тело UDF — самодостаточное (не зависит от backend-кода): читает котировки
и RUONIA через plpy.execute, реализует MeanAdjusted/Market/CAPM модели и
EventStudy.analyze inline. Это сделано чтобы не монтировать backend-код
в контейнер Postgres.

Идемпотентен: CREATE OR REPLACE.

Запуск:
    python scripts/init_postgres_udfs.py
"""
from __future__ import annotations

import psycopg

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'


SQL_CAR_IMPL = r"""
CREATE OR REPLACE FUNCTION car(
    ticker            VARCHAR,
    event_date        DATE,
    model             VARCHAR        DEFAULT 'market_model',
    window_before     INTEGER        DEFAULT 5,
    window_after      INTEGER        DEFAULT 5,
    estimation        INTEGER        DEFAULT 200,
    outlier_threshold DOUBLE PRECISION DEFAULT NULL,
    max_date          DATE           DEFAULT NULL
) RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import numpy as np
import pandas as pd

if ticker is None or event_date is None:
    return None

ticker_u = ticker.upper()

# ── Кэш log_returns в SD (per-session, общий для всех вызовов UDF) ──
# Ключ зависит от max_date: разные max_date — разные ряды.
def _log_returns_for(t, mx):
    cache_key = ('lr', t, mx)
    if cache_key in SD:
        return SD[cache_key]
    if mx is not None:
        plan = plpy.prepare(
            'SELECT candle_date, close FROM stock_candles '
            'WHERE ticker = $1 AND candle_date <= $2 ORDER BY candle_date',
            ['varchar', 'date'],
        )
        rows = plpy.execute(plan, [t, mx])
    else:
        plan = plpy.prepare(
            'SELECT candle_date, close FROM stock_candles '
            'WHERE ticker = $1 ORDER BY candle_date',
            ['varchar'],
        )
        rows = plpy.execute(plan, [t])
    if len(rows) < 2:
        SD[cache_key] = None
        return None
    dates = pd.DatetimeIndex([r['candle_date'] for r in rows])
    closes = pd.Series([float(r['close']) for r in rows], index=dates)
    lr = np.log(closes / closes.shift(1)).dropna()
    if len(lr) < 2:
        SD[cache_key] = None
        return None
    lr.index.name = 'date'
    SD[cache_key] = lr
    return lr

def _rf_for(mx):
    cache_key = ('rf', mx)
    if cache_key in SD:
        return SD[cache_key]
    if mx is not None:
        plan = plpy.prepare(
            'SELECT rate_date, annual_rate_pct FROM risk_free_rate '
            'WHERE rate_date <= $1 ORDER BY rate_date',
            ['date'],
        )
        rows = plpy.execute(plan, [mx])
    else:
        plan = plpy.prepare(
            'SELECT rate_date, annual_rate_pct FROM risk_free_rate ORDER BY rate_date',
            [],
        )
        rows = plpy.execute(plan, [])
    if len(rows) < 1:
        SD[cache_key] = None
        return None
    ridx = pd.DatetimeIndex([r['rate_date'] for r in rows])
    rf_annual = pd.Series([float(r['annual_rate_pct']) for r in rows], index=ridx)
    rf = rf_annual / 100.0 / 252.0
    rf.index.name = 'date'
    SD[cache_key] = rf
    return rf

stock_lr = _log_returns_for(ticker_u, max_date)
if stock_lr is None:
    return None

needs_market = model in ('market_model', 'capm')
needs_rf = model == 'capm'

mkt_lr = _log_returns_for('IMOEX', max_date) if needs_market else None
if needs_market and mkt_lr is None:
    return None
rf_lr = _rf_for(max_date) if needs_rf else None
if needs_rf and rf_lr is None:
    return None

# ── Окна оценки и события (event_study._resolve_windows эквивалент) ──
trading_days = stock_lr.index.sort_values()
t0 = pd.Timestamp(event_date)
ew_start = -int(window_before)
ew_end = int(window_after)
esw = int(estimation)

idx0 = trading_days.searchsorted(t0, side='left')
if idx0 >= len(trading_days):
    return None
est_end_pos = idx0 + ew_start - 1
est_start_pos = est_end_pos - esw + 1
if est_start_pos < 0 or est_end_pos < 0:
    return None
est_idx = trading_days[est_start_pos: est_end_pos + 1]
if len(est_idx) < esw // 2:
    return None
ev_start_pos = idx0 + ew_start
ev_end_pos = idx0 + ew_end
if ev_start_pos < 0 or ev_end_pos >= len(trading_days):
    return None
ev_idx = trading_days[max(ev_start_pos, 0): ev_end_pos + 1]
if len(ev_idx) == 0:
    return None

# ── align series ──
def _align(idx):
    s = stock_lr.reindex(idx).dropna()
    m = mkt_lr.reindex(idx).ffill().fillna(0.0) if mkt_lr is not None else pd.Series(0.0, index=idx)
    r = rf_lr.reindex(idx).ffill().fillna(0.0) if rf_lr is not None else pd.Series(0.0, index=idx)
    return s, m, r

stock_est, mkt_est, rf_est = _align(est_idx)
if len(stock_est) < 10:
    return None
common_est = stock_est.index.intersection(mkt_est.index).intersection(rf_est.index)
stock_est = stock_est.reindex(common_est)
mkt_est = mkt_est.reindex(common_est)
rf_est = rf_est.reindex(common_est)

# ── модели ──
def _fit_predict(model, s_est, m_est, r_est, m_pred, r_pred, idx_pred):
    if model == 'mean_adjusted':
        mu = float(s_est.mean())
        return pd.Series(mu, index=idx_pred)
    elif model == 'market_model':
        beta, alpha = np.polyfit(m_est.values, s_est.values, 1)
        return pd.Series(float(alpha) + float(beta) * m_pred.values, index=idx_pred)
    elif model == 'capm':
        excess_s = s_est.values - r_est.values
        excess_m = m_est.values - r_est.values
        denom = float(np.dot(excess_m, excess_m))
        beta = float(np.dot(excess_m, excess_s) / denom) if denom != 0.0 else 1.0
        rf = r_pred.values; rm = m_pred.values
        return pd.Series(rf + beta * (rm - rf), index=idx_pred)
    raise ValueError(f'unknown model: {model}')

# ── фильтр выбросов ──
if outlier_threshold is not None and outlier_threshold > 0:
    expected_pre = _fit_predict(model, stock_est, mkt_est, rf_est, mkt_est, rf_est, common_est)
    residuals_pre = stock_est.values - expected_pre.values
    sigma_pre = float(np.std(residuals_pre, ddof=1)) if len(residuals_pre) > 1 else 0.0
    if sigma_pre > 0:
        mask = np.abs(residuals_pre) <= outlier_threshold * sigma_pre
        if int(np.sum(~mask)) > 0 and int(np.sum(mask)) >= 10:
            common_est = common_est[mask]
            stock_est = stock_est.reindex(common_est)
            mkt_est = mkt_est.reindex(common_est)
            rf_est = rf_est.reindex(common_est)

# ── окно события ──
stock_ev = stock_lr.reindex(ev_idx).fillna(0.0)
mkt_ev = mkt_lr.reindex(ev_idx).ffill().fillna(0.0) if mkt_lr is not None else pd.Series(0.0, index=ev_idx)
rf_ev = rf_lr.reindex(ev_idx).ffill().fillna(0.0) if rf_lr is not None else pd.Series(0.0, index=ev_idx)
expected_ev = _fit_predict(model, stock_est, mkt_est, rf_est, mkt_ev, rf_ev, ev_idx)

ar = stock_ev.values - expected_ev.values
return float(np.sum(ar))
$$;
"""

SQL_VOL_RATIO = r"""
CREATE OR REPLACE FUNCTION vol_ratio(
    ticker        VARCHAR,
    event_date    DATE,
    window_before INTEGER DEFAULT 5,
    window_after  INTEGER DEFAULT 5,
    max_date      DATE    DEFAULT NULL
) RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import numpy as np
import pandas as pd

if ticker is None or event_date is None:
    return None

ticker_u = ticker.upper()
cache_key = ('lr', ticker_u, max_date)
log_ret = SD.get(cache_key)
if log_ret is None and cache_key not in SD:
    if max_date is not None:
        plan = plpy.prepare(
            'SELECT candle_date, close FROM stock_candles '
            'WHERE ticker = $1 AND candle_date <= $2 ORDER BY candle_date',
            ['varchar', 'date'],
        )
        rows = plpy.execute(plan, [ticker_u, max_date])
    else:
        plan = plpy.prepare(
            'SELECT candle_date, close FROM stock_candles '
            'WHERE ticker = $1 ORDER BY candle_date',
            ['varchar'],
        )
        rows = plpy.execute(plan, [ticker_u])
    if len(rows) >= 2:
        dates = pd.DatetimeIndex([r['candle_date'] for r in rows])
        closes = pd.Series([float(r['close']) for r in rows], index=dates)
        lr = np.log(closes / closes.shift(1)).dropna()
        log_ret = lr if not lr.empty else None
        if log_ret is not None:
            log_ret.index.name = 'date'
    SD[cache_key] = log_ret

if log_ret is None or log_ret.empty:
    return None

t0 = pd.Timestamp(event_date)
trading = log_ret.index
idx0 = trading.searchsorted(t0, side='left')
if idx0 >= len(trading):
    return None
pre_start = idx0 - int(window_before)
pre_end = idx0
post_start = idx0 + 1
post_end = idx0 + 1 + int(window_after)
if pre_start < 0 or post_end > len(trading):
    return None
pre = log_ret.iloc[pre_start:pre_end]
post = log_ret.iloc[post_start:post_end]
if len(pre) < 2 or len(post) < 2:
    return None
pre_std = float(pre.std(ddof=1))
if pre_std == 0:
    return None
return float(post.std(ddof=1)) / pre_std
$$;
"""

SQL_VOLUME_RATIO = r"""
CREATE OR REPLACE FUNCTION volume_ratio(
    ticker        VARCHAR,
    event_date    DATE,
    window_before INTEGER DEFAULT 5,
    window_after  INTEGER DEFAULT 5,
    max_date      DATE    DEFAULT NULL
) RETURNS DOUBLE PRECISION LANGUAGE plpython3u AS $$
import pandas as pd

if ticker is None or event_date is None:
    return None

ticker_u = ticker.upper()
cache_key = ('vol', ticker_u, max_date)
vols = SD.get(cache_key)
if vols is None and cache_key not in SD:
    if max_date is not None:
        plan = plpy.prepare(
            'SELECT candle_date, volume FROM stock_candles '
            'WHERE ticker = $1 AND candle_date <= $2 ORDER BY candle_date',
            ['varchar', 'date'],
        )
        rows = plpy.execute(plan, [ticker_u, max_date])
    else:
        plan = plpy.prepare(
            'SELECT candle_date, volume FROM stock_candles '
            'WHERE ticker = $1 ORDER BY candle_date',
            ['varchar'],
        )
        rows = plpy.execute(plan, [ticker_u])
    if len(rows) >= 1:
        dates = pd.DatetimeIndex([r['candle_date'] for r in rows])
        vols = pd.Series([float(r['volume'] or 0.0) for r in rows], index=dates)
    SD[cache_key] = vols

if vols is None or vols.empty:
    return None

t0 = pd.Timestamp(event_date)
trading = vols.index
idx0 = trading.searchsorted(t0, side='left')
if idx0 >= len(trading):
    return None
pre_start = idx0 - int(window_before)
pre_end = idx0
post_start = idx0 + 1
post_end = idx0 + 1 + int(window_after)
if pre_start < 0 or post_end > len(trading):
    return None
pre = vols.iloc[pre_start:pre_end]
post = vols.iloc[post_start:post_end]
if len(pre) < 1 or len(post) < 1:
    return None
pre_mean = float(pre.mean())
if pre_mean == 0:
    return None
return float(post.mean()) / pre_mean
$$;
"""


def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=True)
    try:
        with pg.cursor() as cur:
            cur.execute(SQL_CAR_IMPL)
            cur.execute(SQL_VOL_RATIO)
            cur.execute(SQL_VOLUME_RATIO)
            print('UDFs created')
    finally:
        pg.close()


if __name__ == '__main__':
    main()
