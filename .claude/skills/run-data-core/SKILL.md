---
name: run-data-core
description: Запуск и верификация локального стека data-core (Postgres + FastAPI:8080 + Vite:5173) — поднимает сервисы и проверяет, что бэкенд и фронт отвечают. Применяется при запросах «запусти проект», «подними бэк», «проверь, что всё работает», «smoke test».
---

# run-data-core

Поднимает локальный стек data-core и убеждается в его работоспособности. Все пути ниже — относительно корня репозитория (`C:\Users\Ruslan\PycharmProjects\data-core`). Платформа — Windows 10 + conda + Docker Desktop.

Стек:
- **Postgres** — контейнер `data-core-postgres` (docker compose), порт `5432`.
- **Backend** — FastAPI / uvicorn, `:8080`. Запускается из `backend/` через `main:app`.
- **Frontend** — Vite + React, `:5173`. Хост `127.0.0.1` (на Windows `localhost` не биндится).

Бэкенд и фронт спавнятся **детачнутыми процессами** через `scripts/run_services.py`. Скрипт идемпотентен (занятый порт → пропуск, не ошибка), пишет stdout/stderr в `data/logs/{backend,frontend}.{out,err}.log` с ротацией.

## Prerequisites

Однократная установка:
- Conda env `data-core` (Python 3.11) по пути `C:/Users/Ruslan/anaconda3/envs/data-core/python.exe`.
- Backend как editable-пакет: `cd backend && pip install -e .`
- Фронтовые зависимости: `cd frontend && npm install`
- Запущенный Docker Desktop.

## Run (agent path)

Один драйвер делает всё: поднимает Postgres, спавнит сервисы, ждёт готовности, прогоняет три API-вызова и проверяет HTML фронта.

```bash
python .claude/skills/run-data-core/smoke.py
```

Ожидаемый успешный вывод (exit code 0):

```
[postgres] data-core-postgres уже запущен
[services] scripts/run_services.py (идемпотентно)
[backend] порт 8080 занят -- пропускаю
[frontend] порт 5173 занят -- пропускаю
[ready] backend=ok frontend=ok
[smoke] /api/health -> {'status': 'ok'}
[smoke] /api/tickers -> 69 тикеров (пример: ['AFLT', 'ALRS', 'BSPB'])
[smoke] /openapi.json -> 35 путей
[smoke] frontend /  -> HTML, 621 bytes
OK: стек поднят. Swagger: http://127.0.0.1:8080/docs
OK: фронт: http://127.0.0.1:5173
```

На первом холодном запуске сначала отображается «поднимаю data-core-postgres» и несколько тиков `[wait] backend=False frontend=False` — это ожидаемо, deadline 30 секунд.

## Run (human path)

```bash
python scripts/run_services.py             # запустить (идемпотентно)
python scripts/run_services.py --stop      # остановить
python scripts/run_services.py --restart   # перезапустить (после правки кода бэка)
python scripts/run_services.py --backend   # действие только над беком
python scripts/run_services.py --frontend  # действие только над фронтом
```

`python` — любой интерпретатор, в котором установлены зависимости проекта; в репозитории используется conda-окружение `data-core`. Дочерние процессы спавнятся через `sys.executable`, поэтому подхватывают ту же среду.

Swagger: <http://127.0.0.1:8080/docs>. Фронт: <http://127.0.0.1:5173>. Логи: `data/logs/backend.err.log`, `data/logs/frontend.err.log`.

## Gotchas

- **Идемпотентный запуск ≠ перезапуск.** Без флагов `run_services.py` молча пропускает занятый порт — это намеренное поведение, защищающее активную сессию разработчика. После правки кода бэка требуется явный `--restart`, иначе на порту останется старая версия.
- **`--stop` определяет процесс по порту, не по PID-файлу.** Поиск идёт через `psutil.net_connections()`: убивается всё, что слушает 8080/5173. На свежей машине перед первым запуском рекомендуется проверить `netstat -ano | findstr 8080` — посторонний процесс на этом порту тоже будет завершён.
- **Зомби-сокеты после kill.** Редкий случай: `Get-NetTCPConnection -LocalPort 8080` показывает PID, но `Get-Process` его не находит — сокет завис в ядре. `taskkill /F` не помогает; решение — перезагрузка машины.
- **`/openapi.json` через `curl | python -c json.load` в Git-bash** иногда падает с «Invalid control character» — баг локали Windows-bash при перекодировке через pipe. Драйвер использует `urllib` и этого избегает. Связку `curl | python` для JSON-ручек применять не следует.
- **Vite first-render — HTML без контента.** На `/` фронт отдаёт ~600 байт shell-страницы, JS-бандл загружается отдельным запросом. Smoke проверяет наличие `<html`, не содержимое.

## Troubleshooting

| Симптом | Причина и решение |
|---|---|
| `[wait] backend=False ...` 15+ тиков, затем таймаут | Открыть `data/logs/backend.err.log` — обычно `ImportError` или ошибка подключения к Postgres. |
| `docker compose up failed: Cannot connect to the Docker daemon` | Docker Desktop не запущен. Запустить вручную, дождаться значка в трее. |
| `[postgres] не дошёл до healthy за 20 секунд` | Контейнер падает. `docker logs data-core-postgres` покажет причину; чаще всего БД не накатана — требуется `docker compose --profile migrate run --rm liquibase update` и `python scripts/load_data_to_postgres.py`. |
| `/api/tickers -> 0 тикеров` или 500 | БД пустая. См. выше: миграции и `load_data_to_postgres.py`. |
| Frontend 200, но в браузере белая страница | DevTools → Network. 404 на `/src/main.tsx` означает отсутствующий или повреждённый `node_modules`. Удалить и переустановить. |

## Stop

```bash
python scripts/run_services.py --stop              # оба
python scripts/run_services.py --stop --backend    # только бек
docker compose stop postgres                       # БД
```

Скрипт находит процессы, слушающие 8080/5173, и убивает дерево (middleware + uvicorn/vite + их дети). По договорённости проекта бэкенд остаётся запущенным после смоук-теста — без необходимости не останавливается.
