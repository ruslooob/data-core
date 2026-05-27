"""Анализ эффекта набора событий (Event Effect Analysis).

Обёртка над EventStudy для расчёта эффекта набора прецедентов на тикер.

Две основные функции:
    calculate_individual           — индивидуальные CAR + предсказательный интервал
                                     (вкладка Events CAR Explorer).
    calculate_aggregate_sensitivity — heatmap усреднённого по выборке CAR/p-value
                                     по сетке параметров (вкладка AggregateSensitivity).

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

# Порог аномальности по percentile rank.
_ANOMALY_RANK_THRESHOLD = 0.95


@dataclass
class IndividualCar:
    event_id: str
    date: str  # ISO YYYY-MM-DD
    car: float
    # Абсолютный (ненаправленный) baseline — для режима |CAR|.
    rank: float        # percentile rank |CAR| в распределении |псевдо-CAR| события (0..1)
    is_anomaly: bool   # rank > _ANOMALY_RANK_THRESHOLD
    baseline_band: float  # личный 95-перцентиль |псевдо-CAR| (|CAR| > baseline_band → аномалия)
    # Знаковый (направленный) baseline — для режима CAR.
    signed_rank: float        # доля знаковых псевдо-CAR < CAR (>0.95 вверх, <0.05 вниз)
    is_anomaly_signed: bool   # signed_rank вне [0.05, 0.95]
    baseline_up: float           # 95-перцентиль знакового распределения псевдо-CAR
    baseline_down: float         # 5-перцентиль знакового распределения псевдо-CAR


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
class AggregateSensitivityCell:
    window: int
    model: str
    estimation: int
    car: float
    p_value: float
    n: int
    # |CAR|-режим: средний rank по выборке (0..1) и p-value t-test против 0.5.
    # Если события случайны относительно фона, mean_rank ≈ 0.5; систематический
    # сдвиг к большим |CAR| даёт mean_rank > 0.5.
    mean_rank: float
    rank_p_value: float


@dataclass
class AggregateSensitivityResult:
    cells: list[AggregateSensitivityCell]
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
# Baseline через нарезку estimation residuals скользящим окном
# ---------------------------------------------------------------------------

def _pseudo_cars(residuals: list[float], window_len: int) -> list[float]:
    """Скользящие W-дневные суммы дневных AR из оценочного окна.

    Имитируют, какой был бы CAR, если бы событие случилось в каждой точке
    estimation_window. Дают эмпирическое распределение «обычного 11-дневного
    движения» тикера в эпоху прямо перед событием.
    """
    n = len(residuals)
    if n < window_len:
        return []
    arr = np.asarray(residuals, dtype=float)
    # Сумма по скользящему окну через cumsum для эффективности.
    cs = np.concatenate(([0.0], np.cumsum(arr)))
    sums = cs[window_len:] - cs[:n - window_len + 1]
    return sums.tolist()


def _percentile_rank(observed: float, distribution: list[float]) -> float:
    """Где |observed| находится в распределении |distribution| (доля 0..1)."""
    if not distribution:
        return 0.0
    abs_obs = abs(observed)
    n_below = sum(1 for v in distribution if abs(v) < abs_obs)
    return n_below / len(distribution)


def _signed_rank(observed: float, distribution: list[float]) -> float:
    """Где observed (со знаком) лежит в знаковом распределении distribution (доля 0..1).

    > 0.95 — наблюдение аномально высоко (вверх), < 0.05 — аномально низко (вниз).
    Самосогласовано с baseline_up/baseline_down: observed > percentile(dist, 95)
    ⟺ signed_rank > 0.95, observed < percentile(dist, 5) ⟺ signed_rank < 0.05.
    """
    if not distribution:
        return 0.0
    n_below = sum(1 for v in distribution if v < observed)
    return n_below / len(distribution)


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
    window_len = 2 * window + 1

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

        pseudo = _pseudo_cars(result.estimation_residuals, window_len)
        hi = _ANOMALY_RANK_THRESHOLD * 100        # 95-й перцентиль
        lo = (1 - _ANOMALY_RANK_THRESHOLD) * 100  # 5-й перцентиль

        rank = _percentile_rank(result.car, pseudo)
        is_anomaly = rank > _ANOMALY_RANK_THRESHOLD
        signed_rank = _signed_rank(result.car, pseudo)
        is_anomaly_signed = bool(pseudo) and (
            signed_rank > _ANOMALY_RANK_THRESHOLD
            or signed_rank < 1 - _ANOMALY_RANK_THRESHOLD
        )
        if pseudo:
            baseline_band = float(np.percentile(np.abs(pseudo), hi))
            baseline_up = float(np.percentile(pseudo, hi))
            baseline_down = float(np.percentile(pseudo, lo))
        else:
            baseline_band = baseline_up = baseline_down = 0.0

        individual_cars.append(IndividualCar(
            event_id=eid,
            date=ev_date.isoformat(),
            car=result.car,
            rank=rank,
            is_anomaly=is_anomaly,
            baseline_band=baseline_band,
            signed_rank=signed_rank,
            is_anomaly_signed=is_anomaly_signed,
            baseline_up=baseline_up,
            baseline_down=baseline_down,
        ))

    forecast = _forecast([ic.car for ic in individual_cars], central_statistic)

    return IndividualResult(
        individual_cars=individual_cars,
        excluded_events=excluded,
        forecast=forecast,
    )


# ---------------------------------------------------------------------------
# calculate_aggregate_sensitivity
# ---------------------------------------------------------------------------

def calculate_aggregate_sensitivity(
    *,
    ticker: str,
    event_ids: list[str],
    windows: list[int],
    models: list[str],
    estimation_windows: list[int],
    con,
    stocks: StockDataProvider,
    market: MarketDataProvider,
) -> AggregateSensitivityResult:
    """Heatmap CAR/p-value по сетке (window × model × estimation_window).

    Для каждой комбинации параметров проходим все события через
    EventStudy.analyze, собираем индивидуальные CAR + rank-аномалии, и
    отдаём в ячейку: средний CAR с t-test p-value (для signed-режима UI)
    и долю аномалий с биномиальным p-value (для |CAR|-режима UI).

    excluded_events_by_estimation формируется отдельным короткиим проходом
    по каждому estimation_window с минимальным event_window и первой моделью —
    исключения зависят почти только от оценочного окна.
    """
    date_by_id = _load_event_dates(con, event_ids)

    stock_log_returns = stocks.get_log_returns(ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()
    study = EventStudy(stock_log_returns=stock_log_returns)

    valid_event_dates: list[date] = [date_by_id[eid] for eid in event_ids if eid in date_by_id]

    cells: list[AggregateSensitivityCell] = []
    for est in estimation_windows:
        for mdl in models:
            for w in windows:
                window_len = 2 * w + 1
                # Один проход по событиям: собираем CARs и индивидуальные rank-и.
                cars_list: list[float] = []
                ranks_list: list[float] = []
                for ev_date in valid_event_dates:
                    r = study.analyze(
                        event_date=ev_date,
                        model=mdl,
                        event_window=(-w, w),
                        estimation_window=est,
                        market=market_log_returns,
                        rf=rf,
                    )
                    if r is None:
                        continue
                    cars_list.append(r.car)
                    pseudo = _pseudo_cars(r.estimation_residuals, window_len)
                    ranks_list.append(_percentile_rank(r.car, pseudo))

                n = len(cars_list)
                if n == 0:
                    cells.append(AggregateSensitivityCell(
                        window=w, model=mdl, estimation=est,
                        car=0.0, p_value=1.0, n=0,
                        mean_rank=0.5, rank_p_value=1.0,
                    ))
                    continue

                mean_car = float(np.mean(cars_list))
                if n >= 2:
                    _, p_value = sp_stats.ttest_1samp(cars_list, 0.0)
                    p_value = float(p_value)
                else:
                    p_value = 1.0

                # T-test mean(rank) против 0.5: «в среднем по выборке абсолютный
                # CAR значимо смещён относительно типичного шума акции?». При
                # случайной выборке E[rank] = 0.5, систематическое влияние
                # сдвигает в верх (или вниз — двусторонний тест).
                mean_rank = float(np.mean(ranks_list))
                if n >= 2:
                    _, rank_p_value = sp_stats.ttest_1samp(ranks_list, 0.5)
                    rank_p_value = float(rank_p_value)
                else:
                    rank_p_value = 1.0

                cells.append(AggregateSensitivityCell(
                    window=w, model=mdl, estimation=est,
                    car=mean_car, p_value=p_value, n=n,
                    mean_rank=mean_rank, rank_p_value=rank_p_value,
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

    return AggregateSensitivityResult(
        cells=cells,
        excluded_events_by_estimation=excluded_by_est,
    )


# ---------------------------------------------------------------------------
# calculate_individual_sensitivity (один прецедент × сетка параметров)
# ---------------------------------------------------------------------------

@dataclass
class IndividualSensitivityCell:
    window: int
    model: str
    estimation: int
    available: bool       # False — у события не хватает истории под это оценочное окно
    car: float
    baseline_down: float  # 5-перцентиль знакового распределения нормы
    baseline_up: float    # 95-перцентиль
    signed_rank: float
    is_anomaly_signed: bool


def calculate_individual_sensitivity(
    *,
    ticker: str,
    event_date: date,
    windows: list[int],
    models: list[str],
    estimation_windows: list[int],
    stocks: StockDataProvider,
    market: MarketDataProvider,
) -> list[IndividualSensitivityCell]:
    """Heatmap CAR против нормы по сетке (window × model × estimation) для ОДНОГО события.

    Для каждой комбинации: CAR события и его личная норма (5/95 перцентили
    знакового распределения псевдо-CAR оценочного окна). Аномалия — CAR вне
    нормы (signed_rank вне [0.05, 0.95]). t-тест неприменим (n=1): устойчивость
    читается глазами по тому, держится ли знак/величина и выход за норму по сетке.
    """
    stock_log_returns = stocks.get_log_returns(ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()
    study = EventStudy(stock_log_returns=stock_log_returns)

    hi = _ANOMALY_RANK_THRESHOLD * 100         # 95
    lo = (1 - _ANOMALY_RANK_THRESHOLD) * 100   # 5

    cells: list[IndividualSensitivityCell] = []
    for est in estimation_windows:
        for mdl in models:
            for w in windows:
                r = study.analyze(
                    event_date=event_date,
                    model=mdl,
                    event_window=(-w, w),
                    estimation_window=est,
                    market=market_log_returns,
                    rf=rf,
                )
                if r is None:
                    cells.append(IndividualSensitivityCell(
                        window=w, model=mdl, estimation=est, available=False,
                        car=0.0, baseline_down=0.0, baseline_up=0.0,
                        signed_rank=0.0, is_anomaly_signed=False,
                    ))
                    continue

                pseudo = _pseudo_cars(r.estimation_residuals, 2 * w + 1)
                signed_rank = _signed_rank(r.car, pseudo)
                is_anomaly_signed = bool(pseudo) and (
                    signed_rank > _ANOMALY_RANK_THRESHOLD
                    or signed_rank < 1 - _ANOMALY_RANK_THRESHOLD
                )
                if pseudo:
                    baseline_up = float(np.percentile(pseudo, hi))
                    baseline_down = float(np.percentile(pseudo, lo))
                else:
                    baseline_up = baseline_down = 0.0

                cells.append(IndividualSensitivityCell(
                    window=w, model=mdl, estimation=est, available=True,
                    car=r.car, baseline_down=baseline_down, baseline_up=baseline_up,
                    signed_rank=signed_rank, is_anomaly_signed=is_anomaly_signed,
                ))

    return cells
