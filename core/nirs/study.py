"""
Датаклассы и оркестратор событийного анализа.

Датаклассы:
    EventStudyConfig  — конфигурация одного запуска (модель + окна)
    Event             — одно дивидендное событие
    MarketContext     — (reexport из models) рыночные данные для окна
    EventResult       — результат по одному событию
    CompanyResult     — агрегат по одной компании (промежуточный вывод)
    StudyResult       — агрегат по всей выборке (одна строка из 27)

Оркестратор:
    EventStudyRunner  — перебирает все 27 комбинаций, возвращает DataFrame
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

from .models import (
    BaseModel, MarketContext,
    MeanAdjustedModel, MarketModel, CAPMModel,
)

# ---------------------------------------------------------------------------
# Конфигурация и входные структуры
# ---------------------------------------------------------------------------

ModelType = Literal["mean_adjusted", "market_model", "capm"]


@dataclass(frozen=True)
class EventStudyConfig:
    """Параметры одного запуска событийного анализа."""
    model: ModelType
    event_window: tuple[int, int]   # например (-10, +10)
    estimation_window: int           # 100, 200 или 300 торговых дней


@dataclass(frozen=True)
class Event:
    """Одно дивидендное событие."""
    ticker: str
    event_date: date
    dividend: float
    year: int


# ---------------------------------------------------------------------------
# Выходные структуры
# ---------------------------------------------------------------------------

@dataclass
class EventResult:
    """Результат расчёта CAR для одного события."""
    ticker: str
    event_date: date
    ar: list[float]          # аномальные доходности по дням окна
    car: float               # накопленная аномальная доходность
    n_days: int              # фактическое количество дней в окне


@dataclass
class CompanyResult:
    """Агрегированный результат по одной компании (промежуточный вывод)."""
    ticker: str
    mean_car: float
    std_car: float
    t_stat: float
    p_value: float
    significant: bool        # уровень значимости 5 %
    n_events: int


@dataclass
class StudyResult:
    """Агрегированный результат по всей выборке для одной конфигурации."""
    config: EventStudyConfig
    mean_car: float
    std_car: float
    t_stat: float
    p_value: float
    significant: bool
    n_companies: int
    n_events: int


# ---------------------------------------------------------------------------
# t-тест (обёртка над scipy)
# ---------------------------------------------------------------------------

def _ttest_1samp(arr: np.ndarray) -> tuple[float, float]:
    """Одновыборочный t-тест H0: mean=0. Возвращает (t_stat, p_value)."""
    if len(arr) < 2:
        return 0.0, 1.0
    result = stats.ttest_1samp(arr, popmean=0.0)
    return float(result.statistic), float(result.pvalue)


# ---------------------------------------------------------------------------
# Фабрика моделей
# ---------------------------------------------------------------------------

def _make_model(model_type: ModelType) -> BaseModel:
    if model_type == "mean_adjusted":
        return MeanAdjustedModel()
    elif model_type == "market_model":
        return MarketModel()
    elif model_type == "capm":
        return CAPMModel()
    raise ValueError(f"Неизвестный тип модели: {model_type!r}")


# ---------------------------------------------------------------------------
# Оркестратор
# ---------------------------------------------------------------------------

class EventStudyRunner:
    """
    Оркестратор событийного анализа.

    Принимает:
        prices   — dict {ticker: pd.Series} дневных логдоходностей
        market   — pd.Series дневных логдоходностей индекса IMOEX
        rf       — pd.Series дневных безрисковых ставок (RUONIA/252/100)
                   с индексом по дате

    Методы:
        analyze_single_event()   — одно событие, возвращает EventResult
        analyze_all_events()     — список событий → список CompanyResult
        run_sensitivity_study()  — 27 конфигураций → DataFrame
    """

    # Все 27 комбинаций параметров
    ALL_CONFIGS: list[EventStudyConfig] = [
        EventStudyConfig(model=m, event_window=ew, estimation_window=esw)
        for m in ("mean_adjusted", "market_model", "capm")
        for ew in ((-3, 3), (-10, 10), (-20, 20))
        for esw in (100, 200, 300)
    ]

    def __init__(
        self,
        prices: dict[str, pd.Series],
        market: pd.Series,
        rf: pd.Series,
    ) -> None:
        self.prices = prices
        self.market = market
        self.rf = rf

    # ------------------------------------------------------------------
    # Уровень 1: одно событие
    # ------------------------------------------------------------------

    def analyze_single_event(
        self,
        event: Event,
        config: EventStudyConfig,
    ) -> EventResult | None:
        """
        Рассчитывает AR и CAR для одного события.

        Возвращает None, если данных недостаточно
        (оценочное или событийное окно слишком короткое).
        """
        ticker = event.ticker
        if ticker not in self.prices:
            return None

        stock = self.prices[ticker]
        t0 = pd.Timestamp(event.event_date)
        ew_start, ew_end = config.event_window
        esw = config.estimation_window

        trading_days = stock.index.sort_values()

        # Индекс t=0
        idx0 = trading_days.searchsorted(t0, side='left')
        if idx0 >= len(trading_days):
            return None

        # Оценочное окно: [t0 - esw - |ew_start|, t0 + ew_start - 1]
        # т.е. esw дней непосредственно перед началом событийного окна
        est_end_pos = idx0 + ew_start - 1       # последний день оценочного окна (отрицательный offset)
        est_start_pos = est_end_pos - esw + 1

        if est_start_pos < 0 or est_end_pos < 0:
            return None

        est_idx = trading_days[est_start_pos: est_end_pos + 1]
        if len(est_idx) < esw // 2:             # допускаем не менее 50% дней
            return None

        # Событийное окно
        ev_start_pos = idx0 + ew_start
        ev_end_pos = idx0 + ew_end

        if ev_start_pos < 0 or ev_end_pos >= len(trading_days):
            return None

        ev_idx = trading_days[max(ev_start_pos, 0): ev_end_pos + 1]
        if len(ev_idx) == 0:
            return None

        # Выравниваем ряды по датам
        stock_est = stock.reindex(est_idx).dropna()
        # ffill: переносим последнее известное значение на выходные/праздники;
        # fillna(0.0) — страховка на случай пропусков в начале ряда.
        mkt_est   = self.market.reindex(est_idx).ffill().fillna(0.0)
        rf_est    = self.rf.reindex(est_idx).ffill().fillna(0.0)

        stock_ev  = stock.reindex(ev_idx).fillna(0.0)
        mkt_ev    = self.market.reindex(ev_idx).ffill().fillna(0.0)
        rf_ev     = self.rf.reindex(ev_idx).ffill().fillna(0.0)

        if len(stock_est) < 10:
            return None

        # Обрезаем mkt/rf по длине stock_est (могут отличаться на 1-2 строки)
        common_est = stock_est.index.intersection(mkt_est.index).intersection(rf_est.index)
        stock_est = stock_est.reindex(common_est)
        mkt_est   = mkt_est.reindex(common_est)
        rf_est    = rf_est.reindex(common_est)

        ctx_est = MarketContext(mkt_est, rf_est)
        ctx_ev  = MarketContext(mkt_ev, rf_ev)

        model = _make_model(config.model)
        model.fit(stock_est, ctx_est)
        expected = model.predict(ctx_ev)

        ar = (stock_ev.values - expected.values).tolist()
        car = float(np.sum(ar))

        return EventResult(
            ticker=ticker,
            event_date=event.event_date,
            ar=ar,
            car=car,
            n_days=len(ev_idx),
        )

    # ------------------------------------------------------------------
    # Уровень 2: все события → результат по компаниям
    # ------------------------------------------------------------------

    def analyze_all_events(
        self,
        events: list[Event],
        config: EventStudyConfig,
    ) -> list[CompanyResult]:
        """
        Рассчитывает CAR для каждого события и агрегирует по компаниям.

        Возвращает список CompanyResult (по одному на тикер).
        """
        by_ticker: dict[str, list[float]] = {}

        for ev in events:
            result = self.analyze_single_event(ev, config)
            if result is None:
                continue
            by_ticker.setdefault(result.ticker, []).append(result.car)

        company_results: list[CompanyResult] = []
        for ticker, cars in by_ticker.items():
            n = len(cars)
            if n < 2:
                continue
            arr = np.array(cars)
            mean = float(arr.mean())
            std  = float(arr.std(ddof=1))
            t_val, p_val = _ttest_1samp(arr)
            company_results.append(CompanyResult(
                ticker=ticker,
                mean_car=round(mean, 6),
                std_car=round(std, 6),
                t_stat=round(float(t_val), 4),
                p_value=round(float(p_val), 4),
                significant=bool(p_val < 0.05),
                n_events=n,
            ))

        return company_results

    # ------------------------------------------------------------------
    # Уровень 3: перебор 27 конфигураций
    # ------------------------------------------------------------------

    def run_sensitivity_study(
        self,
        events: list[Event],
    ) -> pd.DataFrame:
        """
        Запускает анализ для всех 27 конфигураций.

        Для каждой конфигурации выполняется единый проход по событиям,
        после чего вычисляются два уровня агрегации:
            1. Уровень компаний (n=11): среднее mean_CAR по компаниям →
               t-тест по 11 значениям (исходный подход).
            2. Уровень событий (n≈110): t-тест напрямую по всем CARs →
               более высокая мощность критерия (стандарт в литературе).

        Возвращает DataFrame[27 строк] с колонками:
            model, event_window, estimation_window,
            mean_car, std_car,
            t_stat, p_value, significant           (компанейский уровень)
            t_stat_events, p_value_events,
            significant_events, n_events_total     (событийный уровень)
        """
        rows = []
        for config in self.ALL_CONFIGS:
            # Единый проход: собираем CARs по компаниям и по всем событиям
            by_ticker: dict[str, list[float]] = {}
            all_event_cars: list[float] = []

            for ev in events:
                res = self.analyze_single_event(ev, config)
                if res is None:
                    continue
                by_ticker.setdefault(res.ticker, []).append(res.car)
                all_event_cars.append(res.car)

            if not by_ticker:
                continue

            # --- Уровень компаний ---
            company_means = np.array([
                float(np.mean(cars)) for cars in by_ticker.values() if len(cars) >= 2
            ])
            if len(company_means) == 0:
                continue
            n_comp = len(company_means)
            mean_c = float(company_means.mean())
            std_c  = float(company_means.std(ddof=1)) if n_comp > 1 else 0.0
            t_comp, p_comp = _ttest_1samp(company_means)

            # --- Уровень событий ---
            ev_arr = np.array(all_event_cars)
            t_ev, p_ev = _ttest_1samp(ev_arr)

            rows.append({
                "model":               config.model,
                "event_window":        f"[{config.event_window[0]}, +{config.event_window[1]}]",
                "estimation_window":   config.estimation_window,
                "mean_car":            round(mean_c, 6),
                "std_car":             round(std_c, 6),
                # Компанейский уровень (n=11)
                "t_stat":              round(t_comp, 4),
                "p_value":             round(p_comp, 4),
                "significant":         p_comp < 0.05,
                # Событийный уровень (n≈110)
                "t_stat_events":       round(t_ev, 4),
                "p_value_events":      round(p_ev, 4),
                "significant_events":  p_ev < 0.05,
                "n_events_total":      len(ev_arr),
            })

        return pd.DataFrame(rows)

    def check_event_overlaps(
        self,
        events: list[Event],
        config: EventStudyConfig,
    ) -> pd.DataFrame:
        """
        Проверяет пересечение окон разных событий одной компании.

        Для каждого события комбинированное окно = [est_start, ev_end].
        Если у двух событий одной компании эти окна перекрываются,
        оценочное окно второго события «загрязнено» аномальными доходностями
        первого события, что нарушает независимость оценок.

        Возвращает DataFrame с парами конфликтующих событий.
        """
        ew_start, ew_end = config.event_window
        esw = config.estimation_window

        by_ticker: dict[str, list[Event]] = {}
        for ev in events:
            by_ticker.setdefault(ev.ticker, []).append(ev)

        overlap_rows = []
        for ticker, evs in by_ticker.items():
            if ticker not in self.prices:
                continue
            trading_days = self.prices[ticker].index.sort_values()

            # Вычисляем торговые диапазоны [est_start, ev_end] для каждого события
            ranges: list[tuple[Event, pd.Timestamp, pd.Timestamp]] = []
            for ev in sorted(evs, key=lambda e: e.event_date):
                t0   = pd.Timestamp(ev.event_date)
                idx0 = int(trading_days.searchsorted(t0, side="left"))
                if idx0 >= len(trading_days):
                    continue
                est_start_pos = idx0 + ew_start - 1 - esw + 1
                ev_end_pos    = idx0 + ew_end
                if est_start_pos < 0 or ev_end_pos >= len(trading_days):
                    continue
                ranges.append((ev, trading_days[est_start_pos], trading_days[ev_end_pos]))

            # Попарная проверка пересечений
            for i in range(len(ranges)):
                for j in range(i + 1, len(ranges)):
                    ev1, s1, e1 = ranges[i]
                    ev2, s2, e2 = ranges[j]
                    if s1 <= e2 and s2 <= e1:   # интервалы пересекаются
                        overlap_rows.append({
                            "ticker":  ticker,
                            "event1":  ev1.event_date,
                            "event2":  ev2.event_date,
                            "window1": f"{s1.date()} – {e1.date()}",
                            "window2": f"{s2.date()} – {e2.date()}",
                        })

        return pd.DataFrame(overlap_rows)
