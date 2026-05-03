"""Координатор бэктест-прогонов на стороне веб-процесса.

Управляет жизненным циклом дочерних процессов воркеров. Хранит словарь
активных и недавно завершённых прогонов в памяти. Веб-эндпоинты
обращаются только сюда, никаких процессов и очередей знать не должны.

Архитектура — см. docs/drafts/DB_WRITER_PROCESS_DRAFT.md (2 роли).
Защита от утечек памяти и зомби — отложена туда же.
"""
from __future__ import annotations

import multiprocessing as mp
import threading
import uuid
from dataclasses import dataclass, field
from queue import Empty
from typing import Any, Callable

from core.backtest_engine import EnvironmentSpec, StrategySpec
from core.backtest_worker import worker_main

_QUEUE_MAXSIZE = 16


RunStatus = str  # 'running' | 'done' | 'error' | 'cancelled'


@dataclass
class RunHandle:
    run_id: str
    strategy_id: str
    environment_id: str
    status: RunStatus = 'running'
    last_progress: dict = field(default_factory=dict)
    final_result: Any = None  # BacktestResult — обнуляется после persist
    persisted_result_id: str | None = None
    error_message: str | None = None
    process: mp.Process | None = None
    progress_queue: Any = None  # mp.Queue
    cancel_event: Any = None  # mp.Event


class BacktestRunner:
    """Singleton-координатор. Создаётся один раз на процесс FastAPI."""

    def __init__(self, persist_callback: Callable[[Any], str]):
        """
        persist_callback: функция, которой передаётся завершённый
            BacktestResult; должна записать его в persistent-БД и
            вернуть `result_id`. Пишет тот, кто пишет в persistent —
            веб-процесс. Воркер сам в БД ничего не пишет.
        """
        self._persist_callback = persist_callback
        self._runs: dict[str, RunHandle] = {}
        self._runs_lock = threading.Lock()
        self._reader_started = False
        self._reader_lock = threading.Lock()
        # mp-context — обязательно spawn, чтобы дочерний процесс
        # не наследовал DuckDB-коннект веб-процесса (на Windows это и так
        # дефолт, на Linux — нет).
        self._mp_ctx = mp.get_context('spawn')

    # ── Публичный API ──────────────────────────────────────────────────────

    def start_run(
            self,
            strategy: StrategySpec,
            environment: EnvironmentSpec,
    ) -> str:
        run_id = str(uuid.uuid4())
        progress_queue = self._mp_ctx.Queue(maxsize=_QUEUE_MAXSIZE)
        cancel_event = self._mp_ctx.Event()

        process = self._mp_ctx.Process(
            target=worker_main,
            args=(strategy, environment, progress_queue, cancel_event, run_id),
            daemon=True,
        )

        handle = RunHandle(
            run_id=run_id,
            strategy_id=strategy.id,
            environment_id=environment.id,
            process=process,
            progress_queue=progress_queue,
            cancel_event=cancel_event,
        )
        with self._runs_lock:
            self._runs[run_id] = handle

        process.start()
        self._ensure_reader()
        return run_id

    def get_progress(self, run_id: str) -> dict | None:
        with self._runs_lock:
            handle = self._runs.get(run_id)
            if handle is None:
                return None
            return {
                'run_id': handle.run_id,
                'strategy_id': handle.strategy_id,
                'environment_id': handle.environment_id,
                'status': handle.status,
                'progress': handle.last_progress.get('progress', 0.0),
                'current_date': handle.last_progress.get('current_date'),
                'current_equity': handle.last_progress.get('current_equity'),
                'n_trades_so_far': handle.last_progress.get('n_trades_so_far', 0),
                'done': handle.status != 'running',
                'result_id': handle.persisted_result_id,
                'error_message': handle.error_message,
            }

    def cancel(self, run_id: str) -> bool:
        with self._runs_lock:
            handle = self._runs.get(run_id)
            if handle is None or handle.status != 'running':
                return False
            handle.cancel_event.set()
        return True

    # ── Фоновый поток-читатель очередей ────────────────────────────────────

    def _ensure_reader(self) -> None:
        with self._reader_lock:
            if self._reader_started:
                return
            t = threading.Thread(
                target=self._reader_loop, name='backtest-runner-reader', daemon=True,
            )
            t.start()
            self._reader_started = True

    def _reader_loop(self) -> None:
        """Раз в N миллисекунд проходит по всем активным runs и вычитывает
        их очереди. На терминальных сообщениях обновляет статус."""
        while True:
            with self._runs_lock:
                active = [h for h in self._runs.values() if h.status == 'running']

            if not active:
                # idle — проверяем реже, не сжигаем CPU
                _wait(0.2)
                continue

            for handle in active:
                self._drain_queue(handle)

            _wait(0.05)

    def _drain_queue(self, handle: RunHandle) -> None:
        try:
            while True:
                try:
                    msg = handle.progress_queue.get_nowait()
                except Empty:
                    return
                self._dispatch_message(handle, msg)
                if handle.status != 'running':
                    return
        except (OSError, EOFError, BrokenPipeError):
            # Воркер умер не оставив сообщения — выставим error.
            with self._runs_lock:
                if handle.status == 'running':
                    handle.status = 'error'
                    handle.error_message = 'Воркер завершился без ответа'

    def _dispatch_message(self, handle: RunHandle, msg: dict) -> None:
        kind = msg.get('kind')
        if kind == 'progress':
            with self._runs_lock:
                handle.last_progress = {
                    'progress': msg.get('progress', 0.0),
                    'current_date': msg.get('current_date'),
                    'current_equity': msg.get('current_equity'),
                    'n_trades_so_far': msg.get('n_trades_so_far', 0),
                }
        elif kind == 'done':
            result = msg.get('result')
            try:
                result_id = self._persist_callback(result)
            except Exception as e:
                with self._runs_lock:
                    handle.status = 'error'
                    handle.error_message = f'Не удалось сохранить результат: {e}'
                return
            with self._runs_lock:
                handle.persisted_result_id = result_id
                handle.final_result = None  # отдали в persistent — освобождаем
                handle.status = 'done'
                handle.last_progress['progress'] = 1.0
        elif kind == 'cancelled':
            with self._runs_lock:
                handle.status = 'cancelled'
        elif kind == 'error':
            with self._runs_lock:
                handle.status = 'error'
                handle.error_message = msg.get('message', 'unknown error')


def _wait(seconds: float) -> None:
    """Лёгкий sleep-таймер. Вынесено отдельной функцией ради тестируемости."""
    import time
    time.sleep(seconds)
