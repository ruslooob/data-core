"""
Анализ влияния события на котировки акции.

Основная функция: analyze_event_impact()
Возвращает EventImpactResult с набором метрик для окна вокруг даты события.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from events_data_core.cpi_data_provider import load_normalized_ipc_data, IpcType
from events_data_core.stock_data_provider import get_stock_data


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

    cpi_type: IpcType = IpcType.GOODS_AND_SERVICES
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


def analyze_event_impact(
        ticker: str,
        event_date: str | pd.Timestamp,
        params: EventImpactParams,
        event_text: str = '',
        neighbor_dates: Optional[list] = None,
) -> Optional[EventImpactResult]:
    """
    Рассчитывает метрики влияния события на котировки акции.

    Параметры:
        ticker:         тикер акции (например, 'LKOH')
        event_date:     дата события (ключевая дата — начало события)
        params:         параметры анализа (окно, baseline, CPI и др.)
        event_text:     текстовое описание события
        neighbor_dates: список дат соседних событий того же типа
                        для адаптивного обрезания окна;
                        если None — используется полное окно params.window

    Возвращает:
        EventImpactResult или None, если данных недостаточно для расчёта
    """
    event_date = pd.Timestamp(event_date)

    # ── 1. Загрузка данных акции ─────────────────────────────────────────
    stock = get_stock_data(ticker)
    stock['DATE'] = pd.to_datetime(stock['DATE'])
    stock = stock.sort_values('DATE').reset_index(drop=True)

    # ── 2. Нормализация по ИПЦ ───────────────────────────────────────────
    if params.normalize_cpi:
        cpi_norm = load_normalized_ipc_data(params.cpi_type, base_year=params.cpi_base_date)
        cpi_norm['date'] = pd.to_datetime(cpi_norm['date'])
        stock = pd.merge_asof(
            stock, cpi_norm[['date', 'real_ruble']],
            left_on='DATE', right_on='date', direction='backward'
        )
        stock['real_ruble'] = stock['real_ruble'].infer_objects(copy=False)
        price = stock.set_index('DATE')['CLOSE'] * stock.set_index('DATE')['real_ruble']
    else:
        price = stock.set_index('DATE')['CLOSE']

    vol_series = stock.set_index('DATE')['VOL']
    t_days = price.index.sort_values()

    # ── 3. Базовая дневная доходность (для CAR) ──────────────────────────
    baseline_idx = t_days[
        (t_days >= params.baseline_start) & (t_days <= params.baseline_end)
    ]
    baseline_returns = price.reindex(baseline_idx).dropna().pct_change().dropna()
    baseline_daily = baseline_returns.mean()

    # ── 4. Границы окна ──────────────────────────────────────────────────
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

    # ── 5. Метрики ────────────────────────────────────────────────────────

    # Доходность точечная
    point_return_pct = (p_after.iloc[-1] - p_before.iloc[0]) / p_before.iloc[0] * 100

    # Доходность средняя
    avg_return_pct = (p_after.mean() - p_before.mean()) / p_before.mean() * 100

    # CAR
    abnormal = p_after.pct_change().dropna() - baseline_daily
    car_pct = abnormal.sum() * 100

    # Волатильность
    vol_before_pct = p_before.pct_change().dropna().std() * 100
    vol_after_pct = p_after.pct_change().dropna().std() * 100
    vol_ratio = round(vol_after_pct / vol_before_pct, 2) if vol_before_pct > 0 else float('nan')

    # Объём
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
