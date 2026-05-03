"""Файловый логгер бэктест-прогона.

Драфт: Часть 6.4 BACKTEST_GLOSSARY_DRAFT.md.

Формат строки: `<ts>  <LEVEL>  <message>`. Не JSON — грепается обычным
текстом. Файл создаётся при старте прогона, дописывается построчно,
переживает завершение. Удаляется при `DELETE /api/backtest/results/{id}`.

Уровни (по убыванию подробности):
    ERROR — синтаксические/семантические ошибки SQL триггера, нарушение
            контракта `Action.quantity`, падение прогона.
    WARN  — кандидат отброшен (NULL от UDF, не хватило кэша, нет позиции),
            частичное заполнение, пустые данные у тикера.
    INFO  — старт прогона, завершение со всеми метриками, отмена.
    DEBUG — начало тика, результаты триггера каждого правила, кандидаты,
            запись каждой сделки, конец тика с equity/cash/positions.
            **Уровень по умолчанию.**
    TRACE — каждое обращение к UDF/поставщику, длительность, попадание в кэш.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / 'data' / 'logs' / 'backtest'

LEVELS = ('ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE')
LEVEL_PRIORITY = {name: i for i, name in enumerate(LEVELS)}


class BacktestLogger:
    """Пишет в файл `<LOG_DIR>/<run_id>.log` построчно. Открыт всё время прогона."""

    def __init__(self, run_id: str, level: str = 'DEBUG'):
        if level not in LEVEL_PRIORITY:
            raise ValueError(f'Неизвестный уровень: {level!r}, ожидалось одно из {LEVELS}')
        self.run_id = run_id
        self.level_threshold = LEVEL_PRIORITY[level]
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOG_DIR / f'{run_id}.log'
        # line buffering, кодировка utf-8 — пользовательские имена и описания
        # могут содержать русские буквы.
        self._fp = open(self.path, 'a', encoding='utf-8', buffering=1)

    def log(self, level: str, message: str, **kv) -> None:
        if LEVEL_PRIORITY.get(level, 99) > self.level_threshold:
            return
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        # пары ключ=значение: пробел-разделитель, без кавычек если можно
        if kv:
            tail = '  ' + ' '.join(f'{k}={_format_value(v)}' for k, v in kv.items())
        else:
            tail = ''
        self._fp.write(f'{ts}  {level:<5}  {message}{tail}\n')

    def info(self, message: str, **kv) -> None: self.log('INFO', message, **kv)
    def warn(self, message: str, **kv) -> None: self.log('WARN', message, **kv)
    def debug(self, message: str, **kv) -> None: self.log('DEBUG', message, **kv)
    def error(self, message: str, **kv) -> None: self.log('ERROR', message, **kv)
    def trace(self, message: str, **kv) -> None: self.log('TRACE', message, **kv)

    def close(self) -> None:
        try:
            self._fp.close()
        except Exception:
            pass


def _format_value(v) -> str:
    if isinstance(v, (int, float, bool)):
        return str(v)
    s = str(v)
    if any(c.isspace() for c in s):
        return f"'{s}'"
    return s


def log_path_for(run_id: str) -> Path:
    return LOG_DIR / f'{run_id}.log'
