"""Управление backend и frontend в фоне с ротацией логов.

Использование:
    python scripts/ops/run_services.py             # запустить (идемпотентно)
    python scripts/ops/run_services.py --stop      # остановить
    python scripts/ops/run_services.py --restart   # перезапустить
    python scripts/ops/run_services.py --backend   # ограничить действие беком
    python scripts/ops/run_services.py --frontend  # ограничить действие фронтом

Без флагов действия (--stop/--restart) — идемпотентный запуск: если порт
уже занят, сервис пропускается без ошибки.

Каждый сервис спавнится через детачнутый middleware `scripts/ops/_service_runner.py`
(там же реализована ротация и архивация логов).

Логи:
    data/logs/backend.out.log   — uvicorn stdout (access)
    data/logs/backend.err.log   — uvicorn stderr (servicing + errors)
    data/logs/frontend.out.log  — vite stdout
    data/logs/frontend.err.log  — vite stderr
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / 'data' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

PY = sys.executable
BACKEND_PORT = 8080
FRONTEND_PORT = 5173
UVICORN_LOG_CONFIG = ROOT / 'scripts' / 'ops' / 'uvicorn_log_config.yaml'
SERVICE_RUNNER = ROOT / 'scripts' / 'ops' / '_service_runner.py'
PORT_RELEASE_GRACE_SEC = 1.0


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except OSError:
            return False


def _listening_pids_by_port(ports: list[int]) -> dict[int, list[int]]:
    targets = set(ports)
    result: dict[int, set[int]] = {p: set() for p in ports}
    for conn in psutil.net_connections(kind='tcp4'):
        if (conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and conn.laddr.port in targets
                and conn.pid):
            result[conn.laddr.port].add(conn.pid)
    return {p: sorted(pids) for p, pids in result.items()}


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    victims = parent.children(recursive=True) + [parent]
    for proc in victims:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(victims, timeout=3)


def _stop_on_port(name: str, port: int, pids: list[int]) -> bool:
    if not pids:
        print(f'[{name}] на :{port} никого нет')
        return False
    for pid in pids:
        _kill_tree(pid)
        print(f'[{name}] прибил pid={pid} (с детьми)')
    return True


def _detached_flags() -> int:
    if os.name != 'nt':
        return 0
    return (subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW)


def _spawn_middleware(*, cmd_arg: list[str], shell_arg: str | None,
                      cwd: Path, out: Path, err: Path) -> int:
    runner_cmd = [
        PY, str(SERVICE_RUNNER),
        '--cwd', str(cwd),
        '--out-log', str(out),
        '--err-log', str(err),
    ]
    if shell_arg is not None:
        runner_cmd += ['--shell-cmd', shell_arg]
    else:
        runner_cmd += ['--cmd-json', json.dumps(cmd_arg)]
    p = subprocess.Popen(
        runner_cmd,
        creationflags=_detached_flags(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return p.pid


def start_backend() -> None:
    if _port_in_use(BACKEND_PORT):
        print(f'[backend] порт {BACKEND_PORT} занят -- пропускаю')
        return
    cmd = [
        PY, '-m', 'uvicorn', 'main:app',
        '--host', '127.0.0.1', '--port', str(BACKEND_PORT),
        '--log-config', str(UVICORN_LOG_CONFIG),
    ]
    pid = _spawn_middleware(
        cmd_arg=cmd, shell_arg=None,
        cwd=ROOT / 'backend',
        out=LOG_DIR / 'backend.out.log',
        err=LOG_DIR / 'backend.err.log',
    )
    print(f'[backend] middleware pid={pid} :{BACKEND_PORT} '
          f'-> data/logs/backend.{{out,err}}.log')


def start_frontend() -> None:
    if _port_in_use(FRONTEND_PORT):
        print(f'[frontend] порт {FRONTEND_PORT} занят -- пропускаю')
        return
    pid = _spawn_middleware(
        cmd_arg=['npm', 'run', 'dev'],
        shell_arg=('npm run dev' if os.name == 'nt' else None),
        cwd=ROOT / 'frontend',
        out=LOG_DIR / 'frontend.out.log',
        err=LOG_DIR / 'frontend.err.log',
    )
    print(f'[frontend] middleware pid={pid} :{FRONTEND_PORT} '
          f'-> data/logs/frontend.{{out,err}}.log')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--backend', action='store_true', help='ограничить действие беком (по умолчанию оба)')
    parser.add_argument('--frontend', action='store_true', help='ограничить действие фронтом (по умолчанию оба)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--stop', action='store_true', help='остановить, не запускать')
    mode.add_argument('--restart', action='store_true', help='остановить и запустить заново')
    args = parser.parse_args()

    do_backend = args.backend or not args.frontend
    do_frontend = args.frontend or not args.backend

    targets: list[tuple[str, int]] = []
    if do_backend:
        targets.append(('backend', BACKEND_PORT))
    if do_frontend:
        targets.append(('frontend', FRONTEND_PORT))

    if args.stop or args.restart:
        snapshot = _listening_pids_by_port([port for _, port in targets])
        killed_any = False
        for name, port in targets:
            killed_any |= _stop_on_port(name, port, snapshot[port])
        if args.restart and killed_any:
            time.sleep(PORT_RELEASE_GRACE_SEC)

    if not args.stop:
        if do_backend:
            start_backend()
        if do_frontend:
            start_frontend()


if __name__ == '__main__':
    main()
