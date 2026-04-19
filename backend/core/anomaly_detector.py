"""
Автоматический поиск аномалий Level 1: анализ одного события.

Детектирует: значимый CAR, всплеск объёма, рост волатильности,
признаки инсайдерской торговли (CAR до t=0 за пределами ДИ).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from core.event_study import EventStudy, EventStudyResult, ModelType


# ---------------------------------------------------------------------------
# Результат
# ---------------------------------------------------------------------------

@dataclass
class AnomalyFlag:
    """Одна обнаруженная аномалия."""
    code: str          # машинное имя: significant_car, volume_spike, vol_spike, pre_event_car
    label: str         # человеческое название
    severity: float    # 0..1, чем выше — тем аномальнее
    detail: str        # подробное описание


@dataclass
class AnomalyResult:
    """Результат проверки одного события на аномалии."""
    event_date: str          # ISO дата
    ticker: str
    flags: list[AnomalyFlag] = field(default_factory=list)
    car_pct: float = 0.0
    vol_ratio: float = 0.0
    volume_ratio: float = 0.0
    anomaly_score: float = 0.0  # суммарный балл аномальности (0..1)


# ---------------------------------------------------------------------------
# Детектор
# ---------------------------------------------------------------------------

def detect_anomalies(
    ticker: str,
    event_date: date,
    candles: pd.DataFrame,
    study: EventStudy,
    model: ModelType,
    event_window: tuple[int, int],
    estimation_window: int,
    *,
    market: pd.Series | None = None,
    rf: pd.Series | None = None,
    outlier_threshold: float | None = None,
    volume_threshold: float = 1.5,
    vol_threshold: float = 2.0,
) -> AnomalyResult | None:
    """
    Проверяет одно событие на аномалии Level 1.

    Параметры:
        ticker:             тикер акции
        event_date:         дата события
        candles:            DataFrame с колонками DATE, CLOSE, VOL
        study:              экземпляр EventStudy с логдоходностями
        model:              тип модели
        event_window:       событийное окно (-N, +M)
        estimation_window:  длина оценочного окна
        market, rf:         для market_model / capm
        outlier_threshold:  порог фильтрации выбросов
        volume_threshold:   порог volume_ratio для флага (по умолчанию 1.5)
        vol_threshold:      порог vol_ratio для флага (по умолчанию 2.0)

    Возвращает AnomalyResult или None если анализ не удался.
    """
    result = study.analyze(
        event_date=event_date,
        model=model,
        event_window=event_window,
        estimation_window=estimation_window,
        market=market,
        rf=rf,
        outlier_threshold=outlier_threshold,
    )
    if result is None:
        return None

    flags: list[AnomalyFlag] = []

    # --- 1. Значимый CAR: вышел за ±2σ√N ---
    n_days = len(result.ar)
    sigma = result.estimation_std
    ci_bound = 2 * sigma * np.sqrt(n_days) if sigma > 0 else 0
    car_pct = result.car * 100

    if ci_bound > 0 and abs(result.car) > ci_bound:
        severity = min(1.0, abs(result.car) / ci_bound / 3)
        direction = "рост" if result.car > 0 else "падение"
        flags.append(AnomalyFlag(
            code="significant_car",
            label="Значимый CAR",
            severity=severity,
            detail=f"CAR={car_pct:+.2f}% выходит за ±2σ√N ({ci_bound*100:.2f}%). "
                   f"Направление: {direction}.",
        ))

    # --- 2-3. Волатильность и объём (до vs после t=0) ---
    ew_start, ew_end = event_window
    days_before = abs(ew_start)

    vol_ratio, volume_ratio = _compute_ratios(
        candles, event_date, days_before, ew_end,
    )

    if volume_ratio > volume_threshold:
        severity = min(1.0, (volume_ratio - 1) / 3)
        flags.append(AnomalyFlag(
            code="volume_spike",
            label="Всплеск объёма",
            severity=severity,
            detail=f"Объём после события в {volume_ratio:.1f}x выше, чем до (порог {volume_threshold}x).",
        ))

    if vol_ratio > vol_threshold:
        severity = min(1.0, (vol_ratio - 1) / 4)
        flags.append(AnomalyFlag(
            code="vol_spike",
            label="Рост волатильности",
            severity=severity,
            detail=f"Волатильность после события в {vol_ratio:.1f}x выше (порог {vol_threshold}x).",
        ))

    # --- 4. Инсайдерская торговля: CAR до t=0 за пределами ДИ ---
    if days_before >= 3 and sigma > 0:
        ar_before = result.ar[:days_before]
        car_before = float(np.sum(ar_before))
        ci_before = 2 * sigma * np.sqrt(days_before)
        if abs(car_before) > ci_before:
            severity = min(1.0, abs(car_before) / ci_before / 2)
            flags.append(AnomalyFlag(
                code="pre_event_car",
                label="Движение до события",
                severity=severity,
                detail=f"CAR до t=0 = {car_before*100:+.2f}%, за пределами ±2σ√N "
                       f"({ci_before*100:.2f}%). Возможный инсайд.",
            ))

    anomaly_score = min(1.0, sum(f.severity for f in flags) / max(len(flags), 1))

    return AnomalyResult(
        event_date=event_date.isoformat(),
        ticker=ticker,
        flags=flags,
        car_pct=car_pct,
        vol_ratio=vol_ratio,
        volume_ratio=volume_ratio,
        anomaly_score=anomaly_score,
    )


def detect_anomalies_batch(
    ticker: str,
    event_dates: list[date],
    candles: pd.DataFrame,
    study: EventStudy,
    model: ModelType,
    event_window: tuple[int, int],
    estimation_window: int,
    *,
    market: pd.Series | None = None,
    rf: pd.Series | None = None,
    outlier_threshold: float | None = None,
) -> list[AnomalyResult]:
    """
    Батч-проверка всех событий тикера. Возвращает список отсортированный
    по anomaly_score (самые аномальные — первые).
    """
    results: list[AnomalyResult] = []
    for ed in event_dates:
        r = detect_anomalies(
            ticker=ticker,
            event_date=ed,
            candles=candles,
            study=study,
            model=model,
            event_window=event_window,
            estimation_window=estimation_window,
            market=market,
            rf=rf,
            outlier_threshold=outlier_threshold,
        )
        if r is not None:
            results.append(r)

    results.sort(key=lambda x: x.anomaly_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _compute_ratios(
    candles: pd.DataFrame,
    event_date: date,
    days_before: int,
    days_after: int,
) -> tuple[float, float]:
    """Вычисляет vol_ratio и volume_ratio вокруг event_date."""
    if candles.empty:
        return 1.0, 1.0

    dates = pd.to_datetime(candles["DATE"])
    t0 = pd.Timestamp(event_date)
    idx0 = dates.searchsorted(t0, side="left")

    before_slice = candles.iloc[max(0, idx0 - days_before): idx0]
    after_slice = candles.iloc[idx0: min(len(candles), idx0 + days_after + 1)]

    if before_slice.empty or after_slice.empty:
        return 1.0, 1.0

    # Волатильность: std дневных доходностей
    close_before = before_slice["CLOSE"].values
    close_after = after_slice["CLOSE"].values

    ret_before = np.diff(close_before) / close_before[:-1] if len(close_before) > 1 else np.array([0.0])
    ret_after = np.diff(close_after) / close_after[:-1] if len(close_after) > 1 else np.array([0.0])

    std_before = float(np.std(ret_before)) if len(ret_before) > 0 else 1e-9
    std_after = float(np.std(ret_after)) if len(ret_after) > 0 else 0.0
    vol_ratio = std_after / std_before if std_before > 1e-9 else 1.0

    # Объём: средний дневной
    vol_before = float(before_slice["VOL"].mean()) if len(before_slice) > 0 else 1.0
    vol_after = float(after_slice["VOL"].mean()) if len(after_slice) > 0 else 0.0
    volume_ratio = vol_after / vol_before if vol_before > 0 else 1.0

    return round(vol_ratio, 2), round(volume_ratio, 2)
