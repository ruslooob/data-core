"""Валидация SQL пользовательских правил при создании.

Q27 драфта бэктеста:
- Trigger SQL и Action.quantity SQL должны быть синтаксически валидными
  (DuckDB-парсер).
- Action.quantity должен возвращать 1×1 с целым ≥ 0 (или NULL — это
  мягкая ошибка, а не отказ создания).

Подход:
- Поднимается изолированный `:memory:`-коннект.
- В нём создаются «фиктивные» runtime-таблицы (run_context, portfolio_state,
  portfolio_positions, trade_journal) и persistent-таблицы (events, tags,
  event_tags, tagged_events) — все пустые. Это даёт парсеру резолвить
  ссылки на любые таблицы, которые может использовать пользователь.
- Регистрируются stub-UDF/MACRO бэктеста и PQL: возвращают NULL.
- Имена параметров `:tick`, `:ticker` нормализуются в `$tick`, `$ticker`.
- Trigger проверяется через `EXPLAIN` (без исполнения).
- Quantity проверяется через `EXPLAIN` + одно реальное `execute` с
  фиктивными `:tick`/`:ticker`. Контракт «1×1 с целым ≥ 0» проверяется
  по факту: ровно одна колонка, ровно одна строка, значение либо NULL,
  либо приводится к int ≥ 0.
"""
from __future__ import annotations

from datetime import date

import duckdb

from core.backtest_engine import _filter_params, _normalize_named_params


def _make_stub(n_args: int):
    """DuckDB определяет арность Python-функции по `inspect.signature`, поэтому
    `*args` он считает за 1 параметр. Генерируем стаб с нужной арностью явно."""
    arg_names = ', '.join(f'a{i}' for i in range(n_args))
    src = f'lambda {arg_names}: None'
    return eval(src)  # noqa: S307 — закрытый список арностей, без user input


_RUNTIME_DDL = [
    """CREATE TABLE run_context (
        current_date DATE, index INTEGER, date_start DATE, date_end DATE,
        starting_capital DOUBLE
    )""",
    """CREATE TABLE portfolio_state (cash DOUBLE NOT NULL, equity DOUBLE NOT NULL)""",
    """CREATE TABLE portfolio_positions (
        ticker VARCHAR NOT NULL, quantity INTEGER NOT NULL,
        buy_price DOUBLE NOT NULL, buy_date DATE NOT NULL
    )""",
    """CREATE TABLE trade_journal (
        trade_date DATE NOT NULL, ticker VARCHAR NOT NULL, type VARCHAR NOT NULL,
        quantity INTEGER NOT NULL, price DOUBLE NOT NULL, rule_name VARCHAR NOT NULL,
        pnl_realized DOUBLE
    )""",
    """CREATE TABLE events (
        id VARCHAR PRIMARY KEY, date_start DATE NOT NULL, date_end DATE, event TEXT
    )""",
    """CREATE TABLE tags (code VARCHAR PRIMARY KEY, name VARCHAR, type VARCHAR)""",
    """CREATE TABLE event_tags (
        event_id VARCHAR NOT NULL, tag_code VARCHAR NOT NULL,
        PRIMARY KEY (event_id, tag_code)
    )""",
    """CREATE VIEW tagged_events AS
        SELECT e.id AS event_id, e.date_start, e.date_end, e.event,
               t.code AS tag, t.name AS tag_name, t.type AS tag_type
        FROM events e
        JOIN event_tags et ON et.event_id = e.id
        JOIN tags t ON t.code = et.tag_code""",
]


class RuleSqlError(Exception):
    """Сообщение для пользователя; отправляется как 400 detail."""


def _build_validation_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(':memory:')
    for ddl in _RUNTIME_DDL:
        con.execute(ddl)

    # Бэктест-UDF: возвращают NULL.
    for name, types in (
        ('_close_price', ['VARCHAR', 'DATE']),
        ('_open_price', ['VARCHAR', 'DATE']),
        ('_volume', ['VARCHAR', 'DATE']),
        ('_avg_price', ['VARCHAR']),
        ('_volume_ratio', ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER']),
        ('_sma', ['VARCHAR', 'DATE', 'INTEGER']),
        ('_volume_sma', ['VARCHAR', 'DATE', 'INTEGER']),
        ('_volatility', ['VARCHAR', 'DATE', 'INTEGER']),
        ('_return_n_days', ['VARCHAR', 'DATE', 'INTEGER']),
        # PQL-UDF — могут встречаться в триггерах, например для event-study фильтров.
        ('_car_impl', ['VARCHAR', 'DATE', 'VARCHAR', 'INTEGER', 'INTEGER', 'INTEGER', 'DOUBLE']),
        ('_vol_ratio_impl', ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER']),
        ('_volume_ratio_impl', ['VARCHAR', 'DATE', 'INTEGER', 'INTEGER']),
    ):
        con.create_function(name, _make_stub(len(types)), types, 'DOUBLE', null_handling='special')

    # Макросы — те же, что в backtest_engine + precedent_engine.
    con.execute("CREATE MACRO close_price(ticker, d) AS _close_price(ticker, d)")
    con.execute("CREATE MACRO open_price(ticker, d) AS _open_price(ticker, d)")
    con.execute("CREATE MACRO volume(ticker, d) AS _volume(ticker, d)")
    con.execute("CREATE MACRO avg_price(ticker) AS _avg_price(ticker)")
    con.execute(
        "CREATE MACRO volume_ratio(ticker, d, window_before := 5, window_after := 5) "
        "AS _volume_ratio(ticker, d, window_before, window_after)"
    )
    con.execute("CREATE MACRO sma(ticker, d, w) AS _sma(ticker, d, w)")
    con.execute("CREATE MACRO volume_sma(ticker, d, w) AS _volume_sma(ticker, d, w)")
    con.execute("CREATE MACRO volatility(ticker, d, w) AS _volatility(ticker, d, w)")
    con.execute("CREATE MACRO return_n_days(ticker, d, n) AS _return_n_days(ticker, d, n)")
    con.execute(
        "CREATE MACRO car("
        "ticker, event_date, "
        "model := 'market_model', window_before := 5, window_after := 5, "
        "estimation := 200, outlier_threshold := NULL"
        ") AS _car_impl(ticker, event_date, model, window_before, window_after, estimation, outlier_threshold)"
    )
    con.execute(
        "CREATE MACRO vol_ratio(ticker, event_date, window_before := 5, window_after := 5) "
        "AS _vol_ratio_impl(ticker, event_date, window_before, window_after)"
    )

    # Одна строка в run_context/portfolio_state — чтобы запросы вида
    # `SELECT cash FROM portfolio_state` могли вернуть результат.
    con.execute("INSERT INTO run_context VALUES (DATE '2020-01-02', 0, DATE '2020-01-01', DATE '2025-12-31', 1000000)")
    con.execute("INSERT INTO portfolio_state VALUES (1000000, 1000000)")
    return con


def validate_trigger_sql(trigger_sql: str) -> None:
    """Бросает RuleSqlError, если SQL триггера невалиден."""
    sql = _normalize_named_params(trigger_sql)
    con = _build_validation_con()
    try:
        try:
            con.execute(
                f'EXPLAIN {sql}',
                _filter_params(sql, {'tick': date(2020, 1, 2)}),
            )
        except duckdb.Error as e:
            raise RuleSqlError(f'Trigger SQL невалиден: {e}') from e
    finally:
        con.close()


def validate_quantity_sql(quantity_sql: str) -> None:
    """Бросает RuleSqlError, если Action.quantity SQL невалиден или нарушает
    контракт «ровно одна строка × одна колонка, целое ≥ 0 либо NULL»."""
    sql = _normalize_named_params(quantity_sql)
    con = _build_validation_con()
    try:
        params = _filter_params(sql, {'tick': date(2020, 1, 2), 'ticker': 'TEST'})
        try:
            cur = con.execute(sql, params)
            description = cur.description or []
            rows = cur.fetchall()
        except duckdb.Error as e:
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
        con.close()
