"""Анализ эффекта набора событий (Event Effect Analysis).

Обёртка над EventStudy для расчёта эффекта набора прецедентов на тикер.

Две основные функции:
    calculate_individual  — индивидуальные CAR + предсказательный интервал
                            (вкладка Events CAR Explorer).
    calculate_sensitivity — heatmap CAR/p-value по сетке параметров
                            (вкладка CAR Sensitivity Analysis).

Реализация спецификации в docs/drafts/SPEC_EVENT_EFFECT_ANALYSIS_DRAFT.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt

import numpy as np
from scipy import stats as sp_stats

from core.event_study import EventStudy
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider

CentralStatistic = str  # 'median' | 'mean'

# Уровень доверия PI и теста Shapiro-Wilk — захардкожен в спеке.
_PI_ALPHA = 0.05


@dataclass
class IndividualCar:
    event_id: str
    date: str  # ISO YYYY-MM-DD
    car: float


@dataclass
class ExcludedEvent:
    event_id: str
    reason: str  # 'insufficient_history' | 'unknown_event'


@dataclass
class IndividualForecast:
    central: float
    pi_lower: float
    pi_upper: float
    n: int
    shapiro_p_value: float | None  # None при n < 3 (Shapiro требует ≥ 3)


@dataclass
class IndividualResult:
    individual_cars: list[IndividualCar]
    excluded_events: list[ExcludedEvent]
    forecast: IndividualForecast | None  # None если ни одного валидного CAR


@dataclass
class SensitivityCell:
    window: int
    model: str
    estimation: int
    car: float
    p_value: float
    n: int


@dataclass
class SensitivityResult:
    cells: list[SensitivityCell]
    excluded_events_by_estimation: dict[str, list[str]]


# ---------------------------------------------------------------------------
# Дата события из БД
# ---------------------------------------------------------------------------

def _load_event_dates(con, event_ids: list[str]) -> dict[str, date]:
    """Возвращает event_id → date_start. Отсутствующие в БД пропускаются."""
    if not event_ids:
        return {}
    rows = con.execute(
        "SELECT id, date_start FROM events WHERE id = ANY(%s)",
        [event_ids],
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Прогнозный интервал (предсказательный, через t-распределение)
# ---------------------------------------------------------------------------

def _forecast(cars: list[float], central_statistic: CentralStatistic) -> IndividualForecast | None:
    """PI = M ± t_crit × S × √(1 + 1/n) для следующего наблюдения.

    central_statistic выбирает M ∈ {median, mean}. S — стандартное
    отклонение выборки. Shapiro-Wilk на нормальность — null при n < 3.
    """
    n = len(cars)
    if n == 0:
        return None
    arr = np.asarray(cars, dtype=float)
    central = float(np.median(arr) if central_statistic == 'median' else np.mean(arr))

    if n == 1:
        return IndividualForecast(central=central, pi_lower=central, pi_upper=central,
                                  n=1, shapiro_p_value=None)

    s = float(np.std(arr, ddof=1))
    df = n - 1
    t_crit = float(sp_stats.t.ppf(1 - _PI_ALPHA / 2, df=df))
    half = t_crit * s * sqrt(1 + 1 / n)

    shapiro_p = None
    if n >= 3:
        try:
            shapiro_p = float(sp_stats.shapiro(arr).pvalue)
        except Exception:
            shapiro_p = None

    return IndividualForecast(
        central=central,
        pi_lower=central - half,
        pi_upper=central + half,
        n=n,
        shapiro_p_value=shapiro_p,
    )


# ---------------------------------------------------------------------------
# calculate_individual
# ---------------------------------------------------------------------------

def calculate_individual(
    *,
    ticker: str,
    event_ids: list[str],
    window: int,
    model: str,
    estimation_window: int,
    central_statistic: CentralStatistic,
    con,
    stocks: StockDataProvider,
    market: MarketDataProvider,
) -> IndividualResult:
    """Считает индивидуальные CAR и прогнозный интервал по набору событий.

    Аргументы:
        ticker: тикер из ведущего графика группы.
        event_ids: набор прецедентов (из «Поиска прецедентов»).
        window: симметричное окно (event_window = (-window, +window)).
        model: 'mean_adjusted' | 'market_model' | 'capm'.
        estimation_window: длина оценочного окна в торговых днях.
        central_statistic: 'median' | 'mean' для M в PI.
        con: psycopg-коннект (для чтения date_start из events).
        stocks/market: data providers.
    """
    date_by_id = _load_event_dates(con, event_ids)

    stock_log_returns = stocks.get_log_returns(ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()
    study = EventStudy(stock_log_returns=stock_log_returns)

    individual_cars: list[IndividualCar] = []
    excluded: list[ExcludedEvent] = []

    for eid in event_ids:
        ev_date = date_by_id.get(eid)
        if ev_date is None:
            excluded.append(ExcludedEvent(event_id=eid, reason='unknown_event'))
            continue

        result = study.analyze(
            event_date=ev_date,
            model=model,
            event_window=(-window, window),
            estimation_window=estimation_window,
            market=market_log_returns,
            rf=rf,
        )
        if result is None:
            excluded.append(ExcludedEvent(event_id=eid, reason='insufficient_history'))
            continue

        individual_cars.append(IndividualCar(
            event_id=eid,
            date=ev_date.isoformat(),
            car=result.car,
        ))

    forecast = _forecast([ic.car for ic in individual_cars], central_statistic)

    return IndividualResult(
        individual_cars=individual_cars,
        excluded_events=excluded,
        forecast=forecast,
    )


# ---------------------------------------------------------------------------
# calculate_sensitivity
# ---------------------------------------------------------------------------

def calculate_sensitivity(
    *,
    ticker: str,
    event_ids: list[str],
    windows: list[int],
    models: list[str],
    estimation_windows: list[int],
    con,
    stocks: StockDataProvider,
    market: MarketDataProvider,
) -> SensitivityResult:
    """Heatmap CAR/p-value по сетке (window × model × estimation_window).

    Для каждой комбинации параметров вызывает EventStudy.analyze_aggregate
    и собирает агрегированный CAR + p-value + размер выборки.

    excluded_events_by_estimation формируется по самому короткому оценочному
    окну в сетке: чем длиннее окно — тем больше исключений. Для упрощения
    собираем исключения отдельным проходом по каждому estimation_window.
    """
    date_by_id = _load_event_dates(con, event_ids)

    stock_log_returns = stocks.get_log_returns(ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()
    study = EventStudy(stock_log_returns=stock_log_returns)

    valid_event_dates: list[date] = [date_by_id[eid] for eid in event_ids if eid in date_by_id]

    cells: list[SensitivityCell] = []
    for est in estimation_windows:
        for mdl in models:
            for w in windows:
                agg = study.analyze_aggregate(
                    event_dates=valid_event_dates,
                    model=mdl,
                    event_window=(-w, w),
                    estimation_window=est,
                    market=market_log_returns,
                    rf=rf,
                )
                if agg is None:
                    cells.append(SensitivityCell(
                        window=w, model=mdl, estimation=est,
                        car=0.0, p_value=1.0, n=0,
                    ))
                else:
                    cells.append(SensitivityCell(
                        window=w, model=mdl, estimation=est,
                        car=agg.cumulative_mean_car,
                        p_value=agg.p_value,
                        n=agg.n_events,
                    ))

    # excluded_events_by_estimation: пробегаемся ещё раз по каждому
    # estimation_window и фиксируем events, для которых analyze() вернул None.
    # Окно событий тут не важно (insufficient_history ловится в оценочном окне),
    # берём минимальный window из сетки.
    min_w = min(windows) if windows else 1
    # Модель тут тоже не важна для проверки исторической достаточности.
    probe_model = models[0] if models else 'market_model'
    excluded_by_est: dict[str, list[str]] = {}
    for est in estimation_windows:
        excluded_ids: list[str] = []
        for eid in event_ids:
            ev_date = date_by_id.get(eid)
            if ev_date is None:
                excluded_ids.append(eid)
                continue
            r = study.analyze(
                event_date=ev_date,
                model=probe_model,
                event_window=(-min_w, min_w),
                estimation_window=est,
                market=market_log_returns,
                rf=rf,
            )
            if r is None:
                excluded_ids.append(eid)
        excluded_by_est[str(est)] = excluded_ids

    return SensitivityResult(
        cells=cells,
        excluded_events_by_estimation=excluded_by_est,
    )
