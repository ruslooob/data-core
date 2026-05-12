"""Эндпоинты event-study: одиночный и агрегированный."""
from datetime import date

from fastapi import APIRouter, HTTPException

from core.event_study import EventStudy
from routers._common import dividends, market, stocks
from schemas.event_study import (
    AggregateStudyRequest,
    AggregateStudyResponse,
    EventStudyRequest,
    EventStudyResponse,
)

router = APIRouter()


@router.post("/api/event-study", response_model_by_alias=True)
def run_event_study(req: EventStudyRequest) -> EventStudyResponse:
    """Рассчитывает AR и CAR для одного события."""
    stock_log_returns = stocks.get_log_returns(req.ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()

    study = EventStudy(stock_log_returns=stock_log_returns)
    result = study.analyze(
        event_date=date.fromisoformat(req.event_date),
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market_log_returns,
        rf=rf,
        outlier_threshold=req.outlier_threshold,
    )

    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Недостаточно данных для анализа (слишком ранняя дата или короткая история котировок)",
        )

    return EventStudyResponse(
        event_date=result.event_date.isoformat(),
        ar=result.ar,
        car=result.car,
        n_days=result.n_days,
        estimation_std=result.estimation_std,
        outliers_removed=result.outliers_removed,
    )


@router.post("/api/event-study/aggregate", response_model_by_alias=True)
def run_aggregate_study(req: AggregateStudyRequest) -> AggregateStudyResponse:
    """Агрегированный event study: средний CAR по всем событиям тикера."""
    stock_log_returns = stocks.get_log_returns(req.ticker)
    market_log_returns = market.load_market_index_log_returns()
    rf = market.load_daily_risk_free_rate()

    events = dividends.load_dividends()
    event_dates = [e.event_date for e in events if e.ticker == req.ticker.upper()]

    study = EventStudy(stock_log_returns=stock_log_returns)
    result = study.analyze_aggregate(
        event_dates=event_dates,
        model=req.model,
        event_window=req.event_window,
        estimation_window=req.estimation_window,
        market=market_log_returns,
        rf=rf,
        outlier_threshold=req.outlier_threshold,
    )

    if result is None:
        raise HTTPException(status_code=400, detail="Не удалось проанализировать ни одно событие")

    return AggregateStudyResponse(
        n_events=result.n_events,
        mean_car=result.mean_car,
        cumulative_mean_car=result.cumulative_mean_car,
        t_stat=result.t_stat,
        p_value=result.p_value,
        individual_cars=result.individual_cars,
        event_dates=result.event_dates,
    )
