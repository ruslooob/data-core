"""Пересчитывает max_drawdown_pct для всех существующих backtest_results.

Старые значения были посчитаны на runtime equity_curve, в котором у некоторых
прогонов были битые тики (например, equity briefly = цене 1 акции из-за
строгого _close_price без forward-fill). Это давало нереалистичные просадки
(вплоть до 99.99%). Сейчас баг исправлен, persistent equity-кривая
реконструируется из trade_journal корректно — пересчитываем metric из неё.

Формула — стандартная peak-to-trough:
  peak растёт по ходу, dd = (peak - eq) / peak, max_dd = max по всем тикам.

Запускать со стопнутым бэкендом (DuckDB-файл блокируется одним писателем).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import duckdb

from core.backtest_engine import reconstruct_equity_curve

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'data-core.duckdb')


def main() -> None:
    con = duckdb.connect(DB_PATH)
    try:
        results = con.execute(
            'SELECT br.id, e.starting_capital, br.max_drawdown_pct '
            'FROM backtest_results br '
            'JOIN environments e ON e.id = br.environment_id'
        ).fetchall()
        print(f'found {len(results)} results to backfill')

        for result_id, starting, old_dd in results:
            starting = float(starting)
            curve = reconstruct_equity_curve(con, result_id)
            peak = starting
            max_dd = 0.0
            for _, eq in curve:
                if eq > peak:
                    peak = eq
                if peak > 0:
                    dd = (peak - eq) / peak
                    if dd > max_dd:
                        max_dd = dd
            new_dd = max_dd * 100.0
            con.execute(
                'UPDATE backtest_results SET max_drawdown_pct = ? WHERE id = ?',
                [new_dd, result_id],
            )
            print(f'  {result_id}: {old_dd:.2f}% -> {new_dd:.2f}%')

        print('done')
    finally:
        con.close()


if __name__ == '__main__':
    main()
