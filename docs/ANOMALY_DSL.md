# Язык запросов для поиска аномалий

SQL-подобный DSL для поиска аномалий на финансовых рынках. Пользователь пишет запрос — система вычисляет метрики для каждого события и фильтрует по условиям.

---

## Структура запроса

```
[SET ...]          -- параметры расчёта (опционально, есть дефолты)
[DEFINE ...]       -- пользовательские метрики (опционально)
SELECT ...         -- какие колонки показать
FROM events        -- источник — таблица событий
[JOIN ...]         -- для продвинутых: join с tags
WHERE ...          -- условия фильтрации = anomaly rule
[ORDER BY ...]     -- сортировка
[LIMIT N]          -- ограничение выдачи
```

---

## SET — параметры расчёта

Задают глобальные переменные, от которых зависят встроенные примитивы (`ar`, `car` и т.д.).

```sql
SET model = 'market_model'    -- модель ожидаемой доходности
SET estimation = 200          -- длина оценочного окна (торговых дней)
SET window = (-10, 10)        -- окно события
```

Дефолтные значения: `model='market_model'`, `estimation=200`, `window=(-10, 10)`.

---

## Примитивы данных

Доступны для каждого события. `t` — торговый день относительно даты события (t=0).

| Примитив | Описание |
|----------|----------|
| `price(t)` | Цена закрытия в день t |
| `volume(t)` | Объём торгов в день t |
| `return(t)` | Дневная логдоходность |
| `market_return(t)` | Доходность индекса рынка |
| `ar(t)` | Аномальная доходность (зависит от SET model) |

## Функции агрегации

Работают по диапазону дней `[from, to]` относительно t=0.

| Функция | Описание |
|---------|----------|
| `sum(expr, from, to)` | Сумма |
| `mean(expr, from, to)` | Среднее |
| `std(expr, from, to)` | Стандартное отклонение |
| `max(expr, from, to)` | Максимум |
| `min(expr, from, to)` | Минимум |
| `count(expr, from, to)` | Количество |

## Математические функции

`abs()`, `log()`, `sqrt()`, `pow()`

## Условные выражения

Стандартный SQL `CASE WHEN ... THEN ... ELSE ... END`.

---

## DEFINE — пользовательские метрики

Именованные выражения из примитивов. Используются в SELECT, WHERE, ORDER BY наравне со встроенными.

```sql
-- Встроенные метрики — это тоже DEFINE, просто предопределённые:
-- car = sum(ar, window_start, window_end)
-- volume_ratio = mean(volume, 1, window_end) / mean(volume, window_start, -1)
-- vol_ratio = std(return, 1, window_end) / std(return, window_start, -1)

-- Пользовательские:
DEFINE pre_event_car = sum(ar, -5, -1)
DEFINE price_growth_5d = max(price, 0, 5) / price(0) - 1
```

---

## HAS_TAG — сахар для фильтрации по тегам

```sql
WHERE HAS_TAG('LKOH')           -- событие имеет тег LKOH
  AND HAS_TAG('DIVIDEND')       -- и тег DIVIDEND
```

Разворачивается в:
```sql
WHERE EXISTS (SELECT 1 FROM event_tags WHERE event_id = e.id AND tag_code = 'LKOH')
  AND EXISTS (SELECT 1 FROM event_tags WHERE event_id = e.id AND tag_code = 'DIVIDEND')
```

Продвинутые пользователи могут писать JOIN напрямую.

---

## Примеры

### 1. Значимые дивидендные события LKOH

```sql
-- Дефолтные параметры: model='market_model', window=(-10,10), estimation=200

SELECT date_start, event, car, volume_ratio
FROM events
WHERE HAS_TAG('LKOH')
  AND HAS_TAG('DIVIDEND')
  AND car > 0.03
ORDER BY car DESC
```

*Все дивидендные события LKOH с CAR выше 3%.*

### 2. Поиск инсайдерской торговли перед дивидендами

```sql
SET model = 'market_model'
SET window = (-20, 10)
SET estimation = 200

-- Накопленная аномальная доходность за 5 дней ДО события
DEFINE pre_event_car = sum(ar, -5, -1)

-- Во сколько раз средний объём за 5 дней до события
-- превышает фоновый уровень (15 дней ранее)
DEFINE volume_buildup = mean(volume, -5, -1) / mean(volume, -20, -6)

SELECT date_start, event, pre_event_car, volume_buildup, car
FROM events
WHERE HAS_TAG('DIVIDEND')
  AND pre_event_car > 0.02
  AND volume_buildup > 1.5
ORDER BY pre_event_car DESC
```

*События, где цена и объём росли ДО объявления дивидендов — признак инсайда.*

### 3. Санкции, ударившие по энергосектору

```sql
SET model = 'market_model'
SET window = (-5, 20)

-- Максимальная просадка цены за 20 дней после события (%)
DEFINE drawdown = (min(price, 1, 20) / price(0) - 1) * 100

SELECT date_start, event, car, drawdown
FROM events
WHERE HAS_TAG('SANCTIONS')
  AND HAS_TAG('ENERGY')
  AND car < -0.05
ORDER BY drawdown ASC
```

*Самые болезненные санкции для энергосектора по просадке цены.*

### 4. Продвинутый: санкции по конкретным странам с ростом волатильности

```sql
SET window = (-10, 10)

-- Во сколько раз волатильность после события превышает волатильность до
DEFINE vol_spike = std(return, 1, 10) / std(return, -10, -1)

SELECT e.date_start, e.event, t.name AS country, car, vol_spike
FROM events e
JOIN event_tags et ON e.id = et.event_id
JOIN tags t ON et.tag_code = t.code AND t.type = 'country'
WHERE HAS_TAG('SANCTIONS')
  AND t.code IN ('RUS', 'IRN', 'CHN')
  AND vol_spike > 2.0
ORDER BY vol_spike DESC
```

*Санкционные события по России, Ирану, Китаю с сильным ростом волатильности после события.*

### 5. Многофакторный скоринг аномальности

```sql
SET model = 'capm'
SET window = (-10, 10)
SET estimation = 250

DEFINE pre_car = sum(ar, -10, -1)
DEFINE volume_ratio = mean(volume, 1, 10) / mean(volume, -10, -1)
DEFINE vol_ratio = std(return, 1, 10) / std(return, -10, -1)

-- Составной балл: сколько факторов аномальности сработало (0-4)
DEFINE anomaly_score = (
    CASE WHEN abs(car) > 0.05 THEN 1 ELSE 0 END
  + CASE WHEN volume_ratio > 2.0 THEN 1 ELSE 0 END
  + CASE WHEN vol_ratio > 2.0 THEN 1 ELSE 0 END
  + CASE WHEN abs(pre_car) > 0.03 THEN 1 ELSE 0 END
)

SELECT date_start, event, car, volume_ratio, vol_ratio, anomaly_score
FROM events
WHERE HAS_TAG('DIVIDEND')
  AND anomaly_score >= 2
ORDER BY anomaly_score DESC, abs(car) DESC
LIMIT 20
```

*Топ-20 самых аномальных дивидендных событий: сработало минимум 2 из 4 факторов.*

---

## Архитектура исполнения

```
DSL-запрос
    → препроцессор
        1. Парсинг SET → словарь параметров
        2. Парсинг DEFINE → словарь метрик
        3. Раскрытие HAS_TAG → подзапросы EXISTS
    → определение scope (FROM + WHERE по тегам)
    → расчёт метрик в Python (event study для каждого события в scope)
    → временная таблица [event_id, car, volume_ratio, ...]
    → чистый SQL по временной таблице (WHERE по метрикам, ORDER BY, LIMIT)
    → результат
```

Препроцессор преобразует DSL в два артефакта:
1. Список метрик для вычисления (Python/pandas)
2. Чистый SQL-запрос по результирующей таблице
