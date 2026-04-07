# data-core

Система событийного анализа: как события (дивиденды, санкции, корпоративные новости) влияют на котировки акций. Магистерская дипломная работа.

Состоит из трёх частей:

- **`core/`** — Python-пакет с логикой: загрузка котировок, расчёт CAR, event study, нормализация и т.п.
- **`backend/`** — FastAPI-сервер, тонкая обёртка над `core/`, отдаёт данные фронту по REST.
- **`frontend/`** — React-приложение с плавающими виджетами: графики цен, индексов и интерактивный event study.

Раньше анализ жил только в Jupyter-ноутбуках и Dash-дашбордах (`notebooks/`). Они остаются для research, но для интерактивной работы используется фронт.

---

## Установка

### 1. Python (через conda)

```bash
# создать окружение
conda create -n data-core python=3.11
conda activate data-core

# зависимости (нужны для ноутбуков и анализа)
conda install -c conda-forge pandas numpy gensim plotly dash matplotlib nltk scikit-learn umap-learn hdbscan
conda install -c conda-forge spacy pymorphy3 ipywidgets notebook openpyxl duckdb

# spaCy модели
python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm

# поставить пакет core в editable-режиме (pyproject.toml лежит в backend/)
cd backend
pip install -e .
cd ..
```

После `pip install -e .` пакет `core` доступен для импорта откуда угодно (`from core.event_study import EventStudy`). При изменении кода переустанавливать не нужно.

### 2. Frontend (Node.js + npm)

Нужен Node.js 20+ и npm.

```bash
cd frontend
npm install
```

---

## Запуск

Нужно два терминала: один для бэка, второй для фронта.

### Терминал 1 — backend (порт 8080)

```bash
cd backend
python -m uvicorn main:app --reload --port 8080 --host 127.0.0.1
```

Проверка: http://127.0.0.1:8080/docs — Swagger UI с описанием API.

### Терминал 2 — frontend (порт 5173)

```bash
cd frontend
npm run dev
```

Открыть в браузере: **http://127.0.0.1:5173**

> **Windows:** обязательно `127.0.0.1`, не `localhost` — Vite на localhost не биндится.

---

## Как пользоваться

В тулбаре сверху — кнопка «+ Добавить виджет». Доступны три типа:

- **Price chart** — график цены акции, с маркерами дивидендов.
- **Index chart** — IMOEX или RUONIA.
- **Event study** — расчёт CAR для выбранного события.

Виджеты можно перетаскивать (за заголовок или нижнюю полосу), менять размер за правый нижний угол, закрывать крестиком.

### Связывание виджетов: логические группы и ведущий график

Слева в заголовке каждого виджета — кружок цвета. Клик открывает палитру (`none / red / blue / green / yellow`). Виджеты одного цвета считаются одной **логической группой**.

В каждой группе можно назначить **ведущий график** — кнопкой с круговыми стрелками рядом с дропдауном. Поведение группы зависит от этого:

- **Если в группе есть ведущий** — все остальные графики становятся ведомыми и автоматически повторяют за ним зум/панораму и положение crosshair. Кнопка ведущего подсвечена синим, у ведомых — disabled.
- **Если ведущего нет** — графики группы не синхронизируются (ведут себя независимо).
- **Снять синхронизацию** — toggle кнопки на ведущем (или сменить ему группу).

Event Study автоматически привязывается к ведущему price chart своей группы: его тикер форсится из лидера, а собственный дропдаун тикера блокируется. Если ведущего в группе нет — Event Study блокируется заглушкой «Выберите ведущий price chart в группе».

Контекст исследования (подсветка активного события, hover-sync с CAR, авто-зум на event window при «Рассчитать») работает в любой непустой группе независимо от наличия ведущего — это отдельный канал «контекста», а не навигации.

Группа `none` = виджет автономен, ни с кем не связан. Event Study в `none` работает в одиночном режиме с полным дропдауном тикеров.

---

## Тесты

```bash
cd backend
pytest tests/ -v
```

---

## Документация

- `docs/GLOSSARY.md` — единый словарь проекта (методология + сущности приложения)
- `docs/SPEC_FRONTEND.md` — спецификация фронта (архитектура, API, leader-driven sync)
- `docs/PLAN_FRONTEND.md` — план реализации фронта со статусами
- `docs/SPEC_*.md` — спецификации других подсистем
- `docs/TEST_PLAN.md` — план тестов
- `backend/notebooks/` — research-ноутбуки

---

## Структура

```
data-core/
├── backend/            # вся Python-часть (директория, не пакет)
│   ├── pyproject.toml  # editable-установка пакета core
│   ├── main.py         # FastAPI-сервер, все endpoints
│   ├── core/           # Python-пакет: загрузка данных, event study, метрики
│   ├── notebooks/      # Jupyter-ноутбуки для research
│   └── tests/
├── frontend/           # React + Vite + Lightweight Charts
│   └── src/widgets/    # PriceChart, IndexChart, EventStudy + sync механика
├── data/               # котировки, дивиденды, IMOEX, RUONIA, ИПЦ
├── docs/               # спецификации, планы, глоссарий
├── scripts/            # ETL и вспомогательные скрипты
└── models/             # артефакты ML-моделей (BERTopic и др.)
```
