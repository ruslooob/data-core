"""Валидация SQL пользовательских правил при создании.

Q27 драфта бэктеста:
- Trigger SQL и Action.quantity SQL должны быть синтаксически валидными
  на том же диалекте, что и движок (Postgres).
- Action.quantity должен возвращать 1×1 с целым ≥ 0 (или NULL — это
  мягкая ошибка, а не отказ создания).

Подход:
- Открывается одиночный psycopg-коннект (минуя пул), своя сессия,
  autocommit=False. По завершении — rollback + close, никаких побочных
  эффектов в БД.
- В этой сессии создаются TEMP-таблицы движка (run_context, portfolio_state,
  portfolio_positions, trade_journal, equity_curve) с DDL, идентичным
  `backtest_engine._create_runtime_tables`, но с ON COMMIT DROP (мы и так
  не коммитим — это просто страховка).
- Persistent-таблицы и UDF (`events`, `tags`, `event_tags`, `tagged_events`,
  `car`, `vol_ratio`, `volume_ratio`, `close_price`, `open_price`, …) уже
  живут в Postgres — отдельно их подменять не нужно.
- Чтобы реальные UDF никого не задели данными, выставляется GUC
  `backtest.max_date = '1990-01-01'` — все UDF гарантированно вернут NULL.
- Имена параметров `:tick`, `:ticker` подменяются литералами `DATE '2020-01-02'`
  и `'TEST'` (валидируется только синтаксис и контракт).
- Trigger проверяется через `EXPLAIN` (без исполнения).
- Quantity проверяется через реальное `execute` + проверка контракта
  «ровно одна колонка, ≤ 1 строки, целое ≥ 0 или NULL».
"""
from __future__ import annotations

import re

import psycopg

from core.postgres_db import connect


# Названные параметры в правилах — `:tick`, `:ticker`. Для валидации в
# Postgres заменяем их литералами. Негативный lookbehind отсекает `::TYPE`
# (postgres-каст), но не наши плейсхолдеры.
_NAMED_PARAM_RE = re.compile(r'(?<!:):([A-Za-z_][A-Za-z0-9_]*)')


def _substitute_validation_params(sql: str) -> str:
    """Подставляет литералы вместо `:tick`, `:ticker` для Postgres-валидации."""
    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name == 'tick':
            return "DATE '2020-01-02'"
        if name == 'ticker':
            return "'TEST'"
        return m.group(0)
    return _NAMED_PARAM_RE.sub(_sub, sql)


# DDL TEMP-таблиц движка. Должен совпадать с
# `backtest_engine._create_runtime_tables`. ON COMMIT DROP — на случай,
# если кто-то закоммитит сессию валидации (мы не коммитим, но защита).
_RUNTIME_DDL = [
    """
    CREATE TEMP TABLE run_context (
        current_tick     DATE,
        index            INTEGER,
        date_start       DATE,
        date_end         DATE,
        starting_capital DOUBLE PRECISION
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE portfolio_state (
        cash   DOUBLE PRECISION NOT NULL,
        equity DOUBLE PRECISION NOT NULL
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE portfolio_positions (
        lot_id     SERIAL PRIMARY KEY,
        ticker     VARCHAR NOT NULL,
        quantity   INTEGER NOT NULL,
        buy_price  DOUBLE PRECISION NOT NULL,
        buy_date   DATE NOT NULL
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE trade_journal (
        trade_id      SERIAL PRIMARY KEY,
        trade_date    DATE    NOT NULL,
        ticker        VARCHAR NOT NULL,
        type          VARCHAR NOT NULL CHECK (type IN ('buy', 'sell', 'dividend')),
        quantity      INTEGER NOT NULL,
        price         DOUBLE PRECISION NOT NULL,
        rule_name     VARCHAR NOT NULL,
        pnl_realized  DOUBLE PRECISION
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE equity_curve (
        tick_date DATE NOT NULL,
        equity    DOUBLE PRECISION NOT NULL
    ) ON COMMIT DROP
    """,
]


class RuleSqlError(Exception):
    """Сообщение для пользователя; отправляется как 400 detail."""


def _setup_session(con: psycopg.Connection) -> None:
    """Готовит сессию валидации: TEMP-таблицы + одна заполняющая строка +
    `backtest.max_date` в далёкое прошлое, чтобы все UDF возвращали NULL."""
    for ddl in _RUNTIME_DDL:
        con.execute(ddl)
    con.execute(
        "INSERT INTO run_context VALUES "
        "(DATE '2020-01-02', 0, DATE '2020-01-01', DATE '2025-12-31', 1000000)"
    )
    con.execute("INSERT INTO portfolio_state VALUES (1000000, 1000000)")
    con.execute("SELECT set_config('backtest.max_date', '1990-01-01', false)")


def validate_trigger_sql(trigger_sql: str) -> None:
    """Бросает RuleSqlError, если SQL триггера невалиден."""
    sql = _substitute_validation_params(trigger_sql)
    con = connect()
    try:
        _setup_session(con)
        try:
            con.execute(f'EXPLAIN {sql}')
        except psycopg.Error as e:
            raise RuleSqlError(f'Trigger SQL невалиден: {e}') from e
    finally:
        try:
            con.rollback()
        except psycopg.Error:
            pass
        con.close()


def validate_quantity_sql(quantity_sql: str) -> None:
    """Бросает RuleSqlError, если Action.quantity SQL невалиден или нарушает
    контракт «ровно одна строка × одна колонка, целое ≥ 0 либо NULL»."""
    sql = _substitute_validation_params(quantity_sql)
    con = connect()
    try:
        _setup_session(con)
        try:
            cur = con.execute(sql)
            description = cur.description or []
            rows = cur.fetchall()
        except psycopg.Error as e:
            raise RuleSqlError(f'Action.quantity SQL невалиден: {e}') from e

        if len(description) != 1:
            raise RuleSqlError(
                f'Action.quantity должен возвращать ровно одну колонку, получено {len(description)}'
            )
        if len(rows) > 1:
            raise RuleSqlError(
                f'Action.quantity должен возвращать ровно одну строку, получено {len(rows)}'
            )
        if rows:
            value = rows[0][0]
            if value is not None:
                try:
                    iv = int(value)
                except (TypeError, ValueError) as e:
                    raise RuleSqlError(
                        f'Action.quantity вернул нечисловое значение: {value!r}'
                    ) from e
                if iv < 0:
                    raise RuleSqlError(
                        f'Action.quantity должен быть ≥ 0, вернул {iv}'
                    )
    finally:
        try:
            con.rollback()
        except psycopg.Error:
            pass
        con.close()
