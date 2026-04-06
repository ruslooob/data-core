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

# поставить core и backend в editable-режиме
pip install -e .
```

После `pip install -e .` пакеты `core` и `backend` доступны для импорта откуда угодно. При изменении кода переустанавливать не нужно.

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
python -m uvicorn backend.main:app --reload --port 8080 --host 127.0.0.1
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

### Связывание виджетов: цветовые группы

Слева в заголовке каждого виджета — кружок цвета. Клик открывает палитру (`none / red / blue / green / yellow`).

Виджеты в одной цветовой группе **синхронизируются**:

- Зум/панорама и crosshair у price chart'ов одной группы синхронизируются.
- Event study фильтрует список тикеров по price chart'ам своей группы.
- Когда в Event Study выбираешь событие — на price chart и index chart той же группы появляется красная подсветка t=0 и границ окна.
- Hover на CAR двигает crosshair на price/index chart и показывает соответствующую дату.
- Кнопка «Рассчитать» в Event Study автоматически зумит все графики группы на event window.

Группа `none` = виджет автономен, ни с кем не связан.

---

## Тесты

```bash
pytest tests/ -v
```

---

## Документация

- `docs/SPEC_FRONTEND.md` — спецификация фронта (архитектура, API, sync-группы)
- `docs/PLAN_FRONTEND.md` — план реализации фронта со статусами
- `docs/SPEC_*.md` — спецификации других подсистем
- `docs/TEST_PLAN.md` — план тестов
- `notebooks/` — research-ноутбуки

---

## Структура

```
data-core/
├── core/               # Python-пакет: загрузка данных, event study, метрики
├── backend/            # FastAPI-сервер
│   └── main.py         # все endpoints
├── frontend/           # React + Vite + Lightweight Charts
│   └── src/widgets/    # PriceChart, IndexChart, EventStudy + sync механика
├── notebooks/          # Jupyter-ноутбуки для research
├── data/               # котировки, дивиденды, IMOEX, RUONIA, ИПЦ
├── docs/               # спецификации, планы
├── tests/
└── scripts/            # ETL и вспомогательные скрипты
```
