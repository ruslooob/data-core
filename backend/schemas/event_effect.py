"""DTO для эндпоинтов Event Effect Analysis (две вкладки виджета)."""
from schemas._common import CamelModel


# ── /api/event-effect/individual ────────────────────────────────────────────

class EventEffectParams(CamelModel):
    window: int  # симметричное окно (event_window = (-N, N))
    model: str   # 'mean_adjusted' | 'market_model' | 'capm'
    estimation_window: int


class EventEffectIndividualRequest(CamelModel):
    ticker: str
    event_ids: list[str]
    params: EventEffectParams
    central_statistic: str  # 'median' | 'mean'


class IndividualCarRow(CamelModel):
    event_id: str
    date: str
    car: float
    rank: float
    is_anomaly: bool
    baseline_band: float
    signed_rank: float
    is_anomaly_signed: bool
    baseline_up: float
    baseline_down: float


class ExcludedEventRow(CamelModel):
    event_id: str
    reason: str


class IndividualForecast(CamelModel):
    central: float
    pi_lower: float
    pi_upper: float
    n: int
    shapiro_p_value: float | None


class EventEffectIndividualResponse(CamelModel):
    individual_cars: list[IndividualCarRow]
    excluded_events: list[ExcludedEventRow]
    forecast: IndividualForecast | None


# ── /api/event-effect/aggregate-sensitivity ─────────────────────────────────

class AggregateSensitivityGrid(CamelModel):
    windows: list[int]
    models: list[str]
    estimation_windows: list[int]


class EventEffectAggregateSensitivityRequest(CamelModel):
    ticker: str
    event_ids: list[str]
    grid: AggregateSensitivityGrid


class AggregateSensitivityCell(CamelModel):
    window: int
    model: str
    estimation: int
    car: float
    p_value: float
    n: int
    mean_rank: float
    rank_p_value: float


class EventEffectAggregateSensitivityResponse(CamelModel):
    cells: list[AggregateSensitivityCell]
    excluded_events_by_estimation: dict[str, list[str]]
