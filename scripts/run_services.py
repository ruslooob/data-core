"""Запуск backend и frontend в фоне с ротацией логов.

Использование:
    python scripts/run_services.py             # оба сервиса
    python scripts/run_services.py --backend   # только бек
    python scripts/run_services.py --frontend  # только фронт

Идемпотентность: если порт уже занят — сервис пропускается, ошибки нет.

Архитектура: для каждого сервиса спавнится детачнутый middleware-процесс
(`scripts/_service_runner.py`), который читает stdout/stderr дочернего
сервиса через pipe и пишет каждую строку через ротирующий хендлер.
Ротация — по размеру (10 MB) **и** по дате (новый файл каждые сутки);
хранится 7 архивов на каждый лог.

Логи:
    data/logs/backend.out.log   — uvicorn stdout (access)
    data/logs/backend.err.log   — uvicorn stderr (servicing + errors)
    data/logs/frontend.out.log  — vite stdout
    data/logs/frontend.err.log  — vite stderr

Архивы: <name>.1 … <name>.7 (свежее — меньший номер).

Timestamp в строках backend'а — через scripts/uvicorn_log_config.yaml.
Vite пишется без timestamp.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / 'data' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

PY = r'C:/Users/Ruslan/anaconda3/envs/data-core/python.exe'
BACKEND_PORT = 8080
FRONTEND_PORT = 5173
UVICORN_LOG_CONFIG = ROOT / 'scripts' / 'uvicorn_log_config.yaml'
SERVICE_RUNNER = ROOT / 'scripts' / '_service_runner.py'


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except OSError:
            return False


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
    parser.add_argument('--backend', action='store_true', help='запустить только бекенд')
    parser.add_argument('--frontend', action='store_true', help='запустить только фронт')
    args = parser.parse_args()
    both = not args.backend and not args.frontend
    if args.backend or both:
        start_backend()
    if args.frontend or both:
        start_frontend()


if __name__ == '__main__':
    main()
