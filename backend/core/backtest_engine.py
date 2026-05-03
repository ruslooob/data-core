"""Движок бэктеста: один прогон стратегии в окружении.

Концепция полностью описана в `docs/drafts/BACKTEST_GLOSSARY_DRAFT.md`.
Этот модуль реализует MVP — главный цикл по тикам, частичное исполнение
с FIFO-списанием лотов, расчёт 7 метрик.

Архитектура MVP:
    - Движок работает на **существующем** соединении к `data-core.duckdb`,
      переданном сверху. DuckDB на Windows не даёт двум коннектам открыть
      один файл (даже READ_ONLY), поэтому изоляция через `:memory:`+ATTACH
      из драфта пока недоступна — отложено до полноценной реализации
      многопоточности.
    - Runtime-таблицы создаются с префиксом `runtime_` (`run_context`,
      `portfolio_state`, ..., `equity_curve`). После прогона
      они дропаются.
    - На каждом тике пересоздаётся `StockDataProvider(max_date=:tick - 1)`,
      UDF читают `self._stocks` динамически — поэтому достаточно один раз
      зарегистрировать UDF и подменять провайдера.
    - В пользовательских SQL триггерах используется `:tick`/`:ticker` как
      именованные параметры — DuckDB ожидает `$tick`/`$ticker`, поэтому
      препроцессор `_normalize_named_params` делает замену перед execute.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import duckdb
import pandas as pd

# DuckDB ожидает именованные параметры в форме `$name`, а драфт PQL фиксирует
# синтаксис `:name` (унаследован от Postgres-стиля). Препроцессор заменяет
# `:name` на `$name` перед `con.execute(...)`. Lookbehind на `:` отсекает
# `::DATE` — DuckDB-cast — чтобы не сломать его.
_NAMED_PARAM_RE = re.compile(r'(?<!:):([A-Za-z_][A-Za-z0-9_]*)')


def _normalize_named_params(sql: str) -> str:
    return _NAMED_PARAM_RE.sub(r'$\1', sql)


_PARAM_USAGE_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')


def _filter_params(sql: str, params: dict) -> dict:
    """Возвращает подмножество params, которое реально упомянуто в SQL.

    DuckDB строго проверяет соответствие именованных параметров: если передать
    неиспользуемый параметр — `Parameter argument/count mismatch`.
    """
    used = set(_PARAM_USAGE_RE.findall(sql))
    return {k: v for k, v in params.items() if k in used}

from core.dividend_data_provider import DividendDataProvider
from core.market_data_provider import MarketDataProvider
from core.stock_data_provider import StockDataProvider

DIVIDEND_RULE_NAME = '*dividend*'

_DB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'db')
APP_DB_PATH = os.path.abspath(os.path.join(_DB_DIR, 'data-core.duckdb'))


@dataclass
class RuleSpec:
    """Спецификация правила, как её даёт persistent-таблица `rules`."""
    id: str
    name: str
    trigger_sql: str
    action_type: str  # 'buy' | 'sell'
    action_quantity_sql: str
    priority: int


@dataclass
class StrategySpec:
    id: str
    name: str
    rules: list[RuleSpec]  # упорядочены по `position`


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
    type: str  # 'buy' | 'sell'
    quantity: int
    price: float
    rule_name: str
    pnl_realized: float | None  # только у sell


@dataclass
class BacktestResult:
    """Возвращается из `BacktestEngine.run()`."""
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
_RUNTIME_UDFS = ('_close_price', '_open_price', '_volume', '_avg_price', '_volume_ratio')
_RUNTIME_MACROS = ('close_price', 'open_price', 'volume', 'avg_price', 'volume_ratio')


class BacktestEngine:
    """Один прогон одной стратегии в одном окружении.

    Движок работает на **переданном сверху** соединении (или курсоре) к
    persistent-БД. Это вынужденная архитектура MVP — см. модуль-docstring.
    """

    def __init__(
            self,
            strategy: StrategySpec,
            environment: EnvironmentSpec,
            con,
            logger=None,
    ):
        self.strategy = strategy
        self.environment = environment
        self.con = con
        self.logger = logger

        self._market = MarketDataProvider()  # без max_date — нужен только календарь IMOEX
        self._stocks: StockDataProvider | None = None  # пересоздаётся на каждом тике

        # Дивидендные выплаты: карта (payment_date, ticker) → dividend_per_share.
        # Загружается один раз на старте прогона; max_date не выставляем, т.к.
        # обращение к карте происходит по конкретной дате-тику и не зависит от
        # «прошлого/будущего» — это рыночная механика, не лук-аhead.
        self._dividend_payments = DividendDataProvider().load_payments_by_date()

        self._cleanup_runtime()  # на случай остатков от предыдущего прогона
        self._create_runtime_tables()
        self._init_portfolio()

    # ── Runtime-схема ──────────────────────────────────────────────────────

    def _cleanup_runtime(self) -> None:
        for tbl in _RUNTIME_TABLES:
            try:
                self.con.execute(f'DROP TABLE IF EXISTS {tbl}')
            except duckdb.Error:
                pass
        for fn in _RUNTIME_UDFS:
            try:
                self.con.remove_function(fn)
            except (duckdb.CatalogException, duckdb.InvalidInputException):
                pass
        for macro in _RUNTIME_MACROS:
            try:
                self.con.execute(f'DROP MACRO IF EXISTS {macro}')
            except duckdb.Error:
                pass

    def _create_runtime_tables(self) -> None:
        self.con.execute("""
            CREATE TABLE run_context (
                current_date     DATE,
                index            INTEGER,
                date_start       DATE,
                date_end         DATE,
                starting_capital DOUBLE
            )
        """)
        self.con.execute("""
            CREATE TABLE portfolio_state (
                cash   DOUBLE NOT NULL,
                equity DOUBLE NOT NULL
            )
        """)
        self.con.execute("""
            CREATE TABLE portfolio_positions (
                ticker     VARCHAR NOT NULL,
                quantity   INTEGER NOT NULL,
                buy_price  DOUBLE  NOT NULL,
                buy_date   DATE    NOT NULL
            )
        """)
        self.con.execute("""
            CREATE TABLE trade_journal (
                trade_date    DATE    NOT NULL,
                ticker        VARCHAR NOT NULL,
                type          VARCHAR NOT NULL,
                quantity      INTEGER NOT NULL,
                price         DOUBLE  NOT NULL,
                rule_name     VARCHAR NOT NULL,
                pnl_realized  DOUBLE,
                CHECK (type IN ('buy', 'sell', 'dividend'))
            )
        """)
        self.con.execute("""
            CREATE TABLE equity_curve (
                tick_date DATE   NOT NULL,
                equity    DOUBLE NOT NULL
            )
        """)

    def _init_portfolio(self) -> None:
        capital = float(self.environment.starting_capital)
        self.con.execute(
            "INSERT INTO run_context VALUES (NULL, 0, ?, ?, ?)",
            [self.environment.date_start, self.environment.date_end, capital],
        )
        self.con.execute(
            "INSERT INTO portfolio_state VALUES (?, ?)", [capital, capital],
        )

    # ── UDF: TA-функции, регистрируемые с актуальным max_date-провайдером ───

    def _register_udfs(self) -> None:
        """Зарегистрировать (или перерегистрировать) TA-функции для текущего тика.

        Перед регистрацией снимаем старые версии — иначе DuckDB бросит
        CatalogException "function already exists".
        """
        for name in (
                '_close_price', '_open_price', '_volume',
                '_avg_price', '_volume_ratio',
        ):
            try:
                self.con.remove_function(name)
            except (duckdb.CatalogException, duckdb.InvalidInputException):
                pass

        self.con.create_function(
            '_close_price', self._close_price, ['VARCHAR', 'DATE'], 'DOUBLE',
            null_handling='special',
        )
        self.con.create_function(
            '_open_price', self._open_price, ['VARCHAR', 'DATE'], 'DOUBLE',
            null_handling='special',
        )
        self.con.create_function(
            '_volume', self._volume, ['VARCHAR', 'DATE'], 'DOUBLE',
            null_handling='special',
        )
        self.con.create_function(
            '_avg_price', self._avg_price, ['VARCHAR'], 'DOUBLE',
            null_handling='special',
        )
        self.con.create_function(
            '_volume_ratio', self._volume_ratio,
            ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER'], 'DOUBLE',
            null_handling='special',
        )

        # Макросы — короткие синонимы и значения по умолчанию.
        for macro in ('close_price', 'open_price', 'volume', 'avg_price', 'volume_ratio'):
            try:
                self.con.execute(f"DROP MACRO IF EXISTS {macro}")
            except duckdb.Error:
                pass

        self.con.execute(
            "CREATE MACRO close_price(ticker, d) AS _close_price(ticker, d)"
        )
        self.con.execute(
            "CREATE MACRO open_price(ticker, d) AS _open_price(ticker, d)"
        )
        self.con.execute(
            "CREATE MACRO volume(ticker, d) AS _volume(ticker, d)"
        )
        self.con.execute(
            "CREATE MACRO avg_price(ticker) AS _avg_price(ticker)"
        )
        self.con.execute(
            "CREATE MACRO volume_ratio(ticker, d, window_before := 5, window_after := 5) "
            "AS _volume_ratio(ticker, d, window_before, window_after)"
        )

    # ── Реализация TA-функций (Python) ─────────────────────────────────────

    def _close_price(self, ticker: str, d: date) -> float | None:
        return self._point_price(ticker, d, 'CLOSE')

    def _open_price(self, ticker: str, d: date) -> float | None:
        return self._point_price(ticker, d, 'OPEN')

    def _volume(self, ticker: str, d: date) -> float | None:
        return self._point_price(ticker, d, 'VOL')

    def _point_price(self, ticker: str | None, d: date | None, col: str) -> float | None:
        if ticker is None or d is None or self._stocks is None:
            return None
        try:
            df = self._stocks.get_candles(ticker, normalized=True)
        except (ValueError, FileNotFoundError, OSError):
            return None
        target = pd.Timestamp(d)
        row = df.loc[df['DATE'] == target]
        if row.empty:
            return None
        return float(row.iloc[0][col])

    def _avg_price(self, ticker: str | None) -> float | None:
        if ticker is None:
            return None
        row = self.con.execute(
            "SELECT SUM(quantity * buy_price) / SUM(quantity) FROM portfolio_positions "
            "WHERE ticker = ?",
            [ticker],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def _volume_ratio(
            self, ticker: str | None, d: date | None,
            window_before: int, window_after: int,
    ) -> float | None:
        if self._stocks is None:
            return None
        return self._stocks.volume_ratio(ticker, d, int(window_before), int(window_after))

    # ── Главный цикл ───────────────────────────────────────────────────────

    def run(
            self,
            on_progress=None,
            should_cancel=None,
    ) -> BacktestResult | None:
        """Главный цикл прогона.

        Параметры:
            on_progress: callable(progress_dict) — вызывается раз в тик.
                Получает dict по Q23: progress (0..1), current_date,
                current_equity, n_trades_so_far. Дросселирование оставлено
                на сторону caller'а.
            should_cancel: callable() -> bool. Если вернёт True — цикл
                прерывается на ближайшем тике, run() возвращает None.
        """
        trading_days = self._compute_trading_days()
        if not trading_days:
            raise ValueError(
                f'Нет торговых дней в периоде {self.environment.date_start}..{self.environment.date_end}'
            )
        total = len(trading_days)

        for index, tick in enumerate(trading_days):
            if should_cancel is not None and should_cancel():
                return None

            self._update_run_context(tick, index)
            prev_date = trading_days[index - 1] if index > 0 else None

            # Триггер и quantity-запрос видят данные строго до tick-1 (no-lookahead).
            self._stocks = StockDataProvider(max_date=prev_date)
            self._register_udfs()
            candidates = self._collect_candidates(tick)

            if self.logger and candidates:
                self.logger.debug(
                    f'tick {index + 1:04d} {tick} candidates',
                    n=len(candidates),
                )

            # Исполнение по open(tick) и переоценка по close(tick) — провайдер,
            # видящий tick. UDF читают self._stocks динамически, так что
            # перерегистрировать их не нужно.
            self._stocks = StockDataProvider(max_date=tick)
            self._execute_candidates(candidates, tick)
            self._reprice_equity(tick)
            # Дивиденды начисляются после переоценки — в конце тика, по факту
            # «деньги пришли». Часть 3.3 драфта.
            self._apply_dividends(tick)

            if self.logger:
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
                state = self.con.execute(
                    'SELECT cash, equity FROM portfolio_state',
                ).fetchone()
                n_trades = self.con.execute(
                    'SELECT COUNT(*) FROM trade_journal',
                ).fetchone()[0]
                on_progress({
                    'progress': (index + 1) / total,
                    'current_date': tick.isoformat() if hasattr(tick, 'isoformat') else str(tick),
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
            "UPDATE run_context SET current_date = ?, index = ?",
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
            except duckdb.Error:
                # Жёсткая ошибка триггера — в MVP пропускаем правило, продолжаем прогон.
                continue
            tickers = [r[0] for r in trigger_rows if r and r[0] is not None]
            for ticker in tickers:
                try:
                    qty_row = self.con.execute(
                        quantity_sql,
                        _filter_params(quantity_sql, {'tick': tick, 'ticker': ticker}),
                    ).fetchone()
                except duckdb.Error:
                    continue
                if qty_row is None or qty_row[0] is None:
                    continue
                try:
                    quantity = int(qty_row[0])
                except (TypeError, ValueError):
                    continue
                if quantity <= 0:
                    continue
                candidates.append({
                    'ticker': str(ticker),
                    'type': rule.action_type,
                    'quantity': quantity,
                    'priority': rule.priority,
                    'rule_name': rule.name,
                })
        # Стабильная сортировка по priority desc, потом по позиции в strategy.rules.
        # Сортировка стабильная — порядок добавления (rule order + ticker order) сохраняется.
        candidates.sort(key=lambda c: -c['priority'])
        return candidates

    # ── Исполнение кандидатов ──────────────────────────────────────────────

    def _execute_candidates(self, candidates: list[dict[str, Any]], tick: date) -> None:
        for cand in candidates:
            if cand['type'] == 'buy':
                self._execute_buy(cand, tick)
            else:
                self._execute_sell(cand, tick)

    def _execute_buy(self, cand: dict[str, Any], tick: date) -> None:
        price = self._open_price(cand['ticker'], tick)
        if price is None or price <= 0:
            if self.logger:
                self.logger.warn(
                    'buy skipped: no open price',
                    ticker=cand['ticker'], date=tick.isoformat(),
                )
            return
        cash = self.con.execute('SELECT cash FROM portfolio_state').fetchone()[0]
        affordable = int(cash // price)
        actual = min(cand['quantity'], affordable)
        if actual <= 0:
            if self.logger:
                self.logger.warn(
                    'buy skipped: insufficient cash',
                    ticker=cand['ticker'], requested=cand['quantity'],
                    affordable=affordable, cash=round(float(cash), 2),
                )
            return
        cost = actual * price
        self.con.execute(
            'INSERT INTO portfolio_positions VALUES (?, ?, ?, ?)',
            [cand['ticker'], actual, price, tick],
        )
        self.con.execute(
            'UPDATE portfolio_state SET cash = cash - ?', [cost],
        )
        self.con.execute(
            'INSERT INTO trade_journal VALUES (?, ?, ?, ?, ?, ?, NULL)',
            [tick, cand['ticker'], 'buy', actual, price, cand['rule_name']],
        )
        if self.logger:
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
        # Все лоты этого тикера, отсортированные FIFO (от самого старого).
        lots = self.con.execute(
            'SELECT rowid, quantity, buy_price, buy_date FROM portfolio_positions '
            'WHERE ticker = ? ORDER BY buy_date ASC, rowid ASC',
            [cand['ticker']],
        ).fetchall()
        total_held = sum(l[1] for l in lots)
        if total_held <= 0:
            return
        actual = min(cand['quantity'], total_held)

        remaining = actual
        pnl_total = 0.0
        for rowid, qty, buy_price, _buy_date in lots:
            if remaining <= 0:
                break
            take = min(qty, remaining)
            pnl_total += take * (price - buy_price)
            new_qty = qty - take
            if new_qty == 0:
                self.con.execute(
                    'DELETE FROM portfolio_positions WHERE rowid = ?', [rowid],
                )
            else:
                self.con.execute(
                    'UPDATE portfolio_positions SET quantity = ? WHERE rowid = ?',
                    [new_qty, rowid],
                )
            remaining -= take

        proceeds = actual * price
        self.con.execute(
            'UPDATE portfolio_state SET cash = cash + ?', [proceeds],
        )
        self.con.execute(
            'INSERT INTO trade_journal VALUES (?, ?, ?, ?, ?, ?, ?)',
            [tick, cand['ticker'], 'sell', actual, price, cand['rule_name'], pnl_total],
        )
        if self.logger:
            self.logger.debug(
                'trade sell',
                ticker=cand['ticker'], qty=actual, price=round(price, 2),
                pnl=round(pnl_total, 2), rule=cand['rule_name'],
            )

    # ── Дивиденды ──────────────────────────────────────────────────────────

    def _apply_dividends(self, tick: date) -> None:
        """Начисляет выплаты дивидендов на конец тика по позициям в портфеле."""
        positions = self.con.execute(
            'SELECT ticker, SUM(quantity) FROM portfolio_positions GROUP BY ticker',
        ).fetchall()
        for ticker, total_qty in positions:
            div_per_share = self._dividend_payments.get((tick, ticker))
            if div_per_share is None or total_qty is None or total_qty <= 0:
                continue
            payout = float(div_per_share) * int(total_qty)
            self.con.execute(
                'UPDATE portfolio_state SET cash = cash + ?, equity = equity + ?',
                [payout, payout],
            )
            self.con.execute(
                'INSERT INTO trade_journal VALUES (?, ?, ?, ?, ?, ?, ?)',
                [tick, ticker, 'dividend', int(total_qty), float(div_per_share),
                 DIVIDEND_RULE_NAME, payout],
            )
            if self.logger:
                self.logger.info(
                    'dividend payout',
                    ticker=ticker, qty=int(total_qty),
                    per_share=float(div_per_share), payout=round(payout, 2),
                )
            # Обновим последнюю точку equity_curve на этом тике, чтобы не было
            # «двойного» состояния — equity уже пересчитано выше, тут просто
            # синхронизируем последнюю точку.
            self.con.execute(
                'UPDATE equity_curve SET equity = equity + ? '
                'WHERE tick_date = ?',
                [payout, tick],
            )

    # ── Переоценка equity и запись точки кривой ────────────────────────────

    def _reprice_equity(self, tick: date) -> None:
        cash = self.con.execute('SELECT cash FROM portfolio_state').fetchone()[0]
        positions = self.con.execute(
            'SELECT ticker, quantity FROM portfolio_positions',
        ).fetchall()
        market_value = 0.0
        for ticker, qty in positions:
            close = self._close_price(ticker, tick)
            if close is not None:
                market_value += qty * close
        equity = float(cash) + market_value
        self.con.execute(
            'UPDATE portfolio_state SET equity = ?', [equity],
        )
        self.con.execute(
            'INSERT INTO equity_curve VALUES (?, ?)', [tick, equity],
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

        # Годовая доходность: нормировка на длину прогона в торговых днях / 252.
        years = max(len(equity_curve), 1) / 252.0
        if years > 0 and starting > 0 and final_equity > 0:
            annual_return_pct = ((final_equity / starting) ** (1.0 / years) - 1.0) * 100.0
        else:
            annual_return_pct = 0.0

        # Просадка
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

        # Sharpe — годовой по дневным доходностям equity (rf=0 для MVP)
        if len(equity_curve) > 1:
            eq_series = pd.Series([e for _, e in equity_curve])
            daily_ret = eq_series.pct_change().dropna()
            if len(daily_ret) > 1 and daily_ret.std(ddof=1) > 0:
                sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * (252.0 ** 0.5))
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        # Журнал сделок и журнальные метрики
        trade_rows = self.con.execute(
            'SELECT trade_date, ticker, type, quantity, price, rule_name, pnl_realized '
            'FROM trade_journal ORDER BY trade_date, rowid',
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
        """Очистить runtime-таблицы и UDF, чтобы не загрязнять persistent-БД."""
        self._cleanup_runtime()


# ── Загрузка спецификаций из persistent-БД ─────────────────────────────────

def load_strategy_spec(con, strategy_id: str) -> StrategySpec:
    """Читает strategy + rules из app-БД (через переданный курсор/коннект)."""
    s_row = con.execute(
        'SELECT id, name FROM strategies WHERE id = ?', [strategy_id],
    ).fetchone()
    if s_row is None:
        raise ValueError(f'Стратегия {strategy_id} не найдена')
    rule_rows = con.execute(
        'SELECT r.id, r.name, r.trigger_sql, r.action_type, r.action_quantity_sql, r.priority '
        'FROM strategy_rules sr '
        'JOIN rules r ON r.id = sr.rule_id '
        'WHERE sr.strategy_id = ? '
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
        'FROM environments WHERE id = ?',
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
    рыночных данных. См. Часть 6.2 драфта (вариант «Не хранить, реконструировать
    при открытии карточки»).

    Алгоритм: один проход по торговым дням окружения; на каждом тике применяем
    все trade_journal-строки с `trade_date <= tick`, держим словарь FIFO-лотов
    по тикерам и cash; equity = cash + Σ(qty × close(tick)).
    """
    env_row = con.execute("""
        SELECT e.date_start, e.date_end, e.starting_capital
        FROM environments e
        JOIN backtest_results br ON br.environment_id = e.id
        WHERE br.id = ?
    """, [result_id]).fetchone()
    if env_row is None:
        return []
    date_start, date_end, starting_capital = env_row

    trades = con.execute("""
        SELECT trade_date, ticker, type, quantity, price
        FROM trade_journal
        WHERE backtest_result_id = ?
        ORDER BY trade_date, rowid
    """, [result_id]).fetchall()

    market = MarketDataProvider()
    prices = market.load_market_index_prices()
    mask = (prices.index >= pd.Timestamp(date_start)) & (prices.index <= pd.Timestamp(date_end))
    trading_days = [ts.date() for ts in prices.index[mask]]

    # Pre-compute close-цены по уникальным тикерам — один pandas-индекс на тикер.
    stocks = StockDataProvider()
    unique_tickers = {str(t[1]) for t in trades}
    candles_by_ticker: dict[str, pd.Series] = {}
    for t in unique_tickers:
        try:
            df = stocks.get_candles(t, normalized=True)
            candles_by_ticker[t] = df.set_index('DATE')['CLOSE']
        except (ValueError, FileNotFoundError, OSError):
            candles_by_ticker[t] = pd.Series(dtype=float)

    cash = float(starting_capital)
    lots: dict[str, list[tuple[int, float]]] = {}
    curve: list[tuple[date, float]] = []
    trade_idx = 0

    for tick in trading_days:
        # Применяем все сделки с датой <= tick.
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
            market_value += total_qty * float(closes.loc[ts_tick])

        curve.append((tick, cash + market_value))

    return curve


def persist_backtest_result(
        con,
        result: BacktestResult,
) -> str:
    """Сохраняет BacktestResult в persistent: backtest_results + trade_journal.
    Возвращает id новой записи backtest_results."""
    result_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    con.execute(
        'INSERT INTO backtest_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            result_id, result.strategy_id, result.environment_id, created_at,
            float(result.total_return_pct), float(result.annual_return_pct),
            float(result.max_drawdown_pct), float(result.sharpe),
            int(result.n_trades),
            float(result.profit_factor) if result.profit_factor is not None else None,
            float(result.win_rate_pct) if result.win_rate_pct is not None else None,
        ],
    )
    for trade in result.trades:
        con.execute(
            'INSERT INTO trade_journal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                str(uuid.uuid4()), result_id, trade.trade_date, trade.ticker,
                trade.type, int(trade.quantity), float(trade.price),
                trade.rule_name,
                float(trade.pnl_realized) if trade.pnl_realized is not None else None,
            ],
        )
    return result_id
