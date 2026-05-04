"""Дочерний процесс одного бэктест-прогона.

Точка входа `worker_main` вызывается через `multiprocessing.Process`.
Воркер изолирован от веб-процесса:

- Открывает свой DuckDB-коннект **только в `:memory:`**. Никаких файлов на
  диске — это снимает Windows-ограничение «двух коннектов на один файл»
  (см. docs/drafts/DB_WRITER_PROCESS_DRAFT.md).
- Spec стратегии и окружения приходят сериализованно через аргументы
  Process — никакого чтения persistent-БД из воркера.
- Прогресс пишется в `progress_queue`. Финальный результат и ошибки —
  туда же, отдельным сообщением. Веб-процесс читает очередь в фоновом
  потоке.
- Отмена — через `cancel_event`. Движок проверяет его на каждом тике.

Любое неперехваченное исключение (в т.ч. на этапе `duckdb.connect`,
создании `BacktestLogger` или импортов) пишется в
`data/logs/backtest/<run_id>.err` — иначе процесс умер бы молча
без следов в логе.
"""
from __future__ import annotations

import sys
import traceback
from multiprocessing.synchronize import Event as EventType
from queue import Full
from typing import Any

import duckdb

from core.backtest_engine import BacktestEngine
from core.backtest_logger import BacktestLogger, LOG_DIR


def worker_main(
        strategy_spec: Any,
        environment_spec: Any,
        progress_queue,
        cancel_event: EventType,
        run_id: str,
) -> None:
    """Запускается в дочернем процессе. Гоняет один прогон от начала до конца.

    `run_id` нужен для имени лог-файла `data/logs/backtest/<run_id>.log`.
    """

    def push(message: dict) -> None:
        try:
            progress_queue.put_nowait(message)
        except Full:
            pass

    def dump_fatal(message: str) -> None:
        """Сбрасывает traceback на диск ДО любого нормального логгера.
        Используется когда падает init воркера (duckdb.connect/BacktestLogger
        ещё не открыты). Файл `<run_id>.err` рядом с лог-файлами."""
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
        con = duckdb.connect(':memory:')
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
            logger.error('run failed', error=str(e))
            push({
                'kind': 'error',
                'message': str(e),
                'traceback': traceback.format_exc(),
            })

    except Exception as e:
        # Падение на init воркера (до или во время создания logger) —
        # дампим traceback в `.err` чтобы потом не плясать вокруг spawn'а.
        tb = traceback.format_exc()
        dump_fatal(f'worker init failed: {e}\n{tb}')
        push({'kind': 'error', 'message': str(e), 'traceback': tb})
    finally:
        if logger is not None:
            logger.close()
        if con is not None:
            con.close()
