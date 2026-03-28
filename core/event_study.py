"""
Событийный анализ (event study) для одной акции.

EventStudy     — расчёт AR и CAR для одного события на одной акции.
EventResult    — результат анализа одного события.
DividendEvent  — датакласс дивидендного события.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from core.expected_return_models import (
    BaseModel, MeanAdjustedModel, MarketModel, CAPMModel,
)

# ---------------------------------------------------------------------------
# Типы событий
# ---------------------------------------------------------------------------

ModelType = str  # 'mean_adjusted', 'market_model', 'capm'


@dataclass(frozen=True)
class DividendEvent:
    """Одно дивидендное событие."""
    ticker: str
    event_date: date
    dividend: float
    year: int


# ---------------------------------------------------------------------------
# Результат анализа
# ---------------------------------------------------------------------------

@dataclass
class EventResult:
    """Результат расчёта CAR для одного события."""
    ticker: str
    event_date: date
    ar: list[float]          # аномальные доходности по дням окна
    car: float               # накопленная аномальная доходность
    n_days: int              # фактическое количество дней в окне
    estimation_std: float    # σ аномальных доходностей в оценочном окне


# ---------------------------------------------------------------------------
# Фабрика моделей
# ---------------------------------------------------------------------------

def _make_model(model_type: ModelType) -> BaseModel:
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

        study = EventStudy(stock=get_log_returns('LKOH'))
        result = study.analyze(
            event_date=date(2018, 5, 14),
            model='market_model',
            event_window=(-10, 10),
            estimation_window=200,
            market=market_series,
        )
    """

    def __init__(self, stock: pd.Series, ticker: str = '') -> None:
        self.stock = stock
        self.ticker = ticker

    def _resolve_windows(
        self,
        event_date: date,
        event_window: tuple[int, int],
        estimation_window: int,
    ) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex] | None:
        """Определяет индексы оценочного и событийного окон. None если данных мало."""
        trading_days = self.stock.index.sort_values()
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
        stock: pd.Series,
        market: pd.Series | None,
        rf: pd.Series | None,
        idx: pd.DatetimeIndex,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Выравнивает stock/market/rf по индексу дат."""
        s = stock.reindex(idx).dropna()
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
    ) -> EventResult | None:
        """
        Рассчитывает AR и CAR для одного события.

        Параметры:
            event_date:        дата события
            model:             тип модели ('mean_adjusted', 'market_model', 'capm')
            event_window:      событийное окно, например (-10, 10)
            estimation_window: длина оценочного окна (торговых дней)
            market:            pd.Series логдоходностей индекса (для market_model, capm)
            rf:                pd.Series безрисковых ставок (для capm)

        Возвращает EventResult или None, если данных недостаточно.
        """
        windows = self._resolve_windows(event_date, event_window, estimation_window)
        if windows is None:
            return None
        est_idx, ev_idx = windows

        stock_est, mkt_est, rf_est = self._align_series(self.stock, market, rf, est_idx)
        if len(stock_est) < 10:
            return None

        # Обрезаем по общим датам оценочного окна
        common_est = stock_est.index.intersection(mkt_est.index).intersection(rf_est.index)
        stock_est = stock_est.reindex(common_est)
        mkt_est = mkt_est.reindex(common_est)
        rf_est = rf_est.reindex(common_est)

        stock_ev = self.stock.reindex(ev_idx).fillna(0.0)
        mkt_ev = market.reindex(ev_idx).ffill().fillna(0.0) if market is not None else pd.Series(0.0, index=ev_idx)
        rf_ev = rf.reindex(ev_idx).ffill().fillna(0.0) if rf is not None else pd.Series(0.0, index=ev_idx)

        mdl = _make_model(model)
        mdl.fit(stock_returns=stock_est, market_returns=mkt_est, rf_returns=rf_est)
        expected_ev = mdl.predict(dates=ev_idx, market_returns=mkt_ev, rf_returns=rf_ev)

        # σ аномальных доходностей в оценочном окне
        expected_est = mdl.predict(dates=common_est, market_returns=mkt_est, rf_returns=rf_est)
        residuals_est = stock_est.values - expected_est.values
        estimation_std = float(np.std(residuals_est, ddof=1)) if len(residuals_est) > 1 else 0.0

        ar = (stock_ev.values - expected_ev.values).tolist()
        car = float(np.sum(ar))

        return EventResult(
            ticker=self.ticker,
            event_date=event_date,
            ar=ar,
            car=car,
            n_days=len(ev_idx),
            estimation_std=estimation_std,
        )
