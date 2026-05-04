"""Тесты бэктест-движка на Postgres-стеке.

Перед запуском должны быть установлены persistent-UDF:
    python scripts/init_postgres_udfs.py
    python scripts/init_postgres_backtest_udfs.py

И в `data/db` миграция котировок:
    python scripts/migrate_stocks_to_postgres.py
    python scripts/migrate_duckdb_to_postgres.py

Тесты НЕ удаляют данные из persistent — они открывают свой psycopg-коннект
с TEMP TABLE и работают только в нём.

Покрытие:
- buy-and-hold: одна покупка, держим, equity растёт по close.
- buy-each-day: триггер срабатывает каждый торговый день, в т.ч. понедельник
  (регрессия для бага DuckDB-движка, см. историю миграции).
- FIFO sell: продаются самые старые лоты первыми, pnl_realized считается верно.
- close_price forward-fill на нерабочий день.
- _reprice_equity: правильно считает equity при множестве лотов одного тикера.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg
import pytest

from core.backtest_engine import (
    BacktestEngine, EnvironmentSpec, RuleSpec, StrategySpec,
)
from core.postgres_db import PG_DSN


PERIOD_START = date(2010, 1, 11)   # понедельник, есть свечи у LKOH
PERIOD_END = date(2010, 2, 12)     # пятница, маленькое окно для тестов
STARTING_CAPITAL = 1_000_000.0


class _SilentLogger:
    """Заглушка BacktestLogger: ничего не пишет, не падает на любых полях."""
    def info(self, *_a, **_k): pass
    def debug(self, *_a, **_k): pass
    def warn(self, *_a, **_k): pass
    def error(self, *_a, **_k): pass
    def close(self): pass


def _env(period_start=PERIOD_START, period_end=PERIOD_END,
         capital=STARTING_CAPITAL, name='TEST_ENV') -> EnvironmentSpec:
    return EnvironmentSpec(
        id='test-env',
        name=name,
        date_start=period_start,
        date_end=period_end,
        starting_capital=capital,
    )


def _strategy(rules: list[RuleSpec], name='TEST_STRATEGY') -> StrategySpec:
    return StrategySpec(id='test-strat', name=name, rules=rules)


@pytest.fixture()
def con():
    """Свежий коннект на каждый тест. autocommit=False чтобы TEMP TABLE
    жили до конца сессии (и закрывались вместе с коннектом)."""
    c = psycopg.connect(PG_DSN, autocommit=False)
    yield c
    try:
        c.rollback()
    except Exception:
        pass
    c.close()


def _run(con, rules, period_start=PERIOD_START, period_end=PERIOD_END,
         capital=STARTING_CAPITAL):
    engine = BacktestEngine(
        strategy=_strategy(rules),
        environment=_env(period_start, period_end, capital),
        con=con,
        logger=_SilentLogger(),
    )
    try:
        result = engine.run()
    finally:
        engine.close()
    return result


# ── 1. buy-and-hold: на 2-м тике покупает по close-вчера, дальше держит ──
# Контракт no-lookahead: в trigger/quantity-фазе доступны данные до tick-1
# включительно. Поэтому quantity вычисляем через close_price(:tick - 1) —
# это формальный proxy на «оценку капитала перед открытием рынка». На
# первом тике (index=0) prev_date = None, любые UDF возвращают NULL —
# поэтому стратегия должна стартовать с index=1.

def test_buy_and_hold_lkoh(con):
    rules = [RuleSpec(
        id='r1', name='buy-once',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE (SELECT index FROM run_context) = 1"
        ),
        action_type='buy',
        action_quantity_sql=(
            "SELECT FLOOR(s.cash / close_price('LKOH', :tick - 1)) "
            "FROM portfolio_state s"
        ),
        priority=10,
    )]
    result = _run(con, rules)
    buys = [t for t in result.trades if t.type == 'buy']
    sells = [t for t in result.trades if t.type == 'sell']
    assert len(buys) == 1, f'ждали 1 buy, получили {len(buys)}'
    assert len(sells) == 0
    # Сделка на втором торговом дне окружения.
    assert buys[0].trade_date == result.equity_curve[1][0]
    assert result.n_trades == 1


# ── 2. buy each day: триггер срабатывает каждый торговый день ──
# Регрессия: в старом DuckDB-движке систематически пропускались понедельники
# в первые годы (2002–2005). Здесь проверяем что Postgres-движок покупает
# каждый торговый день включая понедельники.

def test_buy_each_day_no_weekday_skips(con):
    rules = [RuleSpec(
        id='r1', name='buy-1-each-day',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE cash >= close_price('LKOH', :tick - 1)"
        ),
        action_type='buy',
        action_quantity_sql='SELECT 1',
        priority=10,
    )]
    # Берём окно с известными понедельниками: 2010-01-11..2010-02-12 (5 пнд).
    result = _run(con, rules, period_start=date(2010, 1, 11), period_end=date(2010, 2, 12))
    # Первый торговый день — триггер пустой (prev_date is None → max_date 1990).
    # На последующих тиках должен покупать каждый день.
    n_trading_days = len(result.equity_curve)
    n_buys = sum(1 for t in result.trades if t.type == 'buy')
    # Ожидаем покупки на (N-1) тиках: первый пропускается из-за no-lookahead.
    assert n_buys == n_trading_days - 1, (
        f'buys={n_buys}, trading_days={n_trading_days}, '
        f'ожидали buys = trading_days - 1'
    )
    # Среди покупок должны быть понедельники.
    monday_buys = [t for t in result.trades
                   if t.type == 'buy' and t.trade_date.weekday() == 0]
    assert monday_buys, 'не нашлось ни одной покупки в понедельник — регрессия!'


# ── 3. FIFO sell: старые лоты продаются первыми ──

def test_fifo_sell_pnl_calculation(con):
    # Стратегия: 5 дней покупаем по 1 LKOH, на 6-й продаём 3 акции.
    # Должны продаться лоты дней 1, 2, 3 — самые старые. PnL рассчитывается
    # против их buy_price.
    rules = [
        RuleSpec(
            id='r-buy', name='buy-1-each',
            trigger_sql=(
                "SELECT 'LKOH' AS ticker FROM portfolio_state "
                "WHERE (SELECT index FROM run_context) BETWEEN 1 AND 5"
            ),
            action_type='buy',
            action_quantity_sql='SELECT 1',
            priority=10,
        ),
        RuleSpec(
            id='r-sell', name='sell-3-on-day-6',
            trigger_sql=(
                "SELECT 'LKOH' AS ticker FROM portfolio_state "
                "WHERE (SELECT index FROM run_context) = 6"
            ),
            action_type='sell',
            action_quantity_sql='SELECT 3',
            priority=20,
        ),
    ]
    result = _run(con, rules,
                  period_start=date(2010, 1, 11), period_end=date(2010, 1, 25))
    sells = [t for t in result.trades if t.type == 'sell']
    buys = [t for t in result.trades if t.type == 'buy']
    assert len(sells) == 1, f'ждали 1 sell, получили {len(sells)}'
    assert sells[0].quantity == 3
    assert sells[0].pnl_realized is not None
    # PnL = (sell_price * 3) - сумма (buy_price[i]) для i=1..3 (FIFO).
    sell_price = sells[0].price
    expected_pnl = sell_price * 3 - sum(b.price for b in buys[:3])
    assert abs(sells[0].pnl_realized - expected_pnl) < 1e-6


# ── 4. close_price forward-fill ──

def test_close_price_forward_fill_on_weekend(con):
    """На вторнике 2010-01-19 (index=1) max_date = понедельник 2010-01-18.
    close_price('LKOH', '2010-01-17') (воскресенье, нет торгов) должна
    вернуться close пятницы 2010-01-15 через forward-fill.
    """
    rules = [RuleSpec(
        id='r1', name='check-fwd-fill',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE close_price('LKOH', DATE '2010-01-17') "
            "    = close_price('LKOH', DATE '2010-01-15')"
            "  AND (SELECT index FROM run_context) = 1"
        ),
        action_type='buy',
        action_quantity_sql='SELECT 1',
        priority=10,
    )]
    # Окно начинается с понедельника 2010-01-18, чтобы на index=1 (вторник)
    # max_date был равен 2010-01-18, и close_price для воскресенья
    # 2010-01-17 был в пределах max_date.
    result = _run(con, rules,
                  period_start=date(2010, 1, 18), period_end=date(2010, 1, 25))
    assert len(result.trades) == 1, (
        'forward-fill close_price не работает: на воскресенье 2010-01-17 '
        'должна вернуться пятничная цена 2010-01-15'
    )


# ── 5. _reprice_equity на множестве лотов одного тикера ──

def test_reprice_equity_with_many_lots(con):
    """Регрессия: до фикса _reprice_equity делал отдельный SELECT close_price
    на каждый лот, что было O(N) round-trip'ов. После фикса — один SQL
    с GROUP BY ticker. Проверяем что equity численно совпадает с ожидаемым.
    """
    rules = [RuleSpec(
        id='r1', name='buy-1-each',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE cash >= close_price('LKOH', :tick - 1)"
        ),
        action_type='buy',
        action_quantity_sql='SELECT 1',
        priority=10,
    )]
    result = _run(con, rules,
                  period_start=date(2010, 1, 11), period_end=date(2010, 2, 12))
    # На последнем тике equity = cash + qty_total × close(last_tick)
    last_date, last_equity = result.equity_curve[-1]
    n_buys = sum(1 for t in result.trades if t.type == 'buy')

    # Получаем цены из БД отдельно для проверки.
    other = psycopg.connect(PG_DSN, autocommit=True)
    with other.cursor() as cur:
        cur.execute(
            "SELECT close FROM stock_candles WHERE ticker = 'LKOH' "
            "AND candle_date <= %s ORDER BY candle_date DESC LIMIT 1",
            [last_date],
        )
        last_close = float(cur.fetchone()[0])
    other.close()

    # Сумма потраченного на buy + остаток cash должно ≈ starting_capital.
    spent = sum(t.price * t.quantity for t in result.trades if t.type == 'buy')
    cash_left = STARTING_CAPITAL - spent
    expected_equity = cash_left + n_buys * last_close
    assert abs(last_equity - expected_equity) < 1e-2, (
        f'equity={last_equity}, expected={expected_equity}, '
        f'разница {abs(last_equity - expected_equity)}'
    )


# ── 6. No-lookahead на первом тике: open_price(:tick) и close_price(:tick) NULL ──
# Регрессия: в DuckDB-движке на первом тике prev_date был None, и
# StockDataProvider создавался без max_date — вся история была видна,
# что нарушало no-lookahead. Postgres-движок честно ставит max_date в
# далёкое прошлое (1990-01-01), чтобы все TA-UDF возвращали NULL.

def test_no_lookahead_on_first_tick(con):
    """Trigger срабатывает на первом тике (index=0), но open_price(:tick)
    и close_price(:tick - 1) обязаны вернуть NULL. quantity NULL → buy
    отбрасывается. n_trades должно быть 0."""
    rules = [RuleSpec(
        id='r1', name='try-buy-on-first-tick',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE (SELECT index FROM run_context) = 0"
        ),
        action_type='buy',
        action_quantity_sql=(
            "SELECT FLOOR(s.cash / open_price('LKOH', :tick)) "
            "FROM portfolio_state s"
        ),
        priority=10,
    )]
    result = _run(con, rules)
    buys = [t for t in result.trades if t.type == 'buy']
    assert len(buys) == 0, (
        f'на первом тике с open_price(:tick) в quantity не должно быть '
        f'покупок (no-lookahead), получено {len(buys)}'
    )


# ── 7. open_price строго по дате (нет торгов — NULL) ──

def test_open_price_strict_match(con):
    """open_price на нерабочий день возвращает NULL — в отличие от
    close_price (forward-fill)."""
    rules = [RuleSpec(
        id='r1', name='check-open-strict',
        trigger_sql=(
            "SELECT 'LKOH' AS ticker FROM portfolio_state "
            "WHERE open_price('LKOH', DATE '2010-01-17') IS NULL "
            "  AND close_price('LKOH', DATE '2010-01-17') IS NOT NULL "
            "  AND (SELECT index FROM run_context) = 1"
        ),
        action_type='buy',
        action_quantity_sql='SELECT 1',
        priority=10,
    )]
    result = _run(con, rules,
                  period_start=date(2010, 1, 18), period_end=date(2010, 1, 25))
    assert len(result.trades) == 1, (
        'open_price должен вернуть NULL для воскресенья, '
        'close_price — пятничную цену (forward-fill)'
    )


# ── 8. Sell больше, чем есть в портфеле — берёт всё что есть ──

def test_sell_more_than_held_takes_everything(con):
    rules = [
        RuleSpec(
            id='r-buy', name='buy-2',
            trigger_sql=(
                "SELECT 'LKOH' FROM portfolio_state "
                "WHERE (SELECT index FROM run_context) = 1"
            ),
            action_type='buy',
            action_quantity_sql='SELECT 2',
            priority=10,
        ),
        RuleSpec(
            id='r-sell', name='try-sell-100',
            trigger_sql=(
                "SELECT 'LKOH' FROM portfolio_state "
                "WHERE (SELECT index FROM run_context) = 5"
            ),
            action_type='sell',
            action_quantity_sql='SELECT 100',
            priority=20,
        ),
    ]
    result = _run(con, rules,
                  period_start=date(2010, 1, 11), period_end=date(2010, 1, 25))
    sells = [t for t in result.trades if t.type == 'sell']
    assert len(sells) == 1
    assert sells[0].quantity == 2, (
        'sell должен взять всё что есть (2 акции), не больше'
    )
