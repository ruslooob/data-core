"""Дочерний процесс одного бэктест-прогона.

После переезда на Postgres воркер открывает свой psycopg-коннект
(autocommit=False) — это даёт ему собственную сессию, в которой будут
жить TEMP TABLE движка и SD-кэш plpython3u-UDF. По окончании прогона
коннект закрывается, всё runtime-состояние удаляется автоматически.

Воркер изолирован от веб-процесса:
- Spec стратегии и окружения приходят через args Process (pickle).
- Прогресс пишется в `progress_queue`. Финальный результат и ошибки —
  туда же.
- Отмена — через `cancel_event`, движок проверяет на каждом тике.

Любое неперехваченное исключение пишется в `data/logs/backtest/<run_id>.err`.
"""
from __future__ import annotations

import sys
import traceback
from multiprocessing.synchronize import Event as EventType
from queue import Full
from typing import Any

import psycopg

from core.backtest_engine import BacktestEngine
from core.backtest_logger import BacktestLogger, LOG_DIR
from core.postgres_db import PG_DSN


def worker_main(
        strategy_spec: Any,
        environment_spec: Any,
        progress_queue,
        cancel_event: EventType,
        run_id: str,
) -> None:
    """Запускается в дочернем процессе. Гоняет один прогон от начала до конца."""

    def push(message: dict) -> None:
        try:
            progress_queue.put_nowait(message)
        except Full:
            pass

    def dump_fatal(message: str) -> None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / f'{run_id}.err', 'w', encoding='utf-8') as fp:
                fp.write(message)
        except Exception:
            pass
        try:
            sys.stderr.write(message)
            sys.stderr.flush()
        except Exception:
            pass

    con = None
    logger = None
    try:
        con = psycopg.connect(PG_DSN, autocommit=False)
        logger = BacktestLogger(run_id=run_id, level='DEBUG')

        try:
            logger.info(
                'run start',
                run_id=run_id,
                strategy=strategy_spec.name,
                environment=environment_spec.name,
                period=f'{environment_spec.date_start}..{environment_spec.date_end}',
                starting_capital=environment_spec.starting_capital,
            )
            engine = BacktestEngine(
                strategy=strategy_spec,
                environment=environment_spec,
                con=con,
                logger=logger,
            )
            try:
                result = engine.run(
                    on_progress=lambda p: push({'kind': 'progress', **p}),
                    should_cancel=cancel_event.is_set,
                )
            finally:
                engine.close()

            if result is None:
                logger.info('run cancelled', run_id=run_id)
                push({'kind': 'cancelled'})
            else:
                logger.info(
                    'run complete',
                    run_id=run_id,
                    total_return_pct=round(result.total_return_pct, 2),
                    sharpe=round(result.sharpe, 2),
                    max_drawdown_pct=round(result.max_drawdown_pct, 2),
                    trades=result.n_trades,
                )
                push({'kind': 'done', 'result': result})

        except Exception as e:
            try:
                con.rollback()
            except Exception:
                pass
            logger.error('run failed', error=str(e))
            push({
                'kind': 'error',
                'message': str(e),
                'traceback': traceback.format_exc(),
            })

    except Exception as e:
        tb = traceback.format_exc()
        dump_fatal(f'worker init failed: {e}\n{tb}')
        push({'kind': 'error', 'message': str(e), 'traceback': tb})
    finally:
        if logger is not None:
            logger.close()
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
