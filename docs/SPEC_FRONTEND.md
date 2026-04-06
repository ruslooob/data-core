# Спецификация: Full-stack фронтенд для анализа котировок и событий

## Контекст и мотивация

Текущие дашборды на Dash/Plotly упёрлись в архитектурные ограничения (см. `docs/DASH_LIMITATIONS_STOCK_VIEWER.md`): нельзя плавно зумить/пролистывать большие ряды, нет автоскейла Y при навигации, нет overlapping panels, серверный round-trip тормозит. Для терминало-подобного интерактивного анализа нужен клиентский JS.

Решение — разделить систему на два приложения: **Python-бэкенд** (тонкая обёртка над `core/`) и **React-фронтенд** с графической библиотекой Lightweight Charts.

---

## Общая картина

```
┌─────────────────┐         HTTP/JSON          ┌──────────────────┐
│   Frontend      │ ◄─────────────────────────► │    Backend       │
│   React + Vite  │         REST API            │    FastAPI       │
│   Lightweight   │                             │                  │
│   Charts        │                             │  обёртка над     │
│                 │                             │  core/*          │
│  localhost:5173 │                             │  localhost:8080  │
└─────────────────┘                             └──────────────────┘
                                                         │
                                                         ▼
                                                 ┌──────────────┐
                                                 │  core/       │
                                                 │  stock_data  │
                                                 │  dividends   │
                                                 │  event_study │
                                                 └──────────────┘
```

- Backend ничего не хранит — при запросе зовёт соответствующий модуль `core/`.
- Frontend — единственный источник UI. Вся логика отрисовки и интеракции на клиенте.
- Без авторизации, без базы данных на бэкенде, без SSR.

---

## Структура репозитория

```
data-core/
├── core/          # существующий Python пакет
├── notebooks/     # существующие ноутбуки (для research)
├── data/
├── tests/
├── docs/
├── backend/       # НОВОЕ: FastAPI сервер
└── frontend/      # НОВОЕ: React + Vite проект
```

---

## Backend

### Стек
- **FastAPI** — простота + автоматическая валидация (pydantic) + автодоки (Swagger UI)
- **uvicorn** — ASGI-сервер
- Зависит от существующего пакета `core`

### Порт
- `localhost:8080`
- Swagger UI доступен на `localhost:8080/docs`

### CORS
- Разрешить `localhost:5173` (dev-сервер Vite)

### REST API

| Метод | Endpoint | Описание |
|---|---|---|
| `GET` | `/api/tickers` | Список доступных тикеров |
| `GET` | `/api/prices/{ticker}?start=&end=` | Котировки (OHLCV) для тикера |
| `GET` | `/api/events?ticker=&start=&end=` | Список дивидендных событий с фильтрами |
| `GET` | `/api/events/{id}` | Одно событие по ID |
| `POST` | `/api/event-study` | Расчёт CAR для события |

**`POST /api/event-study` — тело запроса:**
```json
{
    "ticker": "LKOH",
    "event_date": "2015-04-28",
    "model": "market_model",
    "event_window": [-10, 10],
    "estimation_window": 200
}
```

**Ответ:**
```json
{
    "event_date": "2015-04-28",
    "ar": [...],
    "car": -0.027696,
    "n_days": 21,
    "estimation_std": 0.011280
}
```

### Логика
Backend — тонкая обёртка. Каждый endpoint вызывает соответствующую функцию `core/`:
- `/api/tickers` → `stock_data_provider.list_avail_tickers()` (или аналог)
- `/api/prices/{ticker}` → `stock_data_provider.get_stock_data()`
- `/api/events` → `dividend_data_provider.load_dividends()` + фильтры
- `/api/event-study` → `core.event_study.EventStudy.analyze()`

---

## Frontend

### Стек
- **Vite** — dev-сервер и bundler
- **React + TypeScript** — UI + типизация API-контрактов
- **Lightweight Charts** (TradingView, open source) — терминало-подобные графики с автоскейлом Y, rangeslider, overlapping panels
- **npm** — менеджер пакетов

### Порт
- `localhost:5173`

### Виджеты (MVP)

Виджет = независимое плавающее окно с графиком / панелью.

**Размещение:**
- Плавающие окна с абсолютным позиционированием (полотно во весь экран)
- Новый виджет появляется по центру с каскадным смещением, чтобы не перекрывать существующие
- Размер по умолчанию: 640×480
- **Drag** — перетаскивание за заголовок виджета
- **Resize** — за правый нижний угол (CSS `resize: both` + ResizeObserver для синхронизации графика внутри)

**Тулбар** — сверху страницы, содержит кнопку «+ Добавить виджет» (меню выбора типа). В будущем — другие инструменты.

#### 1. Price chart widget
- Линейный график цены (CLOSE) для выбранного тикера
- Встроенная панель объёма снизу (из коробки Lightweight Charts)
- Тикер выбирается внутри виджета через дропдаун
- Интеракция из коробки: зум колесом, drag, автоскейл Y, crosshair
- Без событий — чистый график цены. События относятся к event study widget.

#### 2. Event study widget
- Всё функциональность из `notebooks/22_event_study_interactive.ipynb` в нативной JS-реализации:
  - Дропдауны: тикер → событие, модель
  - Слайдеры: дней до/после t=0, длина оценочного окна
  - Кнопка «Рассчитать» + кнопки навигации ←/→ по событиям
  - График CAR с доверительным интервалом (95%)
  - Карточки метрик: CAR, vol_ratio, volume_ratio, дней в окне
- Независимый виджет, не накладывается на price chart
- Все три модели: `mean_adjusted`, `market_model`, `capm`

### Сопоставление графиков (sync-группы по цвету)
- В заголовке каждого price chart виджета — пикер цветовой группы (none/red/blue/green/yellow)
- Виджеты в одной цветовой группе синхронизируются между собой:
  - **Visible time range** — по центру окна. При сдвиге master'а slave сохраняет свою длительность/масштаб (bar spacing), смещается только центр. Если новый диапазон выходит за края данных slave'а — клампится к границам.
  - **Crosshair** — позиция курсора пробрасывается между графиками группы.
- Защита от echo-feedback: `WeakMap<chart, lastAppliedAt>` с окном игнора 150 мс.
- Группа `none` = виджет автономен.
- API Lightweight Charts v5: использовать `subscribeVisibleTimeRangeChange` + `setVisibleRange` (не logical range — он даёт расхождение по датам между тикерами с разной историей). `subscribe*` возвращает `void` — отписка через `unsubscribe*(handler)`.
- `timeScale.fixLeftEdge: true, fixRightEdge: true` — запретить пролистывание за края данных.
- Event study виджеты управляются независимо.

### Данные
- Frontend кэширует ответы API на клиенте
- Тикеры и список событий префетчатся при старте
- Котировки запрашиваются при создании/переключении price chart
- Event study результаты — при каждом расчёте (через POST)

---

## Запуск в dev-режиме

Два терминала:

```bash
# Terminal 1 — backend
cd backend
uvicorn main:app --reload --port 8080

# Terminal 2 — frontend
cd frontend
npm run dev
```

---

## Что вне MVP

- Dashboard-сетка с перетаскиваемыми плитками (snap-to-grid)
- Сохранение layout виджетов между сессиями (localStorage)
- Авторизация
- Сохранение layout виджетов между сессиями
- SSR, статическая генерация
- Лассо для выделения областей на графике
- Аутентификация / роли пользователей
- Тесты backend (будут добавлены отдельно по запросу)
- Production-деплой (хостинг, CI/CD)
