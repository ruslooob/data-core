"""Перезапускает все стратегии на их «родных» окружениях после переезда на Postgres.

Алгоритм:
1. Снимает текущий маппинг (strategy, environment) → result из persistent.
2. Чистит trade_journal + backtest_results.
3. Для каждой пары (strategy, environment) запускает прогон через REST API,
   ждёт завершения, логирует результат.
4. Печатает финальную таблицу метрик.

Перед запуском должен быть поднят backend на 127.0.0.1:8080.
Логирует прогресс в `data/logs/rerun_all_strategies.log` (через
явный flush, чтобы пользователь мог `tail -f`).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(ROOT, 'data', 'logs', 'rerun_all_strategies.log')
PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'
API = 'http://127.0.0.1:8080'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
_log = open(LOG_PATH, 'w', encoding='utf-8', buffering=1)


def log(msg: str) -> None:
    line = f'{datetime.now().strftime("%H:%M:%S")}  {msg}'
    print(line, flush=True)
    _log.write(line + '\n')
    _log.flush()


def http_get(p: str) -> dict:
    with urllib.request.urlopen(f'{API}{p}', timeout=30) as r:
        return json.loads(r.read())


def http_post(p: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f'{API}{p}',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())


_NEW_STRATEGIES_DEFAULT_ENV = {
    # Стратегии без истории прогонов — задаём «родное» окружение явно.
    'Buy LKOH all available': 'LKOH full history 2002-2025',
}


def collect_pairs() -> list[tuple[str, str, str, str]]:
    """Возвращает список (strategy_id, strategy_name, env_id, env_name).

    Берёт уникальные пары из существующих backtest_results, плюс новые
    стратегии, заявленные в `_NEW_STRATEGIES_DEFAULT_ENV`."""
    con = psycopg.connect(PG_DSN, autocommit=True)
    with con.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT br.strategy_id, s.name, br.environment_id, e.name
            FROM backtest_results br
            JOIN strategies s ON s.id = br.strategy_id
            JOIN environments e ON e.id = br.environment_id
            ORDER BY s.name
        """)
        rows = cur.fetchall()

        existing_pair_keys = {(str(r[0]), str(r[2])) for r in rows}
        pairs: list[tuple[str, str, str, str]] = [
            (str(r[0]), r[1], str(r[2]), r[3]) for r in rows
        ]

        # Добавляем новые стратегии без истории.
        for s_name, e_name in _NEW_STRATEGIES_DEFAULT_ENV.items():
            cur.execute('SELECT id FROM strategies WHERE name = %s', [s_name])
            sr = cur.fetchone()
            if sr is None:
                continue
            cur.execute('SELECT id FROM environments WHERE name = %s', [e_name])
            er = cur.fetchone()
            if er is None:
                continue
            key = (str(sr[0]), str(er[0]))
            if key in existing_pair_keys:
                continue
            pairs.append((str(sr[0]), s_name, str(er[0]), e_name))
    con.close()
    pairs.sort(key=lambda p: p[1])
    return pairs


def cleanup_results() -> None:
    con = psycopg.connect(PG_DSN, autocommit=True)
    with con.cursor() as cur:
        cur.execute('DELETE FROM trade_journal')
        cur.execute('DELETE FROM backtest_results')
        cur.execute('SELECT COUNT(*) FROM backtest_results')
        cnt = cur.fetchone()[0]
    con.close()
    log(f'cleaned: backtest_results count = {cnt}')


def run_one(strategy_id: str, env_id: str, label: str) -> dict | None:
    """Запускает прогон, ждёт окончания, возвращает progress-snapshot или None."""
    log(f'  start: {label}')
    try:
        status, body = http_post('/api/backtest/run',
                                 {'strategyId': strategy_id, 'environmentId': env_id})
    except Exception as e:
        log(f'    POST failed: {e}')
        return None
    run_id = body.get('runId')
    if not run_id:
        log(f'    no runId in response: {body}')
        return None
    last_pct = -1
    started = time.time()
    deadline = started + 30 * 60  # 30 минут потолок на прогон
    while time.time() < deadline:
        time.sleep(2)
        try:
            p = http_get(f'/api/backtest/runs/{run_id}/progress')
        except Exception as e:
            log(f'    progress fetch failed: {e}')
            time.sleep(2)
            continue
        pct = round(p.get('progress', 0) * 100, 1)
        if pct != last_pct:
            log(f'    {pct}% trades={p.get("nTradesSoFar")} status={p["status"]}')
            last_pct = pct
        if p['done']:
            elapsed = round(time.time() - started, 1)
            log(f'  done in {elapsed}s  status={p["status"]}  err={p.get("errorMessage")}')
            return p
    log('  TIMEOUT — превышено 30 минут')
    return None


def main() -> None:
    log('=== rerun_all_strategies ===')
    pairs = collect_pairs()
    log(f'pairs collected: {len(pairs)}')
    for sid, sname, eid, ename in pairs:
        log(f'  {sname!r:55s} on {ename!r}')

    log('--- cleanup ---')
    cleanup_results()

    log('--- runs ---')
    for sid, sname, eid, ename in pairs:
        run_one(sid, eid, f'{sname} | {ename}')

    log('--- final ---')
    con = psycopg.connect(PG_DSN, autocommit=True)
    with con.cursor() as cur:
        cur.execute("""
            SELECT s.name, e.name, br.total_return_pct, br.annual_return_pct,
                   br.max_drawdown_pct, br.sharpe, br.n_trades,
                   br.profit_factor, br.win_rate_pct
            FROM backtest_results br
            JOIN strategies s ON s.id = br.strategy_id
            JOIN environments e ON e.id = br.environment_id
            ORDER BY s.name
        """)
        for r in cur.fetchall():
            log(f'  {r[0]!r:50s} | {r[1]!r:35s} | tot={r[2]:.2f}% '
                f'ann={r[3]:.2f}% dd={r[4]:.2f}% sharpe={r[5]:.2f} n={r[6]}')
    con.close()


if __name__ == '__main__':
    main()
