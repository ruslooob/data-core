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
| `GET` | `/api/health` | Healthcheck |
| `GET` | `/api/tickers` | Список доступных тикеров (без служебных файлов DIVIDENDS/IMOEX/RUONIA/SPLITS) |
| `GET` | `/api/prices/{ticker}?start=&end=` | Котировки (OHLCV) для тикера |
| `GET` | `/api/events?ticker=&start=&end=` | Список дивидендных событий с фильтрами |
| `POST` | `/api/event-study` | Расчёт AR/CAR для события |

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

### Виджеты

Виджет = независимое плавающее окно с графиком / панелью.

**Полотно и размещение:**
- Прокручиваемое полотно фиксированного размера 4000×3000 (см. `WidgetContainer`). При упоре — обсуждаем динамический рост.
- Виджеты — плавающие (`position: absolute` относительно полотна) с каскадным смещением
- Новый виджет появляется в **центре видимой области** (учитывает `window.scrollX/scrollY`)
- Размер по умолчанию: 640×480
- **Drag** — за заголовок ИЛИ за нижнюю 10-пиксельную полосу (на случай если виджет упёрся в верх). Правые 16px нижней полосы оставлены для resize-grabber
- **Resize** — за правый нижний угол (CSS `resize: both` + ResizeObserver для синхронизации графика внутри)
- **Z-order** — по клику в любую часть виджета он поднимается на самый верх (счётчик `topZ` в контейнере). Перетаскиваемый виджет автоматически оказывается над тем, на который его тащат

**Тулбар** — `position: sticky; top: 0; width: 100vw`, содержит кнопку «+ Добавить виджет» (меню выбора типа). Остаётся видимым при любом скролле полотна.

#### 1. Price chart widget
- Линейный график цены (CLOSE) для выбранного тикера + панель объёма снизу (panes Lightweight Charts)
- Тикер выбирается внутри виджета через дропдаун
- Интеракция из коробки: зум колесом, drag, автоскейл Y, crosshair
- **Маркеры дивидендных событий** — серые треугольники под барами для всех событий тикера (через `createSeriesMarkers`)
- **Подсветка активного события группы** (если тикер совпадает): красный кружок «t=0» над баром, красные стрелки `−N` / `+M` на границах event window
- **Клик** по маркеру (в пределах ±2 дней от события) → публикует `requestSelectEvent` в группу — Event Study виджет той же группы выбирает это событие и пересчитывает
- Подписка на `requestZoom` группы → `setVisibleRange`
- Подписка на `broadcastHoverDate` → `setCrosshairPosition` на ближайший бар (синхронизация курсора с CarChart)

#### 2. Event study widget
- Контролы:
  - Дропдауны: тикер, событие (фильтруется по тикеру), модель
  - Слайдеры: дней до t=0, дней после, длина оценочного окна
  - Кнопка «Рассчитать»
  - Кнопки навигации ←/→ по событиям (правее «Рассчитать»)
- График CAR (компонент `CarChart`):
  - Кривая CAR (cumsum AR) в **процентах**
  - CI ±2σ√k в процентах, пунктиром
  - Нулевая горизонтальная линия + красный маркер «t=0»
  - **CI и нулевая линия исключены из autoscale** (`autoscaleInfoProvider: () => null`) — иначе раздувшийся CI прижимает CAR к нулю
  - Ось X — относительные торговые дни, метки `+5` / `-3` / `t=0` через `tickMarkFormatter` + `localization.timeFormatter` (синтетические timestamps от 2000-01-01)
- Все три модели: `mean_adjusted`, `market_model`, `capm`
- При **«Рассчитать»** и при **навигации стрелками** автоматически:
  - публикуется активное событие в группу (для подсветки на price chart)
  - запрашивается зум price chart'ов группы на event window ×3
  - запускается расчёт
- При **hover на CAR** — публикуется `broadcastHoverDate(group, event_date + t дней)` → price chart показывает crosshair на ближайшем баре

**Не реализовано:** карточки метрик (CAR%, vol_ratio, volume_ratio).

### Sync-группы по цвету

В заголовке **каждого** виджета (и price chart, и event study) — пикер цветовой группы: `none / red / blue / green / yellow`. Группа `none` = виджет автономен.

Семантика группы — несколько независимых каналов связи. Реализованы в двух модулях:

**`chartSync` (только price chart ↔ price chart)** — синхронизация навигации:
- **Visible time range** — по центру окна. При сдвиге master'а slave сохраняет свою длительность/масштаб (bar spacing), смещается только центр. Если новый диапазон выходит за края данных slave'а — клампится к границам
- **Crosshair** — позиция курсора пробрасывается между графиками группы
- Защита от echo-feedback: `WeakMap<chart, lastAppliedAt>` с окном игнора 150 мс
- API Lightweight Charts v5: `subscribeVisibleTimeRangeChange` + `setVisibleRange` (НЕ logical range — он даёт расхождение по датам между тикерами с разной историей). `subscribe*` возвращает `void`, отписка через `unsubscribe*(handler)`
- `timeScale.fixLeftEdge: true, fixRightEdge: true` — запретить пролистывание за края данных

**`groupRegistry` (price chart ↔ event study)** — связь по контексту, отдельная шина:
- **Состав группы** — `register/unregister/setGroup/setTicker`. Event Study фильтрует свой dropdown тикеров по объединению тикеров price chart'ов своей группы. Если в группе нет price chart — фоллбек на все тикеры. Если текущий тикер выпал из списка — авто-переключение на первый
- **Активное событие группы** — `setActiveEvent / subscribeActiveEvent / getActiveEvent`. Event Study публикует `{ticker, event_date, daysBefore, daysAfter}`, price chart'ы рисуют подсветку. Конфликт двух ES в одной группе разрешается «последний победил»
- **Zoom-команда** — `requestZoom / subscribeZoom`. Event Study запрашивает зум на event window ×3, price chart'ы группы зовут `setVisibleRange`
- **Select-event-команда** — `requestSelectEvent / subscribeSelectEvent`. Клик по маркеру события на price chart → Event Study выбирает событие и автоматически пересчитывает (через `calcRef` + `setTimeout(0)` для применения state)
- **Hover-date канал** — `broadcastHoverDate / subscribeHoverDate`. CarChart на crosshair публикует `event_date + t календарных дней`, price chart'ы зовут `setCrosshairPosition` на ближайший бар. Lightweight-charts снэпит к торговому дню, выходные округляются

Разделение `chartSync` vs `groupRegistry` сделано осознанно: range/crosshair sync — узкая механика только для price chart; всё остальное — про контекст и взаимосвязь виджетов.

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

- Карточки метрик в Event Study (CAR%, vol_ratio, volume_ratio, дней в окне)
- Динамически растущее полотно или pan/zoom canvas (Figma-like)
- Вкладки с независимыми наборами виджетов
- Сохранение layout виджетов между сессиями (localStorage)
- Snap-to-grid сетка
- Лассо для выделения областей на графике
- Авторизация / роли
- SSR, статическая генерация
- Тесты backend (будут добавлены отдельно по запросу)
- Production-деплой (хостинг, CI/CD)
