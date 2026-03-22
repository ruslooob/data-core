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
        mkt_est   = self.market.reindex(est_idx).fillna(0.0)
        rf_est    = self.rf.reindex(est_idx).fillna(0.0)

        stock_ev  = stock.reindex(ev_idx).fillna(0.0)
        mkt_ev    = self.market.reindex(ev_idx).fillna(0.0)
        rf_ev     = self.rf.reindex(ev_idx).fillna(0.0)

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

        Для каждой конфигурации:
            1. Вычисляет CompanyResult по каждой компании.
            2. Усредняет mean_CAR по компаниям (equal-weighted).
            3. Считает t-статистику по распределению mean_CAR компаний.

        Возвращает DataFrame[27 строк] с колонками:
            model, event_window, estimation_window,
            mean_car, std_car, t_stat, p_value, significant
        """
        rows = []
        for config in self.ALL_CONFIGS:
            company_results = self.analyze_all_events(events, config)
            if not company_results:
                continue

            company_means = np.array([cr.mean_car for cr in company_results])
            n_comp = len(company_means)
            mean   = float(company_means.mean())
            std    = float(company_means.std(ddof=1)) if n_comp > 1 else 0.0
            t_val, p_val = _ttest_1samp(company_means)

            rows.append({
                "model":             config.model,
                "event_window":      f"[{config.event_window[0]}, +{config.event_window[1]}]",
                "estimation_window": config.estimation_window,
                "mean_car":          round(mean, 6),
                "std_car":           round(std, 6),
                "t_stat":            round(t_val, 4),
                "p_value":           round(p_val, 4),
                "significant":       p_val < 0.05,
            })

        return pd.DataFrame(rows)
