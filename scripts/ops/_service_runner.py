"""Middleware-обёртка между run_services.py и сервисом (uvicorn / vite).

Запускает дочерний сервис через pipe и форвардит каждую строку stdout/stderr
в свой ротирующий лог-хендлер. Ротация: размер > 10 MB **или** пересечение
полуночи. Хранится последние 7 архивов (.1 … .7), старшие удаляются.

Не предназначен для прямого запуска — используется только из
scripts/ops/run_services.py.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 7              # хранить 7 архивов


class DailySizedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler + принудительная ротация при смене даты."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._day = datetime.date.today().isoformat()

    def shouldRollover(self, record):
        today = datetime.date.today().isoformat()
        if self._day != today:
            self._day = today
            try:
                if self.stream is not None:
                    self.stream.flush()
                    self.stream.seek(0, 2)
                    if self.stream.tell() > 0:
                        return True
            except OSError:
                pass
        return super().shouldRollover(record)


def _make_logger(name: str, path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.propagate = False
    handler = DailySizedRotatingFileHandler(
        filename=str(path),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(handler)
    return log


def _pump(stream, logger: logging.Logger) -> None:
    try:
        for line in stream:
            line = line.rstrip('\r\n')
            if line:
                logger.info(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cmd-json', help='команда как JSON-list (для shell=False)')
    parser.add_argument('--shell-cmd', help='команда строкой (для shell=True)')
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--out-log', required=True)
    parser.add_argument('--err-log', required=True)
    args = parser.parse_args()

    if args.shell_cmd:
        cmd, shell = args.shell_cmd, True
    elif args.cmd_json:
        cmd, shell = json.loads(args.cmd_json), False
    else:
        raise SystemExit('передай --cmd-json или --shell-cmd')

    out_log = _make_logger('svc.out', Path(args.out_log))
    err_log = _make_logger('svc.err', Path(args.err_log))

    err_log.info(f'--- service_runner starting cmd={cmd!r} cwd={args.cwd}')
    proc_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=args.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            creationflags=proc_flags,
        )
    except Exception:
        err_log.info('--- service_runner failed to start subprocess:\n' + traceback.format_exc())
        return 1

    t_out = threading.Thread(target=_pump, args=(proc.stdout, out_log), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, err_log), daemon=True)
    t_out.start()
    t_err.start()

    rc = proc.wait()
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    err_log.info(f'--- service_runner subprocess exited rc={rc}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
