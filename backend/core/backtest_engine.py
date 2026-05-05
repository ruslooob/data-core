"""Движок бэктеста: один прогон стратегии в одном окружении.

Архитектура (после переезда на Postgres):
- Коннект psycopg к Postgres (autocommit=False, чтобы TEMP TABLE жили
  до конца сессии). Один коннект = одна сессия = один прогон.
- Runtime-таблицы (`run_context`, `portfolio_state`, `portfolio_positions`,
  `trade_journal`, `equity_curve`) — TEMP TABLE, видны только этой сессии.
  Стратегии и движок обращаются к ним без префикса. Persistent-таблицы
  (`tagged_events`, `events`, и т.п.) видны через обычный JOIN.
- TA-функции (`car`, `vol_ratio`, `volume_ratio`, `close_price`, `open_price`,
  `volume`, `sma`, `volume_sma`, `volatility`, `return_n_days`, `avg_price`)
  живут в Postgres как plpython3u-функции (см. `scripts/init_postgres_*_udfs.py`).
- No-lookahead — через session-GUC `backtest.max_date`. Перед триггерной
  фазой движок выставляет `max_date = tick - 1`, перед исполнением и
  переоценкой — `tick`. UDF читают этот GUC и фильтруют котировки по нему.
- Пользовательские SQL-параметры `:tick` / `:ticker` приводятся к `$1`/`$2`
  и параметру по имени. См. `_normalize_named_params`.
"""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import psycopg

from core.dividend_data_provider import DividendDataProvider
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider

DIVIDEND_RULE_NAME = '*dividend*'

# Регулярка для замены `:name` → `%(name)s` (psycopg named params).
# Lookbehind на `:` исключает `::CAST` (его в Postgres всё равно нет, но на всякий).
_NAMED_PARAM_RE = re.compile(r'(?<!:):([A-Za-z_][A-Za-z0-9_]*)')


def _normalize_named_params(sql: str) -> str:
    return _NAMED_PARAM_RE.sub(r'%(\1)s', sql)


_PARAM_USAGE_RE = re.compile(r'%\(([A-Za-z_][A-Za-z0-9_]*)\)s')


def _filter_params(sql: str, params: dict) -> dict:
    used = set(_PARAM_USAGE_RE.findall(sql))
    return {k: v for k, v in params.items() if k in used}


def _annualize_return(total_return_pct: float, date_start: date, date_end: date) -> float:
    days = (date_end - date_start).days
    if days <= 0:
        return 0.0
    years = days / 365.25
    growth_factor = 1.0 + total_return_pct / 100.0
    if growth_factor <= 0:
        return 0.0
    return (growth_factor ** (1.0 / years) - 1.0) * 100.0


@dataclass
class RuleSpec:
    id: str
    name: str
    trigger_sql: str
    action_type: str
    action_quantity_sql: str
    priority: int


@dataclass
class StrategySpec:
    id: str
    name: str
    rules: list[RuleSpec]


@dataclass
class EnvironmentSpec:
    id: str
    name: str
    date_start: date
    date_end: date
    starting_capital: float


@dataclass
class TradeRecord:
    trade_date: date
    ticker: str
    type: str
    quantity: int
    price: float
    rule_name: str
    pnl_realized: float | None


@dataclass
class BacktestResult:
    strategy_id: str
    environment_id: str
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    n_trades: int
    profit_factor: float | None
    win_rate_pct: float | None
    trades: list[TradeRecord]
    equity_curve: list[tuple[date, float]]


_RUNTIME_TABLES = (
    'run_context',
    'portfolio_state',
    'portfolio_positions',
    'trade_journal',
    'equity_curve',
)


class BacktestEngine:
    """Один прогон одной стратегии в одном окружении.

    Принимает свой psycopg-коннект; полностью владеет им (закрывать
    обязан caller через engine.close()). Все runtime-таблицы создаются
    как TEMP в этой сессии — приватны, удалятся автоматически при
    закрытии коннекта.
    """

    def __init__(
            self,
            strategy: StrategySpec,
            environment: EnvironmentSpec,
            con: psycopg.Connection,
            logger,
    ):
        self.strategy = strategy
        self.environment = environment
        self.con = con
        self.logger = logger

        # Провайдер для календаря (без max_date) — нужен для списка торговых
        # дней IMOEX. Чтения котировок при бэктесте идут через UDF в Postgres.
        self._market = MarketDataProvider()
        self._dividend_payments = DividendDataProvider().load_payments_by_date()

        self._create_runtime_tables()
        self._init_portfolio()

    # ── Runtime-схема ──────────────────────────────────────────────────────
    # `_cleanup_runtime` НЕ нужен: каждый прогон открывает свой psycopg-коннект
    # (см. backtest_worker.py), его TEMP-схема пустая. DROP без квалификатора
    # был бы опасен — Postgres резолвил бы имя на persistent-таблицу
    # `public.trade_journal` и удалил её.

    def _create_runtime_tables(self) -> None:
        # ON COMMIT PRESERVE ROWS — таблица переживает COMMIT, удалится
        # только при DISCARD/закрытии сессии.
        self.con.execute("""
            CREATE TEMP TABLE run_context (
                current_tick     DATE,
                index            INTEGER,
                date_start       DATE,
                date_end         DATE,
                starting_capital DOUBLE PRECISION
            ) ON COMMIT PRESERVE ROWS
        """)
        self.con.execute("""
            CREATE TEMP TABLE portfolio_state (
                cash   DOUBLE PRECISION NOT NULL,
                equity DOUBLE PRECISION NOT NULL
            ) ON COMMIT PRESERVE ROWS
        """)
        # Используем serial id чтобы можно было удалять конкретный лот при FIFO-sell.
        self.con.execute("""
            CREATE TEMP TABLE portfolio_positions (
                lot_id     SERIAL PRIMARY KEY,
                ticker     VARCHAR NOT NULL,
                quantity   INTEGER NOT NULL,
                buy_price  DOUBLE PRECISION NOT NULL,
                buy_date   DATE NOT NULL
            ) ON COMMIT PRESERVE ROWS
        """)
        self.con.execute("""
            CREATE TEMP TABLE trade_journal (
                trade_id      SERIAL PRIMARY KEY,
                trade_date    DATE    NOT NULL,
                ticker        VARCHAR NOT NULL,
                type          VARCHAR NOT NULL CHECK (type IN ('buy', 'sell', 'dividend')),
                quantity      INTEGER NOT NULL,
                price         DOUBLE PRECISION NOT NULL,
                rule_name     VARCHAR NOT NULL,
                pnl_realized  DOUBLE PRECISION
            ) ON COMMIT PRESERVE ROWS
        """)
        self.con.execute("""
            CREATE TEMP TABLE equity_curve (
                tick_date DATE   NOT NULL,
                equity    DOUBLE PRECISION NOT NULL
            ) ON COMMIT PRESERVE ROWS
        """)
        self.con.commit()

    def _init_portfolio(self) -> None:
        capital = float(self.environment.starting_capital)
        self.con.execute(
            "INSERT INTO run_context VALUES (NULL, 0, %s, %s, %s)",
            [self.environment.date_start, self.environment.date_end, capital],
        )
        self.con.execute(
            "INSERT INTO portfolio_state VALUES (%s, %s)", [capital, capital],
        )
        self.con.commit()

    # ── max_date GUC для no-lookahead ──────────────────────────────────────

    def _set_max_date(self, d: date | None) -> None:
        """Выставляет session-GUC backtest.max_date. None → пустая строка
        (UDF трактуют как «вся история», но в бэктесте всегда задан)."""
        value = d.isoformat() if d is not None else ''
        self.con.execute("SELECT set_config('backtest.max_date', %s, false)", [value])

    # ── Главный цикл ───────────────────────────────────────────────────────

    def run(
            self,
            on_progress=None,
            should_cancel=None,
    ) -> BacktestResult | None:
        trading_days = self._compute_trading_days()
        if not trading_days:
            raise ValueError(
                f'Нет торговых дней в периоде {self.environment.date_start}..{self.environment.date_end}',
            )
        total = len(trading_days)

        for index, tick in enumerate(trading_days):
            if should_cancel is not None and should_cancel():
                return None

            self._update_run_context(tick, index)
            prev_date = trading_days[index - 1] if index > 0 else None

            # Триггер и quantity-фаза: данные строго до tick (исключительно).
            # Если prev_date None (первый тик) — задаём день до первого тика
            # как дату-минус-1, чтобы UDF гарантированно отдавали NULL.
            if prev_date is not None:
                self._set_max_date(prev_date)
            else:
                self._set_max_date(date(1990, 1, 1))
            candidates = self._collect_candidates(tick)

            if candidates:
                self.logger.debug(
                    f'tick {index + 1:04d} {tick} candidates',
                    n=len(candidates),
                )

            # Исполнение и переоценка: данные включают tick.
            self._set_max_date(tick)
            self._execute_candidates(candidates, tick)
            self._reprice_equity(tick)
            self._apply_dividends(tick)
            self.con.commit()

            state = self.con.execute(
                'SELECT cash, equity FROM portfolio_state',
            ).fetchone()
            positions = self.con.execute(
                'SELECT COUNT(DISTINCT ticker) FROM portfolio_positions',
            ).fetchone()[0]
            self.logger.debug(
                f'tick {index + 1:04d} {tick} end',
                equity=round(float(state[1]), 2),
                cash=round(float(state[0]), 2),
                positions=int(positions),
            )

            if on_progress is not None:
                n_trades = self.con.execute(
                    'SELECT COUNT(*) FROM trade_journal',
                ).fetchone()[0]
                on_progress({
                    'progress': (index + 1) / total,
                    'current_tick': tick.isoformat(),
                    'current_equity': float(state[1]) if state else 0.0,
                    'n_trades_so_far': int(n_trades),
                })

        return self._compute_result()

    def _compute_trading_days(self) -> list[date]:
        prices = self._market.load_market_index_prices()
        mask = (prices.index >= pd.Timestamp(self.environment.date_start)) & \
               (prices.index <= pd.Timestamp(self.environment.date_end))
        return [ts.date() for ts in prices.index[mask]]

    def _update_run_context(self, tick: date, index: int) -> None:
        self.con.execute(
            "UPDATE run_context SET current_tick = %s, index = %s",
            [tick, index],
        )

    # ── Сбор кандидатов ────────────────────────────────────────────────────

    def _collect_candidates(self, tick: date) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for rule in self.strategy.rules:
            trigger_sql = _normalize_named_params(rule.trigger_sql)
            quantity_sql = _normalize_named_params(rule.action_quantity_sql)
            try:
                trigger_rows = self.con.execute(
                    trigger_sql, _filter_params(trigger_sql, {'tick': tick}),
                ).fetchall()
            except psycopg.Error as e:
                self.con.rollback()
                self.logger.debug(
                    'trigger error', tick=tick, rule=rule.name, error=str(e),
                )
                continue
            tickers = [r[0] for r in trigger_rows if r and r[0] is not None]
            if not tickers:
                self.logger.debug(
                    'trigger empty', tick=tick, rule=rule.name,
                )
            for ticker in tickers:
                try:
                    qty_row = self.con.execute(
                        quantity_sql,
                        _filter_params(quantity_sql, {'tick': tick, 'ticker': ticker}),
                    ).fetchone()
                except psycopg.Error as e:
                    self.con.rollback()
                    self.logger.debug(
                        'candidate dropped', tick=tick, rule=rule.name,
                        ticker=ticker, reason='quantity_error', error=str(e),
                    )
                    continue
                if qty_row is None or qty_row[0] is None:
                    self.logger.debug(
                        'candidate dropped', tick=tick, rule=rule.name,
                        ticker=ticker, reason='quantity_null',
                    )
                    continue
                try:
                    quantity = int(qty_row[0])
                except (TypeError, ValueError):
                    self.logger.debug(
                        'candidate dropped', tick=tick, rule=rule.name,
                        ticker=ticker, reason='quantity_not_int',
                        value=str(qty_row[0]),
                    )
                    continue
                if quantity <= 0:
                    self.logger.debug(
                        'candidate dropped', tick=tick, rule=rule.name,
                        ticker=ticker, reason='quantity_zero', quantity=quantity,
                    )
                    continue
                candidates.append({
                    'ticker': str(ticker),
                    'type': rule.action_type,
                    'quantity': quantity,
                    'priority': rule.priority,
                    'rule_name': rule.name,
                })
        candidates.sort(key=lambda c: -c['priority'])
        return candidates

    # ── Исполнение кандидатов ──────────────────────────────────────────────

    def _execute_candidates(self, candidates: list[dict[str, Any]], tick: date) -> None:
        for cand in candidates:
            if cand['type'] == 'buy':
                self._execute_buy(cand, tick)
            else:
                self._execute_sell(cand, tick)

    def _open_price(self, ticker: str, d: date) -> float | None:
        """Берёт open_price через Postgres-UDF (с учётом session GUC max_date)."""
        row = self.con.execute(
            'SELECT open_price(%s, %s)', [ticker, d],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def _close_price(self, ticker: str, d: date) -> float | None:
        row = self.con.execute(
            'SELECT close_price(%s, %s)', [ticker, d],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def _execute_buy(self, cand: dict[str, Any], tick: date) -> None:
        price = self._open_price(cand['ticker'], tick)
        if price is None or price <= 0:
            self.logger.warn(
                'buy skipped: no open price',
                ticker=cand['ticker'], date=tick.isoformat(),
            )
            return
        cash = self.con.execute('SELECT cash FROM portfolio_state').fetchone()[0]
        affordable = int(float(cash) // price)
        actual = min(cand['quantity'], affordable)
        if actual <= 0:
            self.logger.warn(
                'buy skipped: insufficient cash',
                ticker=cand['ticker'], requested=cand['quantity'],
                affordable=affordable, cash=round(float(cash), 2),
            )
            return
        cost = actual * price
        self.con.execute(
            'INSERT INTO portfolio_positions (ticker, quantity, buy_price, buy_date) '
            'VALUES (%s, %s, %s, %s)',
            [cand['ticker'], actual, price, tick],
        )
        self.con.execute(
            'UPDATE portfolio_state SET cash = cash - %s', [cost],
        )
        self.con.execute(
            'INSERT INTO trade_journal (trade_date, ticker, type, quantity, price, rule_name, pnl_realized) '
            'VALUES (%s, %s, %s, %s, %s, %s, NULL)',
            [tick, cand['ticker'], 'buy', actual, price, cand['rule_name']],
        )
        self.logger.debug(
            'trade buy',
            ticker=cand['ticker'], qty=actual, price=round(price, 2),
            fill_ratio=round(actual / cand['quantity'], 2),
            rule=cand['rule_name'],
        )

    def _execute_sell(self, cand: dict[str, Any], tick: date) -> None:
        price = self._open_price(cand['ticker'], tick)
        if price is None or price <= 0:
            return
        lots = self.con.execute(
            'SELECT lot_id, quantity, buy_price FROM portfolio_positions '
            'WHERE ticker = %s ORDER BY buy_date ASC, lot_id ASC',
            [cand['ticker']],
        ).fetchall()
        total_held = sum(l[1] for l in lots)
        if total_held <= 0:
            return
        actual = min(cand['quantity'], total_held)

        remaining = actual
        pnl_total = 0.0
        for lot_id, qty, buy_price in lots:
            if remaining <= 0:
                break
            take = min(qty, remaining)
            pnl_total += take * (price - float(buy_price))
            new_qty = qty - take
            if new_qty == 0:
                self.con.execute(
                    'DELETE FROM portfolio_positions WHERE lot_id = %s', [lot_id],
                )
            else:
                self.con.execute(
                    'UPDATE portfolio_positions SET quantity = %s WHERE lot_id = %s',
                    [new_qty, lot_id],
                )
            remaining -= take

        proceeds = actual * price
        self.con.execute(
            'UPDATE portfolio_state SET cash = cash + %s', [proceeds],
        )
        self.con.execute(
            'INSERT INTO trade_journal (trade_date, ticker, type, quantity, price, rule_name, pnl_realized) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            [tick, cand['ticker'], 'sell', actual, price, cand['rule_name'], pnl_total],
        )
        self.logger.debug(
            'trade sell',
            ticker=cand['ticker'], qty=actual, price=round(price, 2),
            pnl=round(pnl_total, 2), rule=cand['rule_name'],
        )

    # ── Дивиденды ──────────────────────────────────────────────────────────

    def _apply_dividends(self, tick: date) -> None:
        positions = self.con.execute(
            'SELECT ticker, SUM(quantity) FROM portfolio_positions GROUP BY ticker',
        ).fetchall()
        for ticker, total_qty in positions:
            div_per_share = self._dividend_payments.get((tick, ticker))
            if div_per_share is None or total_qty is None or total_qty <= 0:
                continue
            payout = float(div_per_share) * int(total_qty)
            self.con.execute(
                'UPDATE portfolio_state SET cash = cash + %s, equity = equity + %s',
                [payout, payout],
            )
            self.con.execute(
                'INSERT INTO trade_journal (trade_date, ticker, type, quantity, price, rule_name, pnl_realized) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                [tick, ticker, 'dividend', int(total_qty), float(div_per_share),
                 DIVIDEND_RULE_NAME, payout],
            )
            self.logger.info(
                'dividend payout',
                ticker=ticker, qty=int(total_qty),
                per_share=float(div_per_share), payout=round(payout, 2),
            )
            self.con.execute(
                'UPDATE equity_curve SET equity = equity + %s WHERE tick_date = %s',
                [payout, tick],
            )

    # ── Переоценка equity и запись точки кривой ────────────────────────────

    def _reprice_equity(self, tick: date) -> None:
        # Один SQL вместо цикла по lots: GROUP BY ticker + один close_price-call
        # на тикер. Без этого на стратегиях типа «buy 1 каждый день» к концу
        # прогона тысячи лотов одного тикера → тысячи round-trip'ов на тик.
        row = self.con.execute(
            """
            SELECT s.cash + COALESCE((
                SELECT SUM(p.total_qty * close_price(p.ticker, %(tick)s))
                FROM (
                    SELECT ticker, SUM(quantity) AS total_qty
                    FROM portfolio_positions
                    GROUP BY ticker
                ) p
            ), 0) AS equity
            FROM portfolio_state s
            """,
            {'tick': tick},
        ).fetchone()
        equity = float(row[0]) if row and row[0] is not None else float(
            self.con.execute('SELECT cash FROM portfolio_state').fetchone()[0],
        )
        self.con.execute(
            'UPDATE portfolio_state SET equity = %s', [equity],
        )
        self.con.execute(
            'INSERT INTO equity_curve VALUES (%s, %s)', [tick, equity],
        )

    # ── Расчёт метрик и формирование результата ────────────────────────────

    def _compute_result(self) -> BacktestResult:
        starting = float(self.environment.starting_capital)
        equity_rows = self.con.execute(
            'SELECT tick_date, equity FROM equity_curve ORDER BY tick_date',
        ).fetchall()
        equity_curve = [(d, float(e)) for d, e in equity_rows]

        if not equity_curve:
            final_equity = starting
        else:
            final_equity = equity_curve[-1][1]

        total_return_pct = (final_equity - starting) / starting * 100.0
        annual_return_pct = _annualize_return(
            total_return_pct, self.environment.date_start, self.environment.date_end,
        )

        peak = starting
        max_dd = 0.0
        for _, eq in equity_curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        max_drawdown_pct = max_dd * 100.0

        if len(equity_curve) > 1:
            eq_series = pd.Series([e for _, e in equity_curve])
            daily_ret = eq_series.pct_change().dropna()
            if len(daily_ret) > 1 and daily_ret.std(ddof=1) > 0:
                sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (252.0 ** 0.5))
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        trade_rows = self.con.execute(
            'SELECT trade_date, ticker, type, quantity, price, rule_name, pnl_realized '
            'FROM trade_journal ORDER BY trade_date, trade_id',
        ).fetchall()
        trades = [
            TradeRecord(
                trade_date=r[0], ticker=r[1], type=r[2], quantity=int(r[3]),
                price=float(r[4]), rule_name=r[5],
                pnl_realized=float(r[6]) if r[6] is not None else None,
            )
            for r in trade_rows
        ]
        n_trades = len(trades)
        sells = [t for t in trades if t.type == 'sell' and t.pnl_realized is not None]
        if sells:
            wins = sum(1 for t in sells if t.pnl_realized > 0)
            win_rate_pct = wins / len(sells) * 100.0
            gains = sum(t.pnl_realized for t in sells if t.pnl_realized > 0)
            losses = -sum(t.pnl_realized for t in sells if t.pnl_realized < 0)
            profit_factor = gains / losses if losses > 0 else None
        else:
            win_rate_pct = None
            profit_factor = None

        return BacktestResult(
            strategy_id=self.strategy.id,
            environment_id=self.environment.id,
            total_return_pct=total_return_pct,
            annual_return_pct=annual_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            sharpe=sharpe,
            n_trades=n_trades,
            profit_factor=profit_factor,
            win_rate_pct=win_rate_pct,
            trades=trades,
            equity_curve=equity_curve,
        )

    def close(self) -> None:
        """TEMP TABLE удалятся при закрытии коннекта; здесь только rollback
        возможной незакрытой транзакции и сброс GUC."""
        try:
            self.con.execute("RESET backtest.max_date")
            self.con.commit()
        except psycopg.Error:
            try:
                self.con.rollback()
            except psycopg.Error:
                pass


# ── Загрузка спецификаций из Postgres ──────────────────────────────────────

def load_strategy_spec(con, strategy_id: str) -> StrategySpec:
    s_row = con.execute(
        'SELECT id, name FROM strategies WHERE id = %s', [strategy_id],
    ).fetchone()
    if s_row is None:
        raise ValueError(f'Стратегия {strategy_id} не найдена')
    rule_rows = con.execute(
        'SELECT r.id, r.name, r.trigger_sql, r.action_type, r.action_quantity_sql, r.priority '
        'FROM strategy_rules sr '
        'JOIN rules r ON r.id = sr.rule_id '
        'WHERE sr.strategy_id = %s '
        'ORDER BY sr.position',
        [strategy_id],
    ).fetchall()
    rules = [
        RuleSpec(
            id=r[0], name=r[1], trigger_sql=r[2],
            action_type=r[3], action_quantity_sql=r[4], priority=int(r[5]),
        )
        for r in rule_rows
    ]
    return StrategySpec(id=s_row[0], name=s_row[1], rules=rules)


def load_environment_spec(con, environment_id: str) -> EnvironmentSpec:
    row = con.execute(
        'SELECT id, name, date_start, date_end, starting_capital '
        'FROM environments WHERE id = %s',
        [environment_id],
    ).fetchone()
    if row is None:
        raise ValueError(f'Окружение {environment_id} не найдено')
    return EnvironmentSpec(
        id=row[0], name=row[1],
        date_start=row[2], date_end=row[3],
        starting_capital=float(row[4]),
    )


def reconstruct_equity_curve(con, result_id: str) -> list[tuple[date, float]]:
    """Восстанавливает equity-кривую прогона из persistent trade_journal +
    рыночных данных. Один проход по торговым дням окружения."""
    env_row = con.execute("""
        SELECT e.date_start, e.date_end, e.starting_capital
        FROM environments e
        JOIN backtest_results br ON br.environment_id = e.id
        WHERE br.id = %s
    """, [result_id]).fetchone()
    if env_row is None:
        return []
    date_start, date_end, starting_capital = env_row

    trades = con.execute("""
        SELECT trade_date, ticker, type, quantity, price
        FROM trade_journal
        WHERE backtest_result_id = %s
        ORDER BY trade_date, id
    """, [result_id]).fetchall()

    market = MarketDataProvider()
    prices = market.load_market_index_prices()
    mask = (prices.index >= pd.Timestamp(date_start)) & (prices.index <= pd.Timestamp(date_end))
    trading_days = [ts.date() for ts in prices.index[mask]]
    trading_index = pd.DatetimeIndex([pd.Timestamp(d) for d in trading_days])

    stocks = StockDataProvider()
    unique_tickers = {str(t[1]) for t in trades}
    candles_by_ticker: dict[str, pd.Series] = {}
    for t in unique_tickers:
        try:
            df = stocks.get_candles(t)
            closes = df.set_index('DATE')['CLOSE']
            candles_by_ticker[t] = closes.reindex(trading_index, method='ffill')
        except ValueError:
            candles_by_ticker[t] = pd.Series(dtype=float)

    cash = float(starting_capital)
    lots: dict[str, list[tuple[int, float]]] = {}
    curve: list[tuple[date, float]] = []
    trade_idx = 0

    for tick in trading_days:
        while trade_idx < len(trades) and trades[trade_idx][0] <= tick:
            _td, ticker, ttype, qty, price = trades[trade_idx]
            ticker = str(ticker)
            qty = int(qty)
            price = float(price)
            if ttype == 'buy':
                cash -= qty * price
                lots.setdefault(ticker, []).append((qty, price))
            elif ttype == 'sell':
                cash += qty * price
                remaining = qty
                ticker_lots = lots.get(ticker, [])
                while remaining > 0 and ticker_lots:
                    lot_qty, lot_price = ticker_lots[0]
                    take = min(lot_qty, remaining)
                    if take == lot_qty:
                        ticker_lots.pop(0)
                    else:
                        ticker_lots[0] = (lot_qty - take, lot_price)
                    remaining -= take
            elif ttype == 'dividend':
                cash += qty * price
            trade_idx += 1

        market_value = 0.0
        ts_tick = pd.Timestamp(tick)
        for ticker, ticker_lots in lots.items():
            total_qty = sum(l[0] for l in ticker_lots)
            if total_qty == 0:
                continue
            closes = candles_by_ticker.get(ticker)
            if closes is None or ts_tick not in closes.index:
                continue
            close = closes.loc[ts_tick]
            if pd.isna(close):
                continue
            market_value += total_qty * float(close)

        curve.append((tick, cash + market_value))

    return curve


def persist_backtest_result(
        con,
        result: BacktestResult,
        research_id: str,
) -> str:
    """Сохраняет BacktestResult в persistent: backtest_results + trade_journal.
    `research_id` — обязательное поле; прогон всегда принадлежит исследованию.
    Возвращает id новой записи backtest_results."""
    result_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    con.execute(
        'INSERT INTO backtest_results '
        '(id, strategy_id, environment_id, created_at, total_return_pct, '
        ' annual_return_pct, max_drawdown_pct, sharpe, n_trades, profit_factor, '
        ' win_rate_pct, research_id) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [
            result_id, result.strategy_id, result.environment_id, created_at,
            float(result.total_return_pct), float(result.annual_return_pct),
            float(result.max_drawdown_pct), float(result.sharpe),
            int(result.n_trades),
            float(result.profit_factor) if result.profit_factor is not None else None,
            float(result.win_rate_pct) if result.win_rate_pct is not None else None,
            research_id,
        ],
    )
    for trade in result.trades:
        con.execute(
            'INSERT INTO trade_journal VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [
                str(uuid.uuid4()), result_id, trade.trade_date, trade.ticker,
                trade.type, int(trade.quantity), float(trade.price),
                trade.rule_name,
                float(trade.pnl_realized) if trade.pnl_realized is not None else None,
            ],
        )
    return result_id
