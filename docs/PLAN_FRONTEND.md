# План реализации: Full-stack фронтенд

План разбит на маленькие шаги. После каждого — пауза для валидации пользователем.

---

## Этап 1: Backend skeleton

### Шаг 1.1 — Создать структуру backend
- Создать папку `backend/`
- `backend/main.py` — минимальный FastAPI app с endpoint `GET /api/health` → `{"status": "ok"}`
- Добавить в `pyproject.toml`: `fastapi`, `uvicorn[standard]`
- CORS middleware разрешает `http://localhost:5173`

**Критерий приёмки:**
- `uvicorn backend.main:app --reload --port 8080` запускается
- `curl localhost:8080/api/health` возвращает `{"status": "ok"}`
- `localhost:8080/docs` открывает Swagger UI

---

### Шаг 1.2 — Endpoint /api/tickers
- `GET /api/tickers` возвращает `list[str]` доступных тикеров
- Внутри вызывает `stock_data_provider` (использовать существующую функцию списка тикеров или `os.listdir(data/stocks)` с фильтрацией)

**Критерий приёмки:**
- `curl localhost:8080/api/tickers` возвращает JSON-массив тикеров
- В массиве есть LKOH, SBER, UPRO и т.д.

---

### Шаг 1.3 — Endpoint /api/prices/{ticker}
- `GET /api/prices/{ticker}?start=YYYY-MM-DD&end=YYYY-MM-DD`
- Параметры `start` и `end` опциональные
- Возвращает `list[{date, open, high, low, close, volume}]`
- Внутри вызывает `stock_data_provider.get_stock_data(ticker)` и фильтрует по датам
- Pydantic-модели для валидации ответа

**Критерий приёмки:**
- `curl localhost:8080/api/prices/LKOH?start=2015-01-01&end=2015-12-31` возвращает ~250 точек
- Формат ответа — OHLCV

---

### Шаг 1.4 — Endpoint /api/events
- `GET /api/events?ticker=&start=&end=` — все параметры опциональные
- Возвращает `list[{id, ticker, event_date, dividend, year}]`
- Внутри вызывает `dividend_data_provider.load_dividends()` и фильтрует
- `id` — порядковый номер или комбинация `ticker_date`

**Критерий приёмки:**
- `curl localhost:8080/api/events` возвращает 110 событий
- `curl localhost:8080/api/events?ticker=LKOH` возвращает только дивиденды LKOH

---

### Шаг 1.5 — Endpoint POST /api/event-study
- `POST /api/event-study` с телом: `ticker, event_date, model, event_window, estimation_window`
- Pydantic-модели для request и response
- Внутри:
  1. Загружает котировки тикера (`get_log_returns`)
  2. Загружает IMOEX и RUONIA (`market_data_provider`)
  3. Создаёт `EventStudy` и вызывает `analyze()`
  4. Возвращает `EventResult` как JSON

**Критерий приёмки:**
- POST с валидными данными возвращает CAR, AR, estimation_std
- CAR совпадает со значениями из nb22 для тех же параметров

---

## Этап 2: Frontend skeleton

### Шаг 2.1 — Инициализация React + Vite проекта
- В папке `frontend/` создать проект через `npm create vite@latest . -- --template react-ts`
- Установить зависимости: `npm install`
- Настроить proxy в `vite.config.ts` для `/api` → `http://localhost:8080`

**Критерий приёмки:**
- `npm run dev` запускает dev-сервер на `localhost:5173`
- Дефолтная страница Vite открывается

---

### Шаг 2.2 — API-клиент
- `frontend/src/api/client.ts` — функции для всех endpoint:
  - `getTickers()` → `Promise<string[]>`
  - `getPrices(ticker, start?, end?)` → `Promise<Candle[]>`
  - `getEvents(params?)` → `Promise<DividendEvent[]>`
  - `runEventStudy(params)` → `Promise<EventResult>`
- TypeScript-типы для всех ответов
- Простой fetch, без axios

**Критерий приёмки:**
- Все функции типизированы
- Работает с backend через proxy
- В `App.tsx` тест-вызов `getTickers()` и вывод списка на экран

---

### Шаг 2.3 — Layout с плавающими виджетами
- Убрать дефолтный контент Vite и мусорные глобальные стили
- Создать компонент `WidgetContainer` с тулбаром сверху (кнопка «+ Добавить виджет»)
- Тулбар вызывает меню выбора типа виджета (Price chart / Event study)
- Виджеты — плавающие окна (`position: absolute`), появляются по центру с каскадным смещением
- Размер по умолчанию 640×480, `resize: both` для изменения
- Drag за заголовок через `mousedown/move/up` + абсолютные координаты в state
- Кнопка закрытия × в заголовке

**Критерий приёмки:**
- Кнопка «+ Добавить виджет» сверху
- Виджет появляется в центре экрана фиксированного размера
- Виджет перетаскивается за заголовок, закрывается, меняет размер за угол

---

## Этап 3: Price chart widget

### Шаг 3.1 — Установка Lightweight Charts
- `npm install lightweight-charts`
- Создать компонент `PriceChartWidget` с пустым графиком
- React-хук для инициализации/уничтожения chart на mount/unmount

**Критерий приёмки:**
- При добавлении виджета Price chart — появляется пустой график

---

### Шаг 3.2 — Загрузка и отрисовка котировок
- Внутри виджета дропдаун с тикерами (из `getTickers()`)
- При выборе тикера — `getPrices(ticker)` → отрисовка на графике
- Объём как отдельный series в нижней панели (через Lightweight Charts panes)
- График синхронизируется с размером карточки виджета через ResizeObserver (flex: 1 + 100% размер)

**Критерий приёмки:**
- Выбираешь LKOH → видишь кривую цены + гистограмму объёма снизу
- Работают зум, скролл, crosshair
- При изменении размера карточки-виджета график синхронно подстраивается

---

### Шаг 3.3 — Синхронизация нескольких price chart виджетов по X
- Если есть два+ price chart виджета — зум/скролл одного двигает остальные
- Используется visible range sync от Lightweight Charts

**Критерий приёмки:**
- Добавляешь два виджета (LKOH и SBER)
- Двигаешь один — второй синхронно перемещается по времени

---

## Этап 4: Event study widget

### Шаг 4.1 — UI: дропдауны, слайдеры, кнопки
- Компонент `EventStudyWidget` с контролами:
  - Дропдаун тикера
  - Дропдаун события (фильтруется по тикеру)
  - Дропдаун модели
  - Слайдеры: дней до, дней после, длина оценочного окна
  - Кнопка «Рассчитать»
  - Кнопки ←/→ для навигации по событиям

**Критерий приёмки:**
- Все контролы отрисованы
- Дропдаун событий фильтруется при смене тикера

---

### Шаг 4.2 — Расчёт и отображение CAR
- При нажатии «Рассчитать» → `runEventStudy(params)` → получаем `EventResult`
- Отрисовка кривой CAR на Lightweight Charts
- Доверительный интервал ±2σ√N как area series
- Вертикальная линия на t=0

**Критерий приёмки:**
- Нажимаешь «Рассчитать» — видишь кривую CAR
- Значения совпадают с nb22 для тех же параметров

---

### Шаг 4.3 — Метрики-карточки
- Под графиком CAR — карточки: CAR%, коэф. волатильности, коэф. объёма, дней в окне
- Стиль как в nb22

**Критерий приёмки:**
- Карточки отображаются после расчёта
- Значения совпадают с nb22

---

### Шаг 4.4 — Навигация по событиям
- Кнопки ←/→ переключают событие в дропдауне
- Автоматический пересчёт при смене события

**Критерий приёмки:**
- Стрелки работают, событие меняется, график обновляется

---

## Этап 5: Полировка

### Шаг 5.1 — Стили и UX
- Единый визуальный стиль (цвета, отступы, шрифты)
- Кнопка закрытия виджета
- Loading states при запросах

### Шаг 5.2 — Readme для запуска
- Секция в `README.md`: как запустить backend + frontend

---

## Итого

- **Этапов:** 5
- **Шагов:** 13
- После каждого шага — пауза на валидацию

Начинаем с **Шаг 1.1**.
