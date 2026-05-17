"""Эндпоинты Event Effect Analysis: индивидуальные CAR + sensitivity."""
from fastapi import APIRouter, HTTPException

from core.event_effect import calculate_individual, calculate_sensitivity
from routers._common import get_pg, market, stocks
from schemas.event_effect import (
    EventEffectIndividualRequest,
    EventEffectIndividualResponse,
    EventEffectSensitivityRequest,
    EventEffectSensitivityResponse,
    ExcludedEventRow,
    IndividualCarRow,
    IndividualForecast,
    SensitivityCell,
)

router = APIRouter()


@router.post("/api/event-effect/individual", response_model_by_alias=True)
def post_individual(req: EventEffectIndividualRequest) -> EventEffectIndividualResponse:
    """Индивидуальные CAR + 95% предсказательный интервал для вкладки Events CAR Explorer."""
    if req.central_statistic not in ('median', 'mean'):
        raise HTTPException(status_code=400, detail="central_statistic должен быть 'median' или 'mean'")

    con = get_pg()
    result = calculate_individual(
        ticker=req.ticker,
        event_ids=req.event_ids,
        window=req.params.window,
        model=req.params.model,
        estimation_window=req.params.estimation_window,
        central_statistic=req.central_statistic,
        con=con,
        stocks=stocks,
        market=market,
    )

    return EventEffectIndividualResponse(
        individual_cars=[
            IndividualCarRow(
                event_id=ic.event_id, date=ic.date, car=ic.car,
                rank=ic.rank, is_anomaly=ic.is_anomaly, noise_band=ic.noise_band,
            )
            for ic in result.individual_cars
        ],
        excluded_events=[
            ExcludedEventRow(event_id=ex.event_id, reason=ex.reason)
            for ex in result.excluded_events
        ],
        forecast=IndividualForecast(
            central=result.forecast.central,
            pi_lower=result.forecast.pi_lower,
            pi_upper=result.forecast.pi_upper,
            n=result.forecast.n,
            shapiro_p_value=result.forecast.shapiro_p_value,
        ) if result.forecast is not None else None,
    )


@router.post("/api/event-effect/sensitivity", response_model_by_alias=True)
def post_sensitivity(req: EventEffectSensitivityRequest) -> EventEffectSensitivityResponse:
    """Heatmap CAR/p-value по сетке параметров для вкладки CAR Sensitivity Analysis."""
    grid = req.grid
    if not grid.windows or not grid.models or not grid.estimation_windows:
        raise HTTPException(status_code=400, detail="Сетка должна содержать хотя бы одно значение по каждой оси")

    con = get_pg()
    result = calculate_sensitivity(
        ticker=req.ticker,
        event_ids=req.event_ids,
        windows=grid.windows,
        models=grid.models,
        estimation_windows=grid.estimation_windows,
        con=con,
        stocks=stocks,
        market=market,
    )

    return EventEffectSensitivityResponse(
        cells=[
            SensitivityCell(
                window=c.window, model=c.model, estimation=c.estimation,
                car=c.car, p_value=c.p_value, n=c.n,
                mean_rank=c.mean_rank, rank_p_value=c.rank_p_value,
            )
            for c in result.cells
        ],
        excluded_events_by_estimation=result.excluded_events_by_estimation,
    )
