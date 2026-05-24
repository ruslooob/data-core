"""
Событийный анализ для одной акции.

EventStudy             — расчёт AR и CAR для одного события на одной акции.
EventStudyResult       — результат анализа одного события.
AggregateStudyResult   — результат агрегированного анализа по всем событиям тикера.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from core.expected_return_models import (
    BaseExpectedReturnModel, MeanAdjustedModel, MarketModel, CAPMModel,
)

# ---------------------------------------------------------------------------
# Типы и результат
# ---------------------------------------------------------------------------

ModelType = str  # 'mean_adjusted', 'market_model', 'capm'


@dataclass
class EventStudyResult:
    """Результат расчёта CAR для одного события."""
    event_date: date
    ar: list[float]          # аномальные доходности по дням окна
    car: float               # накопленная аномальная доходность
    n_days: int              # фактическое количество дней в окне
    estimation_std: float    # σ аномальных доходностей в оценочном окне
    estimation_residuals: list[float] = field(default_factory=list)
    # ↑ дневные AR на оценочном окне (после фильтрации выбросов, если она была);
    # используются для построения baseline-фона через нарезку скользящим окном
    estimation_dates: list[str] = field(default_factory=list)
    estimation_actual: list[float] = field(default_factory=list)
    estimation_predicted: list[float] = field(default_factory=list)
    outliers_removed: int = 0  # сколько выбросов убрано из оценочного окна


@dataclass
class AggregateStudyResult:
    """Результат агрегированного анализа по нескольким событиям."""
    n_events: int                        # количество событий
    mean_car: list[float]                # средний CAR по дням окна (усреднённый AR[t])
    cumulative_mean_car: float           # итоговый средний CAR
    t_stat: float                        # t-статистика на итоговом CAR
    p_value: float                       # p-value (двусторонний)
    individual_cars: list[float]         # CAR каждого отдельного события
    event_dates: list[str]               # даты событий (ISO)


# ---------------------------------------------------------------------------
# Фабрика моделей
# ---------------------------------------------------------------------------

def _make_model(model_type: ModelType) -> BaseExpectedReturnModel:
    if model_type == 'mean_adjusted':
        return MeanAdjustedModel()
    elif model_type == 'market_model':
        return MarketModel()
    elif model_type == 'capm':
        return CAPMModel()
    raise ValueError(f"Неизвестный тип модели: {model_type!r}")


# ---------------------------------------------------------------------------
# EventStudy
# ---------------------------------------------------------------------------

class EventStudy:
    """
    Событийный анализ для одной акции.

    Принимает pd.Series дневных логдоходностей (DatetimeIndex).
    Метод analyze() рассчитывает AR и CAR для одного события.

    Пример::

        study = EventStudy(stock_log_returns=StockDataProvider().get_log_returns('LKOH', start_date='2013-01-01'))
        result = study.analyze(
            event_date=date(2018, 5, 14),
            model='market_model',
            event_window=(-10, 10),
            estimation_window=200,
            market=market_series,
        )
    """

    def __init__(self, stock_log_returns: pd.Series) -> None:
        self.stock_log_returns = stock_log_returns

    def _resolve_windows(
        self,
        event_date: date,
        event_window: tuple[int, int],
        estimation_window: int,
    ) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex] | None:
        """Определяет индексы оценочного и событийного окон. None если данных мало."""
        trading_days = self.stock_log_returns.index.sort_values()
        t0 = pd.Timestamp(event_date)
        ew_start, ew_end = event_window
        esw = estimation_window

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

        return est_idx, ev_idx

    @staticmethod
    def _align_series(
        stock_log_returns: pd.Series,
        market: pd.Series | None,
        rf: pd.Series | None,
        idx: pd.DatetimeIndex,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Выравнивает доходности акции/рынка/безрисковой ставки по индексу дат."""
        s = stock_log_returns.reindex(idx).dropna()
        m = market.reindex(idx).ffill().fillna(0.0) if market is not None else pd.Series(0.0, index=idx)
        r = rf.reindex(idx).ffill().fillna(0.0) if rf is not None else pd.Series(0.0, index=idx)
        return s, m, r

    def analyze(
        self,
        event_date: date,
        model: ModelType,
        event_window: tuple[int, int],
        estimation_window: int,
        *,
        market: pd.Series | None = None,
        rf: pd.Series | None = None,
        outlier_threshold: float | None = None,
    ) -> EventStudyResult | None:
        """
        Рассчитывает AR и CAR для одного события.

        Параметры:
            event_date:         дата события
            model:              тип модели ('mean_adjusted', 'market_model', 'capm')
            event_window:       событийное окно, например (-10, 10)
            estimation_window:  длина оценочного окна (торговых дней)
            market:             pd.Series логдоходностей индекса (для market_model, capm)
            rf:                 pd.Series безрисковых ставок (для capm)
            outlier_threshold:  порог фильтрации выбросов в оценочном окне (в σ).
                                Если задан, дни с |residual| > threshold*σ исключаются
                                из оценочного окна, модель перекалибруется.

        Возвращает EventStudyResult или None, если данных недостаточно.
        """
        windows = self._resolve_windows(event_date, event_window, estimation_window)
        if windows is None:
            return None
        est_idx, ev_idx = windows

        stock_est, mkt_est, rf_est = self._align_series(self.stock_log_returns, market, rf, est_idx)
        if len(stock_est) < 10:
            return None

        # Обрезаем по общим датам оценочного окна
        common_est = stock_est.index.intersection(mkt_est.index).intersection(rf_est.index)
        stock_est = stock_est.reindex(common_est)
        mkt_est = mkt_est.reindex(common_est)
        rf_est = rf_est.reindex(common_est)

        outliers_removed = 0

        # Фильтрация выбросов и калибровка модели обёрнуты в try/except:
        # на вырожденных оценочных окнах (NaN / константа в доходностях
        # индекса или акции) numpy.polyfit бросает LinAlgError. Для
        # event study это равнозначно «не смогли откалибровать модель» —
        # возвращаем None, событие исключается ровно как при нехватке
        # истории. См. также backend/routers/event_effect.py.
        try:
            if outlier_threshold is not None and outlier_threshold > 0:
                mdl_pre = _make_model(model)
                mdl_pre.fit(stock_log_returns=stock_est, market_log_returns=mkt_est, rf_log_returns=rf_est)
                expected_pre = mdl_pre.predict(dates=common_est, market_log_returns=mkt_est, rf_log_returns=rf_est)
                residuals_pre = stock_est.values - expected_pre.values
                sigma_pre = float(np.std(residuals_pre, ddof=1)) if len(residuals_pre) > 1 else 0.0

                if sigma_pre > 0:
                    mask = np.abs(residuals_pre) <= outlier_threshold * sigma_pre
                    outliers_removed = int(np.sum(~mask))
                    if outliers_removed > 0 and np.sum(mask) >= 10:
                        common_est = common_est[mask]
                        stock_est = stock_est.reindex(common_est)
                        mkt_est = mkt_est.reindex(common_est)
                        rf_est = rf_est.reindex(common_est)

            stock_ev = self.stock_log_returns.reindex(ev_idx).fillna(0.0)
            mkt_ev = market.reindex(ev_idx).ffill().fillna(0.0) if market is not None else pd.Series(0.0, index=ev_idx)
            rf_ev = rf.reindex(ev_idx).ffill().fillna(0.0) if rf is not None else pd.Series(0.0, index=ev_idx)

            mdl = _make_model(model)
            mdl.fit(stock_log_returns=stock_est, market_log_returns=mkt_est, rf_log_returns=rf_est)
            expected_ev = mdl.predict(dates=ev_idx, market_log_returns=mkt_ev, rf_log_returns=rf_ev)

            # σ аномальных доходностей в оценочном окне (после фильтрации)
            expected_est = mdl.predict(dates=common_est, market_log_returns=mkt_est, rf_log_returns=rf_est)
        except np.linalg.LinAlgError:
            return None
        residuals_est = stock_est.values - expected_est.values
        estimation_std = float(np.std(residuals_est, ddof=1)) if len(residuals_est) > 1 else 0.0

        ar = (stock_ev.values - expected_ev.values).tolist()
        car = float(np.sum(ar))

        return EventStudyResult(
            event_date=event_date,
            ar=ar,
            car=car,
            n_days=len(ev_idx),
            estimation_std=estimation_std,
            estimation_residuals=residuals_est.tolist(),
            estimation_dates=[d.strftime('%Y-%m-%d') for d in common_est],
            estimation_actual=stock_est.values.tolist(),
            estimation_predicted=expected_est.values.tolist(),
            outliers_removed=outliers_removed,
        )

    def analyze_aggregate(
        self,
        event_dates: list[date],
        model: ModelType,
        event_window: tuple[int, int],
        estimation_window: int,
        *,
        market: pd.Series | None = None,
        rf: pd.Series | None = None,
        outlier_threshold: float | None = None,
    ) -> AggregateStudyResult | None:
        """
        Агрегированный event study: средний CAR по нескольким событиям + t-stat.

        Рассчитывает AR для каждого события, усредняет AR[t] по событиям,
        формирует средний CAR и проверяет его значимость.

        Возвращает None, если ни одно событие не удалось проанализировать.
        """
        results: list[EventStudyResult] = []
        for ed in event_dates:
            r = self.analyze(
                event_date=ed,
                model=model,
                event_window=event_window,
                estimation_window=estimation_window,
                market=market,
                rf=rf,
                outlier_threshold=outlier_threshold,
            )
            if r is not None:
                results.append(r)

        if not results:
            return None

        # Все AR должны быть одинаковой длины (окно фиксировано)
        window_len = event_window[1] - event_window[0] + 1
        ar_matrix: list[list[float]] = []
        valid_results: list[EventStudyResult] = []
        for r in results:
            if len(r.ar) == window_len:
                ar_matrix.append(r.ar)
                valid_results.append(r)

        if not valid_results:
            return None

        ar_arr = np.array(ar_matrix)  # shape: (n_events, window_len)
        mean_ar = np.mean(ar_arr, axis=0)  # средний AR по каждому дню
        mean_car = np.cumsum(mean_ar).tolist()

        individual_cars = [r.car for r in valid_results]
        cumulative_mean_car = float(mean_car[-1]) if mean_car else 0.0

        # t-test: H0: средний CAR = 0
        n = len(individual_cars)
        if n >= 2:
            t_stat_val, p_value_val = sp_stats.ttest_1samp(individual_cars, 0.0)
            t_stat = float(t_stat_val)
            p_value = float(p_value_val)
        else:
            t_stat = 0.0
            p_value = 1.0

        return AggregateStudyResult(
            n_events=n,
            mean_car=mean_car,
            cumulative_mean_car=cumulative_mean_car,
            t_stat=t_stat,
            p_value=p_value,
            individual_cars=individual_cars,
            event_dates=[r.event_date.isoformat() for r in valid_results],
        )
