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


# ── /api/event-study/sensitivity (индивидуальный перебор параметров) ─────────

class SensitivityGrid(CamelModel):
    windows: list[int]
    models: list[str]
    estimation_windows: list[int]


class EventStudySensitivityRequest(CamelModel):
    ticker: str
    event_date: str  # ISO: YYYY-MM-DD
    grid: SensitivityGrid


class SensitivityCell(CamelModel):
    window: int
    model: str
    estimation: int
    available: bool          # False — у события не хватает истории под это оценочное окно
    car: float
    baseline_down: float     # нижняя граница нормы (5-й перцентиль псевдо-CAR)
    baseline_up: float       # верхняя граница нормы (95-й перцентиль)
    signed_rank: float       # где CAR в знаковом распределении нормы (0..1)
    is_anomaly_signed: bool  # CAR вне нормы (signed_rank вне [0.05, 0.95])


class EventStudySensitivityResponse(CamelModel):
    cells: list[SensitivityCell]
