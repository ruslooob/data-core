"""DTO для бэктест-эндпоинтов: запуск прогона, прогресс, результаты."""
from schemas._common import CamelModel
from schemas.environments import EnvironmentOut
from schemas.strategies import StrategyOut


class BacktestRunRequest(CamelModel):
    strategy_id: str
    environment_id: str
    research_id: str


class TradeRecordOut(CamelModel):
    trade_date: str
    ticker: str
    type: str
    quantity: int
    price: float
    rule_name: str
    pnl_realized: float | None


class BacktestResultOut(CamelModel):
    id: str
    strategy_id: str
    environment_id: str
    created_at: str
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    n_trades: int
    profit_factor: float | None
    win_rate_pct: float | None


class BacktestResultDetailOut(BacktestResultOut):
    trades: list[TradeRecordOut]
    equity_curve: list[dict]  # [{ date, equity }]
    strategy: StrategyOut | None = None
    environment: EnvironmentOut | None = None


class BacktestRunStartedOut(CamelModel):
    run_id: str
    status: str  # 'running'


class BacktestProgressOut(CamelModel):
    run_id: str
    strategy_id: str
    environment_id: str
    status: str  # 'running' | 'done' | 'error' | 'cancelled'
    progress: float  # 0..1
    current_date: str | None
    current_equity: float | None
    n_trades_so_far: int
    done: bool
    result_id: str | None  # появляется при status='done'
    error_message: str | None
