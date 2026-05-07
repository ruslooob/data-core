# data-core

Рабочее место финансового аналитика: событийный анализ, поиск аномалий, исследование влияния событий на котировки акций. Магистерская дипломная работа.

Состоит из трёх частей:

- **`backend/`** — Python-часть: `core/` (доменная логика), `main.py` (FastAPI), `notebooks/`, `tests/`.
- **`frontend/`** — React-приложение с плавающими виджетами.
- **`data/`**, **`docs/`**, **`scripts/`** — данные, документация, скрипты загрузки.

---

## Установка

### 1. Python (через conda)

```bash
conda create -n data-core python=3.11
conda activate data-core

conda install -c conda-forge pandas numpy gensim plotly dash matplotlib nltk scikit-learn umap-learn hdbscan
conda install -c conda-forge spacy pymorphy3 ipywidgets notebook openpyxl duckdb psycopg

python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm

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

### 3. Docker (для Postgres)

Нужен Docker Desktop.

---

## Запуск с нуля на новом ноутбуке

После клонирования репозитория и установки Python/Node/Docker (см. выше):

```bash
# 1. Поднять Postgres
docker compose up -d postgres

# 2. Восстановить БД из снапшота (схема + UDF + все данные разом)
#    snapshot.dump передаётся отдельно (не в репозитории)
docker cp data/db/snapshot.dump data-core-postgres:/tmp/snapshot.dump
docker exec data-core-postgres pg_restore -U postgres -d postgres \
    --single-transaction /tmp/snapshot.dump

# 3. Залить референсные данные из файлов (идемпотентно, ON CONFLICT DO NOTHING)
#    котировки, RUONIA, дивиденды
python scripts/load_data_to_postgres.py

# 4. Убедиться, что схема актуальна (должно быть 0 pending changesets)
docker compose --profile migrate run --rm liquibase status

# 5. Проверка
cd backend && pytest tests/ -v
```

Снапшот `data/db/snapshot.dump` обновляется командой:

```bash
docker exec data-core-postgres pg_dump -U postgres -d postgres \
    --format=custom --file=/tmp/snapshot.dump
docker cp data-core-postgres:/tmp/snapshot.dump data/db/snapshot.dump
```

---

## Запуск приложения

Два терминала: backend и frontend (Postgres уже должен быть поднят).

### Backend (порт 8080)

```bash
cd backend
python -m uvicorn main:app --reload --port 8080 --host 127.0.0.1
```

Проверка: http://127.0.0.1:8080/docs

### Frontend (порт 5173)

```bash
cd frontend
npm run dev
```

Открыть: **http://127.0.0.1:5173**

> **Windows:** обязательно `127.0.0.1`, не `localhost`.

---

## Как пользоваться

В тулбаре сверху — кнопка «+ Добавить виджет». Доступны четыре типа:

- **Price chart** — график цены акции с маркерами дивидендов.
- **Index chart** — IMOEX или RUONIA.
- **Event study** — расчёт CAR для выбранного события с фильтрацией выбросов в оценочном окне.
- **Anomaly detector** — автоматический поиск аномалий по набору тикеров и событий.

Виджеты можно перетаскивать, менять размер, закрывать.

### Логические группы и ведущий график

Слева в заголовке виджета — кружок цвета. Виджеты одного цвета — одна **логическая группа**.

В группе можно назначить **ведущий график** — кнопкой рядом с дропдауном тикера:

- **Есть ведущий** — остальные графики повторяют за ним зум и crosshair. Event study привязывается к тикеру ведущего.
- **Нет ведущего** — графики независимы.
- Группа `none` = виджет автономен.

Контекст исследования (подсветка события, hover-sync, авто-зум) работает в любой непустой группе независимо от наличия ведущего.

---

## Тесты

```bash
cd backend
pytest tests/ -v
```

---

## Документация

- `docs/GLOSSARY.md` — единый словарь проекта
- `docs/OVERVIEW.md` — обзор системы и архитектура
- `docs/SPEC_FRONTEND.md` — спецификация фронтенда
- `docs/SPEC_EVENT_FILTER.md` — спецификация виджета фильтра событий
- `docs/ANOMALY_DETECTION.md` — поиск аномалий
- `docs/ANOMALY_DSL.md` — язык запросов для аномалий
- `docs/ROBUSTNESS_CHECK.md` — проверка устойчивости
- `docs/TAGS.md` — система тегов событий
- `docs/METRICS.md` — интерпретация метрик
- `docs/TEST_PLAN.md` — план тестов

---

## Структура

```
data-core/
├── backend/            # Python-часть
│   ├── pyproject.toml
│   ├── main.py         # FastAPI-сервер
│   ├── core/           # доменная логика: event study, anomaly detector, провайдеры данных
│   ├── notebooks/      # Jupyter-ноутбуки для research
│   └── tests/
├── frontend/           # React + Vite + Lightweight Charts
│   └── src/widgets/    # PriceChart, IndexChart, EventStudy, AnomalyWidget + sync
├── data/               # котировки, дивиденды, IMOEX, RUONIA, ИПЦ, БД событий
├── docs/               # спецификации, глоссарий, планы
├── scripts/            # загрузка данных (mfd.ru, dohod.ru)
└── models/             # артефакты ML-моделей
```
