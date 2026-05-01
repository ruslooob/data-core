# Детектор аномалий → PQL: упразднение спецдетектора и расширение языка

> Черновик плана для следующей сессии. Источник правды — этот файл; копия лежит в `~/.claude/plans/playful-waddling-bubble.md` для plan-режима.

## Контекст

**Решение пользователя:** старый `anomaly_detector` (четыре жёстких проверки: significant_car, volume_spike, vol_spike, pre_event_car) и его виджет `AnomalyWidget` **удаляются**. Причина — критерий «аномальности» зависит от стратегии (инерционная стратегия vs возврат к среднему и т.п.) и должен быть в руках аналитика, а не жёстко прописан в коде. Стандартный SQL уже умеет комбинировать факторы (`AND` в `WHERE`, `CASE WHEN + HAVING score>=k`); редактор PQL уже есть.

**Чтобы PQL покрыл сценарии старого детектора, нужны:**
- две новых UDF: `vol_ratio`, `volume_ratio`
- расширение `car()`: отрицательные/нулевые значения окон (для pre-event-only сценария)
- удаление кода и виджета старого детектора
- стартовые рецепты-шаблоны в `precedent_queries`
- фиксация в спеке: `CREATE FUNCTION` — пост-MVP

**Пользовательские функции в MVP не включаем** — мощная возможность, нужна когда полный процесс работы аналитика будет реализован, после бэктеста.

---

## Этап A1 — Новые UDF в precedent_engine + расширение `car()`

Две новых UDF добавляются как **методы класса `StockDataProvider`** (см. `docs/SPEC_DATA_PROVIDERS.md`). Редактор PQL регистрирует их в DuckDB через bound-method дефолтного экземпляра поставщика, аналогично `car()`. Каждый метод реализуется через `self.get_candles(ticker, ...)`.

| UDF | Параметры | Возвращает |
|---|---|---|
| `vol_ratio(ticker, event_date, window_before:=5, window_after:=5)` | окно до/после | `std(returns) после / std(returns) до` (DOUBLE, NULL если данных мало) |
| `volume_ratio(ticker, event_date, window_before:=5, window_after:=5)` | окно до/после | `mean(volume) после / mean(volume) до` (DOUBLE, NULL если данных мало) |

**Расширение `car()`**: `window_before` и `window_after` могут быть любыми целыми при условии непустого интервала (`window_after ≥ -window_before`). Сценарий «только до события» пишется как `car(t, d, window_after => -1)`. Затрагивает `EventStudy.analyze` — проверить, что отрицательные значения окон проходят без ошибок.

**Тесты `tests/precedent_engine_udf_test.py`**: численное совпадение (вызов через SQL даёт тот же результат, что прямой расчёт), NULL на неизвестном тикере и слишком ранней дате, отдельный случай на `car()` с `window_after = -1`.

Коммит: `feat(precedent): UDF vol_ratio, volume_ratio + расширение car() на отрицательные окна`

---

## Этап A2 — Удаление старого детектора

**Бэкенд:** 
- `backend/core/anomaly_detector.py` → УДАЛИТЬ
- `backend/main.py`: убрать `POST /api/anomalies`, `POST /api/anomalies/scan-all`, импорты anomaly_detector, DTO `AnomalyRequest/Result/Flag/ScanAll*`
- `backend/tests/`: удалить тесты по аномалиям (если есть)

**Фронтенд:**
- `frontend/src/widgets/AnomalyWidget.tsx` → УДАЛИТЬ
- `frontend/src/widgets/WidgetCanvas.tsx`: убрать тип `'anomaly'`, заголовок, кнопку меню, ветку JSX
- `frontend/src/api/types.ts`: убрать `AnomalyRequest`, `AnomalyResult`, `AnomalyFlag`, `AnomalyScanAllRequest`
- `frontend/src/api/client.ts`: убрать `findAnomalies`, `scanAllAnomalies`

Прогон `pytest` + `tsc --noEmit`.

Коммит: `refactor(precedent): упразднить старый AnomalyDetector в пользу PQL`

---

## Этап A3 — Стартовые рецепты в precedent_queries

При старте `precedent_engine` выполнять идемпотентный `INSERT` нескольких системных рецептов в таблицу `precedent_queries` БД `data/db/data-core.duckdb`. Идемпотентность через `INSERT INTO ... SELECT ... WHERE NOT EXISTS (SELECT 1 FROM precedent_queries WHERE name = ?)` либо через стабильные `id` (UUID5 от имени) и `INSERT OR IGNORE`.

Минимальный набор (3–5 рецептов, имена начинаются с `★` чтобы отличать от пользовательских):

1. **★ Объём: всплеск > 1.5×** — `WHERE volume_ratio(...) > 1.5 ORDER BY volume_ratio DESC`
2. **★ Волатильность: рост > 2×** — `WHERE vol_ratio(...) > 2.0 ORDER BY vol_ratio DESC`
3. **★ Возможный инсайд (CAR до t=0)** — `WHERE ABS(car(..., window_after => -1)) > 0.03 ORDER BY ABS(car(..., window_after => -1)) DESC`
4. **★ Дивиденды LKOH: реакция цены** — JOIN c `DIVIDEND_ANNOUNCEMENT` + CAR
5. **★ Многофакторная оценка аномальности** — `CASE WHEN ... + CASE WHEN ... HAVING score >= 2`

Системные имена (с префиксом `★`) защищены от перезаписи пользователем: `POST /api/precedents/queries` отклоняет создание рецепта с таким именем (409).

Коммит: `feat(precedent): стартовые рецепты для типовых сценариев`

---

## Этап A4 — Документация

`docs/SPEC_PRECEDENT_LANGUAGE.md`:
- Видимая схема: добавить функции `vol_ratio`, `volume_ratio` с сигнатурами; сослаться на `SPEC_DATA_PROVIDERS.md` как источник правды о контракте поставщика и семантику `max_date`
- Раздел про `car()`: уточнить, что `window_before` / `window_after` могут быть любыми целыми при непустом интервале, привести пример «только до события» (`window_after => -1`)
- Раздел «Что не входит в MVP» → добавить пункт **«Пользовательские функции (`CREATE FUNCTION ... LANGUAGE SQL`)» как основу будущего расширения**: позволит аналитику задавать свои композиции метрик и порогов и сохранять их между сессиями (требует единого процесса работы аналитика, начиная с бэктеста)
- Раздел «Стартовые рецепты» — описание системных шаблонов

`docs/OVERVIEW.md`: убрать «Поиск аномалий (anomaly detector)» из списка инструментов — теперь это сценарий PQL-редактора. Убрать `anomaly_detector.py` из таблицы модулей.

`docs/GLOSSARY.md`: статьи `AnomalyRule`, `Anomaly`, `Scan` пометить как устаревшие (или просто переформулировать как примеры использования PQL — обсудим в начале реализации, не блокирует).

`todo.md`: пополнить будущими расширениями (CREATE FUNCTION, бэктест, дополнительные UDF — drawdown, post_event_drift и т.д.).

Коммит: `docs(precedent): расширения языка и упразднение спецдетектора`

---

## Критические файлы

**Создавать/расширять:**
- `backend/core/stock_data_provider.py` — методы `vol_ratio` и `volume_ratio` в классе `StockDataProvider`
- `backend/core/precedent_engine.py` — регистрация двух новых UDF через bound-method поставщика + две `CREATE MACRO`; обновлённая регистрация `car()` с расширенным контрактом окон; идемпотентная вставка системных рецептов в `precedent_queries` при старте
- `backend/core/event_study.py` — поддержка отрицательных значений `window_before` / `window_after` в `analyze`
- `backend/tests/precedent_engine_udf_test.py` — новые тесты + кейс `car()` с `window_after = -1`

**Удалять:**
- `backend/core/anomaly_detector.py`
- `frontend/src/widgets/AnomalyWidget.tsx`

**Править:**
- `backend/main.py` — убрать эндпоинты и DTO по аномалиям
- `frontend/src/widgets/WidgetCanvas.tsx` — убрать регистрацию виджета
- `frontend/src/api/types.ts`, `frontend/src/api/client.ts` — убрать типы и методы по аномалиям
- `docs/SPEC_PRECEDENT_LANGUAGE.md`, `docs/OVERVIEW.md`, `docs/GLOSSARY.md`, `todo.md`

---

## Верификация

- `pytest tests/ -v` — все тесты зелёные
- `npx tsc --noEmit` — без ошибок типов
- Запустить бэкенд и фронтенд; в виджете «Редактор PQL» нажать «лупу» — увидеть пять системных рецептов; загрузить «Объём: всплеск» — выполнить — увидеть таблицу
- В меню «+ Добавить виджет» больше нет пункта «Поиск аномалий»
