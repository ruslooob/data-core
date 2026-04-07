"""
Анализ влияния события на котировки акции.

Основные функции:
    analyze_event_impact()  — одно событие
    analyze_events_impact() — батч событий (данные загружаются один раз)

Возвращают EventImpactResult с набором метрик для окна вокруг даты события.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from core.cpi_data_provider import load_normalized_cpi_data, CpiType
from core.stock_data_provider import get_candles


@dataclass
class EventImpactParams:
    """Параметры анализа влияния события."""

    baseline_start: str
    """Начало базового периода для расчёта CAR (обязательный параметр)."""

    baseline_end: str
    """Конец базового периода для расчёта CAR (обязательный параметр)."""

    window: int = 20
    """Количество торговых дней до и после события."""

    normalize_cpi: bool = True
    """Корректировать цену на инфляцию (ИПЦ)."""

    cpi_base_date: str = '2012-12-01'
    """Базовая дата для нормализации ИПЦ (только при normalize_cpi=True)."""

    cpi_type: CpiType = CpiType.GOODS_AND_SERVICES
    """Тип ИПЦ (только при normalize_cpi=True)."""


@dataclass
class EventImpactResult:
    """Результат анализа влияния события на акцию."""

    ticker: str
    event_text: str
    event_date: pd.Timestamp

    # Информация об окне
    days_before: int
    """Фактическое количество торговых дней до события (может быть меньше window при обрезании)."""

    days_after: int
    """Фактическое количество торговых дней после события."""

    clipped: bool
    """True если окно было обрезано из-за соседних событий."""

    # Метрики доходности
    point_return_pct: float
    """Точечная доходность: цена в последний день after vs первый день before, %."""

    avg_return_pct: float
    """Средняя доходность: mean(after) vs mean(before), %."""

    # CAR
    car_pct: float
    """Накопленная аномальная доходность (CAR) в окне after, %."""

    # Волатильность
    vol_before_pct: float
    """Волатильность (std дневных доходностей) до события, %."""

    vol_after_pct: float
    """Волатильность (std дневных доходностей) после события, %."""

    vol_ratio: float
    """Коэффициент волатильности: vol_after / vol_before."""

    # Объём
    volume_before: float
    """Средний дневной объём торгов до события."""

    volume_after: float
    """Средний дневной объём торгов после события."""

    volume_ratio: float
    """Коэффициент объёма: volume_after / volume_before."""


def _prepare_analysis_context(
        candles: pd.DataFrame,
        params: EventImpactParams,
) -> tuple[pd.Series, pd.Series, pd.DatetimeIndex, float]:
    """
    Подготавливает контекст анализа: ряды цены и объёма + базовую дневную доходность.
    Опционально нормализует цены по инфляции (CPI).
    Возвращает: price, vol_series, t_days, baseline_daily
    """
    candles = candles.sort_values('DATE').reset_index(drop=True)

    if params.normalize_cpi:
        cpi_norm = load_normalized_cpi_data(params.cpi_type, base_date=params.cpi_base_date)
        cpi_norm['date'] = pd.to_datetime(cpi_norm['date'])
        candles = pd.merge_asof(
            candles, cpi_norm[['date', 'real_ruble']],
            left_on='DATE', right_on='date', direction='backward'
        )
        candles['real_ruble'] = candles['real_ruble'].infer_objects(copy=False)
        price = candles.set_index('DATE')['CLOSE'] * candles.set_index('DATE')['real_ruble']
    else:
        price = candles.set_index('DATE')['CLOSE']

    vol_series = candles.set_index('DATE')['VOL']
    t_days = price.index.sort_values()

    baseline_idx = t_days[
        (t_days >= params.baseline_start) & (t_days <= params.baseline_end)
    ]
    baseline_daily = price.reindex(baseline_idx).dropna().pct_change().dropna().mean()

    return price, vol_series, t_days, baseline_daily


def _compute_event_metrics(
        ticker: str,
        event_date: pd.Timestamp,
        event_text: str,
        price: pd.Series,
        vol_series: pd.Series,
        t_days: pd.DatetimeIndex,
        baseline_daily: float,
        params: EventImpactParams,
        neighbor_dates: Optional[list] = None,
) -> Optional[EventImpactResult]:
    """Вычисляет метрики для одного события на основе уже подготовленных данных."""

    # ── Границы окна ──────────────────────────────────────────────────────
    if neighbor_dates is not None:
        neighbor_ts = pd.to_datetime(neighbor_dates)
        prev_events = neighbor_ts[neighbor_ts < event_date]
        next_events = neighbor_ts[neighbor_ts > event_date]
        prev_bound = prev_events.max() if len(prev_events) > 0 else event_date - pd.Timedelta(days=9999)
        next_bound = next_events.min() if len(next_events) > 0 else event_date + pd.Timedelta(days=9999)

        max_before_date = prev_bound + (event_date - prev_bound) / 2
        max_after_date = event_date + (next_bound - event_date) / 2

        before_days = t_days[(t_days < event_date) & (t_days >= max_before_date)][-params.window:]
        after_days = t_days[(t_days > event_date) & (t_days <= max_after_date)][:params.window]
    else:
        before_days = t_days[t_days < event_date][-params.window:]
        after_days = t_days[t_days > event_date][:params.window]

    clipped = len(before_days) < params.window or len(after_days) < params.window

    p_before = price.reindex(before_days).dropna()
    p_after = price.reindex(after_days).dropna()
    v_before = vol_series.reindex(before_days).dropna()
    v_after = vol_series.reindex(after_days).dropna()

    if len(p_before) < 2 or len(p_after) < 2:
        return None

    # ── Метрики ───────────────────────────────────────────────────────────
    point_return_pct = (p_after.iloc[-1] - p_before.iloc[0]) / p_before.iloc[0] * 100
    avg_return_pct = (p_after.mean() - p_before.mean()) / p_before.mean() * 100

    abnormal = p_after.pct_change().dropna() - baseline_daily
    car_pct = abnormal.sum() * 100

    vol_before_pct = p_before.pct_change().dropna().std() * 100
    vol_after_pct = p_after.pct_change().dropna().std() * 100
    vol_ratio = round(vol_after_pct / vol_before_pct, 2) if vol_before_pct > 0 else float('nan')

    volume_before = v_before.mean()
    volume_after = v_after.mean()
    volume_ratio = round(volume_after / volume_before, 2) if volume_before > 0 else float('nan')

    return EventImpactResult(
        ticker=ticker,
        event_text=event_text,
        event_date=event_date,
        days_before=len(p_before),
        days_after=len(p_after),
        clipped=clipped,
        point_return_pct=round(point_return_pct, 2),
        avg_return_pct=round(avg_return_pct, 2),
        car_pct=round(car_pct, 2),
        vol_before_pct=round(vol_before_pct, 3),
        vol_after_pct=round(vol_after_pct, 3),
        vol_ratio=vol_ratio,
        volume_before=round(volume_before),
        volume_after=round(volume_after),
        volume_ratio=volume_ratio,
    )


def analyze_event_impact(
        ticker: str,
        event_date: str | pd.Timestamp,
        params: EventImpactParams,
        event_text: str = '',
        neighbor_dates: Optional[list] = None,
) -> Optional[EventImpactResult]:
    """
    Рассчитывает метрики влияния одного события на котировки акции.

    Параметры:
        ticker:         тикер акции (например, 'LKOH')
        event_date:     дата события (ключевая дата — начало события)
        params:         параметры анализа (окно, baseline, CPI и др.)
        event_text:     текстовое описание события
        neighbor_dates: список дат соседних событий для адаптивного обрезания окна;
                        если None — используется полное окно params.window

    Возвращает:
        EventImpactResult или None, если данных недостаточно для расчёта
    """
    event_date = pd.Timestamp(event_date)
    candles = get_candles(ticker)
    price, vol_series, t_days, baseline_daily = _prepare_analysis_context(candles, params)

    return _compute_event_metrics(
        ticker, event_date, event_text,
        price, vol_series, t_days, baseline_daily,
        params, neighbor_dates,
    )


def analyze_events_impact(
        ticker: str,
        events: pd.DataFrame,
        params: EventImpactParams,
        date_col: str = 'date_start',
        text_col: str = 'event',
) -> list[Optional[EventImpactResult]]:
    """
    Батч-анализ влияния списка событий на котировки акции.

    Все даты событий автоматически используются как neighbor_dates для адаптивного обрезания окна.

    Параметры:
        ticker:   тикер акции (например, 'LKOH')
        events:   DataFrame с событиями
        params:   параметры анализа
        date_col: название колонки с датой события (по умолчанию 'date_start')
        text_col: название колонки с текстом события (по умолчанию 'event')

    Возвращает:
        Список EventImpactResult (или None для событий с недостаточными данными),
        в том же порядке, что и строки events.
    """
    candles = get_candles(ticker)
    price, vol_series, t_days, baseline_daily = _prepare_analysis_context(candles, params)

    neighbor_dates = pd.to_datetime(events[date_col]).tolist()

    results = []
    for _, row in events.iterrows():
        result = _compute_event_metrics(
            ticker=ticker,
            event_date=pd.Timestamp(row[date_col]),
            event_text=row.get(text_col, ''),
            price=price,
            vol_series=vol_series,
            t_days=t_days,
            baseline_daily=baseline_daily,
            params=params,
            neighbor_dates=neighbor_dates,
        )
        results.append(result)

    return results
