"""Smoke-драйвер data-core: поднимает стек и убеждается, что он живой.

Шаги:
  1. Проверка docker-контейнера data-core-postgres (поднимает, если лежит).
  2. Запуск backend + frontend через scripts/ops/run_services.py (идемпотентно).
  3. Polling /api/health и /  фронта (до 30 секунд).
  4. Smoke-вызовы: /api/health, /api/tickers, /openapi.json.

Запуск:
    python .claude/skills/run-data-core/smoke.py

Возвращаемый код: 0 при успехе всех проверок, 1 с traceback — иначе.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable
BACKEND = 'http://127.0.0.1:8080'
FRONTEND = 'http://127.0.0.1:5173'
POSTGRES_CONTAINER = 'data-core-postgres'
READY_TIMEOUT_SEC = 30


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def ensure_postgres() -> None:
    ps = _run(['docker', 'ps', '--filter', f'name={POSTGRES_CONTAINER}', '--format', '{{.Names}}'])
    if POSTGRES_CONTAINER in ps.stdout:
        print(f'[postgres] {POSTGRES_CONTAINER} уже запущен')
        return
    print(f'[postgres] поднимаю {POSTGRES_CONTAINER}')
    up = _run(['docker', 'compose', 'up', '-d', 'postgres'], cwd=ROOT)
    if up.returncode != 0:
        raise SystemExit(f'docker compose up failed:\n{up.stderr}')
    for _ in range(20):
        ps = _run(['docker', 'ps', '--filter', f'name={POSTGRES_CONTAINER}', '--filter', 'health=healthy', '--format', '{{.Names}}'])
        if POSTGRES_CONTAINER in ps.stdout:
            print('[postgres] healthy')
            return
        time.sleep(1)
    raise SystemExit('[postgres] не дошёл до healthy за 20 секунд')


def start_services() -> None:
    print('[services] scripts/ops/run_services.py (идемпотентно)')
    cp = _run([PY, 'scripts/ops/run_services.py'], cwd=ROOT)
    sys.stdout.write(cp.stdout)
    if cp.returncode != 0:
        raise SystemExit(f'ops/run_services.py failed:\n{cp.stderr}')


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def wait_ready() -> None:
    deadline = time.time() + READY_TIMEOUT_SEC
    while time.time() < deadline:
        back = _http_ok(f'{BACKEND}/api/health')
        front = _http_ok(f'{FRONTEND}/')
        if back and front:
            print('[ready] backend=ok frontend=ok')
            return
        print(f'[wait]  backend={back} frontend={front}')
        time.sleep(2)
    raise SystemExit(f'не оба сервиса ответили за {READY_TIMEOUT_SEC} секунд')


def smoke_checks() -> None:
    with urllib.request.urlopen(f'{BACKEND}/api/health') as r:
        health = json.loads(r.read().decode('utf-8'))
    assert health.get('status') == 'ok', f'health не ok: {health}'
    print(f'[smoke] /api/health -> {health}')

    with urllib.request.urlopen(f'{BACKEND}/api/tickers') as r:
        tickers = json.loads(r.read().decode('utf-8'))
    assert isinstance(tickers, list) and tickers, 'tickers пустые'
    print(f'[smoke] /api/tickers -> {len(tickers)} тикеров (пример: {tickers[:3]})')

    with urllib.request.urlopen(f'{BACKEND}/openapi.json') as r:
        spec = json.loads(r.read().decode('utf-8'))
    print(f'[smoke] /openapi.json -> {len(spec["paths"])} путей')

    with urllib.request.urlopen(f'{FRONTEND}/') as r:
        html = r.read().decode('utf-8', errors='replace')
    assert '<html' in html.lower(), 'фронт отдал не HTML'
    print(f'[smoke] frontend /  -> HTML, {len(html)} bytes')


def main() -> int:
    ensure_postgres()
    start_services()
    wait_ready()
    smoke_checks()
    print()
    print('OK: стек поднят. Открывай Swagger: ' + BACKEND + '/docs')
    print('OK: фронт: ' + FRONTEND)
    return 0


if __name__ == '__main__':
    sys.exit(main())
