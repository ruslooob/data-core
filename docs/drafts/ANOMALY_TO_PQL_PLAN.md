# Детектор аномалий → PQL: упразднение спецдетектора и расширение языка

> Черновик плана для следующей сессии. Источник правды — этот файл; копия лежит в `~/.claude/plans/playful-waddling-bubble.md` для plan-режима.

## Контекст

**Решение пользователя:** старый `anomaly_detector` (4 жёстких чека: significant_car, volume_spike, vol_spike, pre_event_car) и его виджет `AnomalyWidget` **удаляются**. Причина — критерий «аномальности» зависит от стратегии (momentum vs mean-reversion и т.п.) и должен быть в руках аналитика, а не захардкожен в коде. Стандартный SQL уже умеет «стакать» факторы (`AND` в `WHERE`, `CASE WHEN + HAVING score>=k`); PQL-редактор уже есть.

**Чтобы PQL покрыл сценарии старого детектора, нужны:**
- три новых UDF: `vol_ratio`, `volume_ratio`, `pre_event_car`
- удаление кода и виджета старого детектора
- стартовые рецепты-шаблоны в `precedent_queries`, чтобы аналитик не упирался в пустое поле
- фиксация в спеке: пользовательские функции (`CREATE FUNCTION`) — пост-MVP, основа будущего расширения

**Свои функции в MVP не делаем** (мощная фича, нужна когда полный flow аналитика будет реализован — после бэктеста).

---

## Этап A1 — Новые UDF в precedent_engine

Добавляются по аналогии с `car()`: Python-функция + макрос с named args + `deterministic=True`.

| UDF | Параметры | Возвращает |
|---|---|---|
| `vol_ratio(ticker, event_date, window_before:=5, window_after:=5)` | окно до/после | `std(returns) после / std(returns) до` (DOUBLE, NULL если данных мало) |
| `volume_ratio(ticker, event_date, window_before:=5, window_after:=5)` | окно до/после | `mean(volume) после / mean(volume) до` (DOUBLE, NULL если данных мало) |
| `pre_event_car(ticker, event_date, window_before:=5, model:='market_model', estimation:=200, outlier_threshold:=NULL)` | окно до t=0 + параметры модели | CAR на интервале `[-window_before, -1]` (DOUBLE, NULL если данных мало) |

Реализация — обёртки над `EventStudy.analyze` и `stock_data_provider.get_candles` (для volume).

**Тесты `tests/precedent_engine_udf_test.py`** — numerical equivalence: SQL-вызов = прямой расчёт на тех же данных, плюс NULL на неизвестном тикере и слишком ранней дате.

Коммит: `feat(precedent): UDF vol_ratio, volume_ratio, pre_event_car`

---

## Этап A2 — Удаление старого детектора

**Backend:**
- `backend/core/anomaly_detector.py` → УДАЛИТЬ
- `backend/main.py`: убрать `POST /api/anomalies`, `POST /api/anomalies/scan-all`, импорты anomaly_detector, DTO `AnomalyRequest/Result/Flag/ScanAll*`
- `backend/tests/`: удалить anomaly-тесты (если есть)

**Frontend:**
- `frontend/src/widgets/AnomalyWidget.tsx` → УДАЛИТЬ
- `frontend/src/widgets/WidgetCanvas.tsx`: убрать тип `'anomaly'`, заголовок, кнопку меню, ветку JSX
- `frontend/src/api/types.ts`: убрать `AnomalyRequest`, `AnomalyResult`, `AnomalyFlag`, `AnomalyScanAllRequest`
- `frontend/src/api/client.ts`: убрать `findAnomalies`, `scanAllAnomalies`

Прогон `pytest` + `tsc --noEmit`.

Коммит: `refactor(precedent): упразднить старый AnomalyDetector в пользу PQL`

---

## Этап A3 — Стартовые рецепты в precedent_queries

При старте `precedent_engine` выполнять идемпотентный `INSERT` нескольких системных рецептов в `precedent_queries` (если записи с такими именами нет). Они сразу видны в дропдауне «Загрузить».

Минимальный набор (3–5 рецептов, имена начинаются с `★` чтобы отличать от пользовательских):

1. **★ Объём: всплеск > 1.5×** — `WHERE volume_ratio(...) > 1.5 ORDER BY volume_ratio DESC`
2. **★ Волатильность: рост > 2×** — `WHERE vol_ratio(...) > 2.0 ORDER BY vol_ratio DESC`
3. **★ Возможный инсайд (CAR до t=0)** — `WHERE ABS(pre_event_car(...)) > 0.03 ORDER BY ABS(pre_event_car) DESC`
4. **★ Дивиденды LKOH: реакция цены** — JOIN c `DIVIDEND_ANNOUNCEMENT` + CAR
5. **★ Multi-factor anomaly score** — `CASE WHEN ... + CASE WHEN ... HAVING score >= 2`

Хранятся в `data/db/precedent_queries.csv`, привязаны к стабильным `id` (UUID5 от имени), чтобы повторный старт не плодил дубли. Системные имена защищены от перезаписи пользователем (POST не даст создать ещё один рецепт с тем же именем).

Коммит: `feat(precedent): стартовые рецепты для типовых сценариев`

---

## Этап A4 — Документация

`docs/SPEC_PRECEDENT_LANGUAGE.md`:
- Видимая схема: добавить функции `vol_ratio`, `volume_ratio`, `pre_event_car` с сигнатурами
- Раздел «Что не входит в MVP» → добавить пункт **«Пользовательские функции (`CREATE FUNCTION ... LANGUAGE SQL`)» как основу будущего расширения**: позволит аналитику задавать свои композиции метрик и порогов и сохранять их между сессиями (требуется единый flow аналитика, начиная с бэктеста)
- Раздел «Стартовые рецепты» — описание системных шаблонов

`docs/OVERVIEW.md`: убрать «Поиск аномалий (anomaly detector)» из списка инструментов — теперь это сценарий PQL-редактора. Убрать `anomaly_detector.py` из таблицы модулей.

`docs/GLOSSARY.md`: статьи `AnomalyRule`, `Anomaly`, `Scan` пометить как устаревшие (или просто переформулировать как примеры использования PQL — обсудим в начале реализации, не блокирует).

`todo.md`: пополнить будущими расширениями (CREATE FUNCTION, бэктест, дополнительные UDF — drawdown, post_event_drift и т.д.).

Коммит: `docs(precedent): расширения языка и упразднение спецдетектора`

---

## Критические файлы

**Создавать/расширять:**
- `backend/core/precedent_engine.py` — три новых UDF + три CREATE MACRO
- `backend/tests/precedent_engine_udf_test.py` — новые тесты
- `data/db/precedent_queries.csv` — стартовые рецепты при старте

**Удалять:**
- `backend/core/anomaly_detector.py`
- `frontend/src/widgets/AnomalyWidget.tsx`

**Править:**
- `backend/main.py` — убрать anomaly-эндпоинты и DTO
- `frontend/src/widgets/WidgetCanvas.tsx` — убрать регистрацию виджета
- `frontend/src/api/types.ts`, `frontend/src/api/client.ts` — убрать anomaly-типы и методы
- `docs/SPEC_PRECEDENT_LANGUAGE.md`, `docs/OVERVIEW.md`, `docs/GLOSSARY.md`, `todo.md`

**Использовать без изменений:**
- `backend/core/event_study.py` (для `pre_event_car`)
- `backend/core/stock_data_provider.py` (для `volume_ratio` через `get_candles`)

---

## Верификация

- `pytest tests/ -v` — все тесты зелёные
- `npx tsc --noEmit` — без ошибок типов
- Запустить бэк + фронт; в виджете «Precedent editor» нажать «лупу» — увидеть 5 системных рецептов; загрузить «Объём: всплеск» — выполнить — увидеть таблицу
- В меню «+ Добавить виджет» больше нет пункта «Anomaly detector»
