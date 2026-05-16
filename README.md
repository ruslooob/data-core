# data-core

Рабочее место финансового аналитика: бэктест стратегий, событийный анализ, поиск прецедентов на языке PQL, журнал исследований. Магистерская дипломная работа.

## Стек

- **Backend:** Python 3.11, FastAPI.
- **БД:** Postgres + PL/Python + самописные postgres-функции; Liquibase для миграций.
- **Frontend:** React, TypeScript, Vite, lightweight-charts, TanStack Table, CodeMirror.
- **Инфраструктура:** Docker Compose (Postgres + Liquibase).

Структура проекта:
- **`docs/`**  — документация по проекту
- **`backend/`** — Python: `main.py` (точка входа), `routers/` (REST по доменам), `schemas/` (DTO), `core/` (доменная логика), `tests/`, `notebooks/` (для прототипирования).
- **`frontend/`** — React + Vite + lightweight-charts + TanStack Table. Плавающие виджеты на полотне.
- **`db/changelog/`** — Liquibase-changelog схемы Postgres.
- **`docker/`** — Dockerfile Postgres с включённым PL/Python и init-скрипт.
- **`data/`** - сырые данные, скачаны из внешних источников
- **`scripts/`** — Служебные скрипты: запуск проекта, загрузка данных и т д.

---

## Установка

### 1. Python (через conda)

```bash
conda create -n data-core python=3.11
conda activate data-core

# Базовые научные пакеты для ноутбуков
conda install -c conda-forge pandas numpy plotly matplotlib jupyter ipywidgets openpyxl

# Runtime-зависимости бэкенда (fastapi, uvicorn, duckdb, psycopg)
cd backend
pip install -e .
cd ..
```

### 2. Frontend (Node.js + npm)

Node.js 20+ и npm.

```bash
cd frontend
npm install
```

## Запуск проекта с нуля

После клонирования репозитория и установки Python/Node/Docker:

```bash
# 1. Поднять Postgres
docker compose up -d postgres

# 2. Накатить схему через Liquibase
docker compose --profile migrate run --rm liquibase update

# 3. Залить данные из папки `data`
python scripts/load_data_to_postgres.py

# 4. Проверка
docker compose --profile migrate run --rm liquibase status   # должно быть 0 pending changesets
cd backend && pytest tests/ -v
```

### Альтернатива: восстановление из дампа бд

Дампы лежат в `data/db/backup_<YYYYMMDD_HHMMSS>/full.dump`. Восстановление из выбранного бэкапа:

```bash
docker cp data/db/backup_20260513_154704/full.dump data-core-postgres:/tmp/full.dump
docker exec data-core-postgres pg_restore -U postgres -d postgres \
    --single-transaction /tmp/full.dump
```

Новый дамп создаётся скриптом:

```bash
python scripts/backup_postgres.py
```
---

## Запуск приложения

Postgres должен быть поднят. Дальше — backend + frontend.

```bash
python scripts/run_services.py             # оба сервиса
python scripts/run_services.py --backend   # только бэкенд
python scripts/run_services.py --frontend  # только фронт
```

- Backend: `http://127.0.0.1:8080/docs` (Swagger).
- Frontend: `http://127.0.0.1:5173`.

---

## Что есть в приложении

В тулбаре сверху — переключатель активного исследования и кнопка «+ Добавить виджет». Доступные виджеты:

| Виджет | Назначение                                    | Спецификация |
|---|-----------------------------------------------|---|
| **Price chart** | График цены акции с маркерами дивидендов и событий | [SPEC_FRONTEND.md](docs/SPEC_FRONTEND.md) |
| **Index chart** | IMOEX, RUONIA и другие индексы                | [SPEC_FRONTEND.md](docs/SPEC_FRONTEND.md) |
| **Event study** | Расчёт CAR для события с фильтрацией выбросов | [SPEC_FRONTEND.md](docs/SPEC_FRONTEND.md), [EXPECTED_RETURN_MODELS.md](docs/EXPECTED_RETURN_MODELS.md) |
| **Precedent editor** | PQL-запросы к базе событий                    | [SPEC_PRECEDENT_LANGUAGE.md](docs/SPEC_PRECEDENT_LANGUAGE.md) |
| **EntityEditor** | Редактор стратегий, правил и окружений бэктеста | [SPEC_BACKTEST.md](docs/SPEC_BACKTEST.md) |
| **BacktestEditor** | Запуск прогонов, результаты прогона | [SPEC_BACKTEST.md](docs/SPEC_BACKTEST.md) |
| **Research Journal** | Экспорт прогонов исследования                 | [SPEC_RESEARCH.md](docs/SPEC_RESEARCH.md) |

Концепция исследования как контейнера приватных стратегий/правил/окружений и прогонов — в [SPEC_RESEARCH.md](docs/SPEC_RESEARCH.md). Логические группы виджетов и ведущий график — в [SPEC_FRONTEND.md](docs/SPEC_FRONTEND.md).

---

## Тесты

```bash
cd backend
pytest tests/ -v
```

План покрытия — [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

---

## Документация

**Общее**
- [GLOSSARY.md](docs/GLOSSARY.md) — единый словарь проекта

**Подсистемы**
- [SPEC_DATABASE.md](docs/SPEC_DATABASE.md) — схема Postgres и миграции
- [SPEC_DATA_PROVIDERS.md](docs/SPEC_DATA_PROVIDERS.md) — провайдеры котировок, дивидендов, ставок
- [SPEC_FRONTEND.md](docs/SPEC_FRONTEND.md) — фронтенд, виджеты, синхронизация графиков
- [SPEC_PRECEDENT_LANGUAGE.md](docs/SPEC_PRECEDENT_LANGUAGE.md) — Спецификация запроса поиска прецендентов
- [SPEC_BACKTEST.md](docs/SPEC_BACKTEST.md) — движок бэктеста, стратегии, правила, окружения, прогоны
- [SPEC_RESEARCH.md](docs/SPEC_RESEARCH.md) — исследование как контекст работы

**Методология**
- [EXPECTED_RETURN_MODELS.md](docs/EXPECTED_RETURN_MODELS.md) — модели ожидаемой доходности. Используются в методологии событийного анализа.
- [TAGS.md](docs/TAGS.md) — система тегов событий

**Прикладное**
- [BACKTEST_STRATEGIES.md](docs/BACKTEST_STRATEGIES.md) — каталог реализованных стратегий и их результатов
- [BACKTEST_ANOMALIES.md](docs/BACKTEST_ANOMALIES.md) — стратегии на аномалиях
- [BACKTEST_RUNNER_AGENT.md](docs/BACKTEST_RUNNER_AGENT.md) — инструкции для агента для прогона стратегий
- [TEST_PLAN.md](docs/TEST_PLAN.md) — план тестов
