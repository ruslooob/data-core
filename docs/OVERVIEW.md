# Обзор системы data-core

## Что это такое

Рабочее место финансового аналитика: набор инструментов для исследования влияния событий на котировки акций.

Основные инструменты:
- **Событийный анализ (event study)** — точечная оценка влияния одного события на цену актива
- **Редактор прецедентных запросов (PQL editor)** — SQL-эдитор для поиска событий по тегам и метрикам с подсветкой синтаксиса и сохранением запросов; поиск аномалий — один из сценариев его использования (см. [ANOMALY_DETECTION.md](ANOMALY_DETECTION.md))
- **Бэктест** — прогон торговых стратегий на исторических данных, журнал прогонов с метриками (см. [SPEC_BACKTEST.md](SPEC_BACKTEST.md))
- **Исследования (Research)** — организационный слой над бэктестом: группировка стратегий, правил, окружений и прогонов под одну тему с автогенерируемым отчётом (см. [SPEC_RESEARCH.md](SPEC_RESEARCH.md))
- **Проверка устойчивости (robustness check)** — проверка, сохраняется ли эффект при вариациях параметров *(запланирован)*

---

## Архитектура

```
Сырые данные (Wikipedia, открытые источники)
        ↓
   ETL-конвейер (скрипты тэгирования, парсеры)
        ↓
  Структурированная БД (Postgres, схема через Liquibase)
        ↓
  Аналитические модули (backend/core/)
        ↓
  FastAPI-сервер (backend/main.py + backend/routers/*)
        ↓
  React-фронтенд (виджеты на полотне)
```

Параллельно остаются Jupyter-ноутбуки для research-задач.

---

## Система тегов событий

См. [TAGS.md](TAGS.md) — иерархия типов, схема данных, примеры разметки.

---

## Структура базы данных

БД реализована в **Postgres** (docker-compose), схема и PL/Python-функции управляются Liquibase (см. [SPEC_DATABASE.md](SPEC_DATABASE.md)). Просматривать содержимое можно через `psql`, DBeaver или вкладку Database в PyCharm.

### Основные таблицы

| Таблица | Содержимое |
|------|-----------|
| `events` | Все события: `id` (PK), `announce_date`, `payload_date`, `event`, `event_type` |
| `tags` | Справочник тегов: `code` (PK), `name`, `type` |
| `event_tags` | Связь событий и тегов: `event_id` (FK), `tag_code` (FK), составной PK |
| `precedent_queries` | Сохранённые прецедентные запросы PQL: `id` (PK), `name` (UNIQUE), `source`, `created_at` |
| `stock_candles` | OHLCV-котировки тикеров (включая синтетический `SAVINGS_MIACR`) |
| `research`, `strategies`, `rules`, `strategy_rules`, `environments`, `backtest_results`, `trade_journal` | Бэктест и исследования |

Дивидендные события импортируются вместе с остальными референсными данными скриптом `scripts/load_data_to_postgres.py` (идемпотентен): на каждую запись создаются два события — объявление и выплата — с тегами тикера компании (type=company) и топиком (`DIVIDEND_ANNOUNCEMENT` / `DIVIDEND_PAYMENT`).

При первом старте `precedent_engine` засевает в `precedent_queries` несколько системных рецептов с префиксом `★` — типовые шаблоны анализа.

### Котировки (`data/stocks/`)

Файлы по тикерам в формате OHLCV. Плюс `splits.json` для корректировки на сплиты, `dividends_all.csv` для дивидендных событий.

---

## ETL-конвейер

Конвейер превращает неструктурированные данные в размеченную базу событий.

```
data/events/1_raw/      — сырые данные (Wikipedia и др.)
        ↓
data/events/2_struct/   — структурированные CSV
        ↓
Postgres (events)       — финальная БД событий (загрузка через scripts/load_data_to_postgres.py)
        ↓
Postgres (event_tags)   — тэгирование
```

Скрипты тэгирования: `spacy_country_recognition` (страны), `air_plane_crash_classification` (авиакатастрофы).

Требования: идемпотентность (повторный запуск безопасен), воспроизводимость.

---

## Аналитические модули (`backend/core/`)

| Модуль | Назначение |
|--------|-----------|
| `event_study.py` | Событийный анализ: AR, CAR, агрегированный анализ, фильтрация выбросов |
| `precedent_engine.py` | Поставщики данных для UDF `car` / `vol_ratio` / `volume_ratio` (сами UDF — PL/Python в Postgres, см. `db/changelog/changes/002-udfs.sql`) |
| `expected_return_models.py` | Модели ожидаемой доходности: mean adjusted, market model, CAPM |
| `stock_data_provider.py` | Класс `StockDataProvider` — котировки, дневные доходности, объёмы; `vol_ratio` и `volume_ratio` |
| `market_data_provider.py` | Класс `MarketDataProvider` — индекс рынка (IMOEX), безрисковая ставка (дневная доходность SAVINGS_MIACR) |
| `dividend_data_provider.py` | Класс `DividendDataProvider` — дивидендные события из CSV (легаси-источник для эндпоинта `/api/events`) |
| `cpi_data_provider.py` | Инфляционная нормализация (ИПЦ) |
| `plot_utils.py` | Визуализация для ноутбуков (Plotly / Dash) |
| `spacy_country_recognition.py` | NLP: распознавание стран в тексте |
| `air_plane_crash_classification.py` | NLP: классификация авиакатастроф |

---

## Связанные документы

- [GLOSSARY.md](GLOSSARY.md) — глоссарий терминов
- [TAGS.md](TAGS.md) — система тегов событий
- [METRICS.md](METRICS.md) — интерпретация метрик
- [EXPECTED_RETURN_MODELS.md](EXPECTED_RETURN_MODELS.md) — модели ожидаемой доходности
- [ANOMALY_DETECTION.md](ANOMALY_DETECTION.md) — поиск аномалий
- [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md) — язык поиска прецедентов (PQL)
- [SPEC_BACKTEST.md](SPEC_BACKTEST.md) — спецификация бэктеста
- [SPEC_RESEARCH.md](SPEC_RESEARCH.md) — спецификация исследований
- [SPEC_DATABASE.md](SPEC_DATABASE.md) — Liquibase-миграции и сценарий «с нуля»
- [SPEC_DATA_PROVIDERS.md](SPEC_DATA_PROVIDERS.md) — поставщики рыночных данных, отсутствие подглядывания в будущее
- [ROBUSTNESS_CHECK.md](ROBUSTNESS_CHECK.md) — проверка устойчивости
- [SPEC_FRONTEND.md](SPEC_FRONTEND.md) — спецификация фронтенда
- [SPEC_EVENT_FILTER.md](SPEC_EVENT_FILTER.md) — виджет фильтра событий
