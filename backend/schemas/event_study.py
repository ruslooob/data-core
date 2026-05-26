"""DTO для event-study эндпоинтов."""
from schemas._common import CamelModel


class EventStudyRequest(CamelModel):
    ticker: str
    event_date: str  # ISO format: YYYY-MM-DD
    model: str  # 'mean_adjusted', 'market_model', 'capm'
    event_window: tuple[int, int]  # (-10, 10)
    estimation_window: int  # 200
    outlier_threshold: float | None = None  # σ-порог фильтрации выбросов


class EventStudyResponse(CamelModel):
    event_date: str
    ar: list[float]
    car: float
    n_days: int
    estimation_std: float
    estimation_dates: list[str]
    estimation_actual: list[float]
    estimation_predicted: list[float]
    outliers_removed: int
    r_squared: float
    estimation_residual_sigmas: list[float]
    car_cumulative: list[float]
    ci_band: list[float]


class AggregateStudyRequest(CamelModel):
    ticker: str
    model: str
    event_window: tuple[int, int]
    estimation_window: int
    outlier_threshold: float | None = None


class AggregateStudyResponse(CamelModel):
    n_events: int
    mean_car: list[float]
    cumulative_mean_car: float
    t_stat: float
    p_value: float
    individual_cars: list[float]
    event_dates: list[str]
