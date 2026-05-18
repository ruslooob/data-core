"""Рисует три картинки event study для LKOH × объявление дивидендов 22.03.2024.

По одной картинке на каждую модель ожидаемой доходности (mean_adjusted,
market_model, capm). На графике:
- ось X — даты (короткий русский формат "15 мар", "22 мар", ...);
- ось Y — цена закрытия в рублях;
- фактическая цена LKOH (сплошная линия);
- прогнозная цена по модели на оценочном хвосте (cumulative от первой
  точки хвоста; даёт характерный «след» модели — экспонента для
  mean_adjusted, рыночный тренд для market_model/CAPM);
- прогнозная цена в окне события (cumulative от факта последнего дня
  оценочного окна — это «прогноз вперёд»);
- фон оценочного окна — голубоватый, фон окна события — розовый;
- вертикальная линия с подписью на дате объявления дивидендов;
- AR-стрелочки от прогнозной к фактической цене на каждом дне окна
  события (с подписями на 5 опорных точках).

После прогона удалить отдельным коммитом.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.dates import num2date
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
import psycopg

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
from core.event_study import EventStudy  # noqa: E402,F401  (для будущих расширений)
from core.expected_return_models import (  # noqa: E402
    MeanAdjustedModel, MarketModel, CAPMModel,
)

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
TICKER = 'LKOH'
EVENT_WINDOW = 5
ESTIMATION_WINDOW = 200
EST_TAIL_DAYS = 20
OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'docs' / 'research' / 'figures'

# 10 крупнейших объявлений дивидендов LKOH разных периодов — пользователь
# выберет лучшие 1-2 примера для презентации защиты.
# Метаданные (размер дивиденда, год) подгружаются из events.payload.
EVENT_DATES = [
    date(2020,  5, 18),
    date(2021, 10, 13),
    date(2022, 10, 28),
    date(2022, 11,  2),
    date(2023,  4, 20),
    date(2023, 10, 26),
    date(2024,  3, 22),
    date(2024, 10, 25),
    date(2025,  3, 25),
    date(2025, 11, 21),
]

MODELS = [
    ('mean_adjusted', MeanAdjustedModel, 'Модель постоянной средней доходности'),
    ('market_model',  MarketModel,       'Рыночная модель'),
    ('capm',          CAPMModel,         'CAPM (модель ценообразования капитальных активов)'),
]

RU_MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                   'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def _fmt_ru(d) -> str:
    return pd.Timestamp(d).strftime('%d.%m.%Y')


def _fmt_short(x, _pos=None) -> str:
    d = num2date(x)
    return f'{d.day} {RU_MONTHS_SHORT[d.month - 1]}'


# ── Загрузка данных ──────────────────────────────────────────────────────

def load_close_series(con, ticker: str) -> pd.Series:
    rows = con.execute(
        'SELECT candle_date, close FROM stock_candles '
        'WHERE ticker = %s ORDER BY candle_date',
        [ticker],
    ).fetchall()
    s = pd.Series({pd.Timestamp(d): float(c) for d, c in rows})
    s = s[s.index.duplicated(keep='last') == False].sort_index()
    return s


def load_log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def load_risk_free(con) -> pd.Series:
    rows = con.execute(
        'SELECT rate_date, annual_rate_pct FROM risk_free_rate ORDER BY rate_date'
    ).fetchall()
    s = pd.Series({pd.Timestamp(d): float(r) for d, r in rows})
    daily = np.log(1 + s / 100) / 252
    return daily


# ── Окна и расчёты ───────────────────────────────────────────────────────

def get_windows(prices: pd.Series, ev_date: date,
                w: int, est_w: int) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    trading = prices.sort_index().index
    t0 = pd.Timestamp(ev_date)
    idx0 = trading.searchsorted(t0, side='left')
    est_end = idx0 - w - 1
    est_start = est_end - est_w + 1
    ev_start = idx0 - w
    ev_end = idx0 + w
    return trading[est_start:est_end + 1], trading[ev_start:ev_end + 1]


def fit_predict(model_cls, stock_lr: pd.Series, market_lr: pd.Series,
                rf_lr: pd.Series, est_idx: pd.DatetimeIndex,
                target_idx: pd.DatetimeIndex) -> pd.Series:
    """Калибрует модель на est_idx, возвращает E[r_t] на target_idx."""
    common_est = est_idx.intersection(stock_lr.index).intersection(market_lr.index)
    common_est = common_est.intersection(rf_lr.index)
    mdl = model_cls()
    mdl.fit(
        stock_log_returns=stock_lr.reindex(common_est),
        market_log_returns=market_lr.reindex(common_est),
        rf_log_returns=rf_lr.reindex(common_est),
    )
    m_t = market_lr.reindex(target_idx).ffill().fillna(0.0)
    r_t = rf_lr.reindex(target_idx).ffill().fillna(0.0)
    return mdl.predict(dates=target_idx, market_log_returns=m_t, rf_log_returns=r_t)


def cumulative_prices_from(actual_prices: pd.Series,
                           expected_lr: pd.Series,
                           target_idx: pd.DatetimeIndex,
                           start_date) -> pd.Series:
    """Накопительный прогноз цен: P_pred(start) = P_actual(start_date),
    далее P_pred(t) = P_pred(t-1) * exp(E[r_t]).

    Используется как для оценочного хвоста (стартуем от первой точки хвоста —
    видно гладкий «след» модели), так и для окна события (стартуем от факта
    последнего дня оценочного окна — стандартный out-of-sample прогноз).
    """
    out = {}
    p = float(actual_prices.loc[start_date])
    for d in target_idx:
        p = p * float(np.exp(expected_lr.loc[d]))
        out[d] = p
    return pd.Series(out)


# ── Рисование ─────────────────────────────────────────────────────────────

def plot_event_study(model_key: str, model_label: str,
                     actual_prices: pd.Series,
                     est_idx: pd.DatetimeIndex,
                     ev_idx: pd.DatetimeIndex,
                     predicted_tail: pd.Series,
                     predicted_event: pd.Series,
                     ar_per_day: pd.Series,
                     event_date: date,
                     div_per_share: float,
                     div_year_label: str,
                     output_path: Path) -> None:
    tail_start = est_idx[-EST_TAIL_DAYS]
    plot_slice = actual_prices.loc[tail_start:ev_idx[-1] + pd.Timedelta(days=5)]

    fig, ax = plt.subplots(figsize=(13, 7))

    ax.axvspan(tail_start, est_idx[-1], facecolor='#cfe2ff', alpha=0.5,
               label=f'Оценочное окно (хвост {EST_TAIL_DAYS} дн., всего {len(est_idx)})')
    ax.axvspan(ev_idx[0], ev_idx[-1], facecolor='#fdd0d8', alpha=0.6,
               label=f'Окно события (±{EVENT_WINDOW} дней)')

    ax.plot(plot_slice.index, plot_slice.values,
            color='#1f3a93', linewidth=1.8, label='Фактическая цена')

    # Прогноз на оценочном хвосте — гладкая cumulative-линия от первой точки хвоста
    ax.plot(predicted_tail.index, predicted_tail.values,
            color='#c0392b', linewidth=1.6, linestyle='--', alpha=0.65)

    # Прогноз в окне события — cumulative от факта последнего дня оценки
    ax.plot(predicted_event.index, predicted_event.values,
            color='#c0392b', linewidth=2.2, linestyle='--',
            label='Прогноз модели')

    actual_in_window = actual_prices.reindex(ev_idx)
    ax.scatter(predicted_event.index, predicted_event.values,
               color='#c0392b', s=42, zorder=5)
    ax.scatter(actual_in_window.index, actual_in_window.values,
               color='#1f3a93', s=42, zorder=5)

    n_days = len(ev_idx)
    label_indices = sorted({0, n_days // 3, n_days // 2, 2 * n_days // 3, n_days - 1})
    for i, d in enumerate(ev_idx):
        p_pred = predicted_event.loc[d]
        p_act = actual_in_window.loc[d]
        if pd.isna(p_pred) or pd.isna(p_act):
            continue
        ax.annotate(
            '', xy=(d, p_act), xytext=(d, p_pred),
            arrowprops=dict(arrowstyle='-|>', color='#7fbf7f', lw=1.2, alpha=0.55),
            zorder=6,
        )
        if i not in label_indices:
            continue
        # AR_t per-day = actual_log_return_t − E[r_t]. Это и есть классический
        # AR одного дня. Не путать с накопленным CAR (стрелка визуально
        # показывает разницу cumulative-цен, но число рядом — именно AR_t).
        ar_t = float(ar_per_day.loc[d]) if d in ar_per_day.index else float('nan')
        ar_sign = '+' if ar_t > 0 else ''
        ar_pct = ar_t * 100
        side_up = (i % 2 == 0)
        offset_y = 32 if side_up else -32
        label_y_anchor = max(p_pred, p_act) if side_up else min(p_pred, p_act)
        ax.annotate(
            f'AR{i - EVENT_WINDOW:+d}\n{ar_sign}{ar_pct:.2f}%',
            xy=(d, label_y_anchor), xytext=(0, offset_y), textcoords='offset points',
            ha='center', va='center', fontsize=9, color='#1f4d1f',
            bbox=dict(boxstyle='round,pad=0.22', fc='white', ec='#7fbf7f', lw=0.8, alpha=0.95),
            arrowprops=dict(arrowstyle='-', color='#a8c8a8', lw=0.6, alpha=0.6),
            zorder=7,
        )

    t0 = pd.Timestamp(event_date)
    ax.axvline(t0, color='#7d3c98', linewidth=1.6, linestyle=':')
    ymin, ymax = plot_slice.min(), plot_slice.max()
    y_label = ymin + 0.04 * (ymax - ymin)
    ax.annotate(f't₀: объявление дивидендов\n{_fmt_ru(event_date)} ({div_per_share} ₽ {div_year_label})',
                xy=(t0, y_label), xytext=(8, 0), textcoords='offset points',
                ha='left', va='center', fontsize=10, color='#5b2c6f',
                bbox=dict(boxstyle='round,pad=0.32', fc='#f4ecf7', ec='#7d3c98', lw=0.9))

    # CAR = sum(AR_t) по всему окну события. Эквивалентно log(P_act_end / P_pred_end),
    # т.к. прогноз cumulative и стартует от факта last_est. Не суммируем
    # log(P_act_t/P_pred_t) по всем t — это даёт 6× инфляцию (двойная сумма).
    car_value = float(ar_per_day.sum())
    ax.text(0.985, 0.97,
            f'CAR = {car_value * 100:+.2f}%',
            transform=ax.transAxes, ha='right', va='top', fontsize=12,
            color='#2c5b2c', weight='bold',
            bbox=dict(boxstyle='round,pad=0.35', fc='#eafbe1', ec='#2c7a2c', lw=1))

    ax.set_title(f'Event Study LKOH — {model_label}\n'
                 f'Объявление дивидендов {_fmt_ru(event_date)}, окно ±{EVENT_WINDOW} дн.',
                 fontsize=13)
    ax.set_ylabel('Цена, ₽', fontsize=11)
    ax.grid(True, alpha=0.25)
    ax.legend(loc='upper left', framealpha=0.95, fontsize=10)
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_short))
    fig.autofmt_xdate()
    plt.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130)
    plt.close(fig)
    print(f'  -> {output_path}', flush=True)


# ── Главный сценарий ──────────────────────────────────────────────────────

def load_event_meta(con, ticker: str, ev_date: date) -> tuple[float, str]:
    """Возвращает (dividend_per_share, year_label) для события из events.payload."""
    rows = con.execute(
        """SELECT e.payload->>'dividend_per_share', e.payload->>'year'
           FROM events e
           JOIN event_tags et ON et.event_id = e.id
           WHERE et.tag_code = 'DIVIDEND_ANNOUNCEMENT'
             AND e.payload->>'ticker' = %s
             AND e.date_start = %s
           LIMIT 1""",
        [ticker, ev_date],
    ).fetchall()
    if not rows:
        return 0.0, ''
    div = float(rows[0][0]) if rows[0][0] is not None else 0.0
    year = rows[0][1] or ''
    return div, f'за {year}' if year else ''


def main() -> None:
    con = psycopg.connect(PG_DSN, autocommit=True)
    prices = load_close_series(con, TICKER)
    market_prices = load_close_series(con, 'IMOEX')
    stock_lr = load_log_returns(prices)
    market_lr = load_log_returns(market_prices)
    rf_lr = load_risk_free(con)

    for event_date in EVENT_DATES:
        div_amount, div_year_label = load_event_meta(con, TICKER, event_date)
        print(f'\n=== LKOH × {event_date} ({div_amount:g} ₽ {div_year_label}) ===', flush=True)

        est_idx, ev_idx = get_windows(prices, event_date, EVENT_WINDOW, ESTIMATION_WINDOW)
        print(f'  оценочное окно: {est_idx[0].date()} .. {est_idx[-1].date()} ({len(est_idx)} дн.)', flush=True)
        print(f'  окно события:   {ev_idx[0].date()} .. {ev_idx[-1].date()} ({len(ev_idx)} дн.)', flush=True)

        tail_idx = est_idx[-EST_TAIL_DAYS:]
        full_target_idx = tail_idx.append(ev_idx)

        for key, cls, label in MODELS:
            print(f'  [{key}] {label}', flush=True)
            expected_lr_full = fit_predict(cls, stock_lr, market_lr, rf_lr, est_idx, full_target_idx)
            predicted_tail = cumulative_prices_from(
                prices, expected_lr_full.reindex(tail_idx),
                target_idx=tail_idx[1:],
                start_date=tail_idx[0],
            )
            predicted_tail = pd.concat([
                pd.Series({tail_idx[0]: float(prices.loc[tail_idx[0]])}),
                predicted_tail,
            ])

            trading = prices.sort_index().index
            last_est_day = trading[trading.get_loc(ev_idx[0]) - 1]
            predicted_event = cumulative_prices_from(
                prices, expected_lr_full.reindex(ev_idx),
                target_idx=ev_idx,
                start_date=last_est_day,
            )

            # AR_t per-day = actual_log_return_t − E[r_t]
            actual_lr_ev = stock_lr.reindex(ev_idx)
            ar_per_day = (actual_lr_ev - expected_lr_full.reindex(ev_idx))
            car_value = float(ar_per_day.sum())
            print(f'    CAR = {car_value:+.4f} ({car_value*100:+.2f}%)', flush=True)
            output_path = OUTPUT_DIR / f'event_study_lkoh_{event_date.isoformat()}_{key}.png'
            plot_event_study(
                model_key=key, model_label=label,
                actual_prices=prices,
                est_idx=est_idx, ev_idx=ev_idx,
                predicted_tail=predicted_tail,
                predicted_event=predicted_event,
                ar_per_day=ar_per_day,
                event_date=event_date,
                div_per_share=div_amount,
                div_year_label=div_year_label,
                output_path=output_path,
            )


if __name__ == '__main__':
    main()
