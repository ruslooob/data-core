# Обзор системы data-core

## Что это такое

Рабочее место финансового аналитика: набор инструментов для исследования влияния событий на котировки акций.

Основные инструменты:
- **Событийный анализ (event study)** — точечная оценка влияния одного события на цену актива
- **Поиск аномалий (anomaly detector)** — автоматическое обнаружение аномального поведения по набору событий и тикеров
- **Редактор прецедентных запросов (PQL editor)** — SQL-эдитор для поиска событий по тегам и метрикам с подсветкой синтаксиса и сохранением запросов
- **Проверка устойчивости (robustness check)** — проверка, сохраняется ли эффект при вариациях параметров *(запланирован)*
- **Бэктест** — прогон торговых стратегий на исторических данных *(запланирован)*

---

## Архитектура

```
Сырые данные (Wikipedia, открытые источники)
        ↓
   ETL-конвейер (скрипты тэгирования, парсеры)
        ↓
  Структурированная БД (CSV-файлы)
        ↓
  Аналитические модули (backend/core/)
        ↓
  FastAPI-сервер (backend/main.py)
        ↓
  React-фронтенд (виджеты на полотне)
```

Параллельно остаются Jupyter-ноутбуки для research-задач.

---

## Система тегов событий

См. [TAGS.md](TAGS.md) — иерархия типов, схема данных, примеры разметки.

---

## Структура базы данных

БД реализована через CSV-файлы. Данные человекочитаемы, легко редактируются, не требуют сервера.

### Таблицы (`data/db/`)

| Файл | Содержимое |
|------|-----------|
| `events.csv` | Все события: `id`, `date_start`, `date_end`, `event` |
| `tags.csv` | Справочник тегов: `code`, `name`, `type` |
| `event_tags.csv` | Связь событий и тегов: `event_id`, `tag_code` |
| `precedent_queries.csv` | Сохранённые прецедентные запросы PQL: `id`, `name`, `source`, `created_at` |

Дивидендные события импортируются из `data/stocks/dividends_all.csv` в `events.csv` через `scripts/import_dividends_to_db.py` (идемпотентен): на каждую запись создаются два события — объявление и выплата — с тегами тикера компании (type=company) и топиком (`DIVIDEND_ANNOUNCEMENT` / `DIVIDEND_PAYMENT`).

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
data/db/events.csv      — финальная БД событий
        ↓
data/db/event_tags.csv  — тэгирование
```

Скрипты тэгирования: `spacy_country_recognition` (страны), `air_plane_crash_classification` (авиакатастрофы).

Требования: идемпотентность (повторный запуск безопасен), воспроизводимость.

---

## Аналитические модули (`backend/core/`)

| Модуль | Назначение |
|--------|-----------|
| `event_study.py` | Событийный анализ: AR, CAR, агрегированный анализ, фильтрация выбросов |
| `anomaly_detector.py` | Поиск аномалий: significant CAR, volume spike, vol spike, pre-event movement |
| `precedent_engine.py` | Движок PQL: in-memory DuckDB, видимая схема (events/tags/event_tags/tagged_events/precedent_queries) и UDF `car()` |
| `expected_return_models.py` | Модели ожидаемой доходности: mean adjusted, market model, CAPM |
| `stock_data_provider.py` | Загрузка котировок, корректировка сплитов |
| `market_data_provider.py` | Индекс рынка (IMOEX), безрисковая ставка (RUONIA) |
| `dividend_data_provider.py` | Загрузка дивидендных событий |
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
- [SPEC_DATA_PROVIDERS.md](SPEC_DATA_PROVIDERS.md) — поставщики рыночных данных, отсутствие подглядывания в будущее
- [ROBUSTNESS_CHECK.md](ROBUSTNESS_CHECK.md) — проверка устойчивости
- [SPEC_FRONTEND.md](SPEC_FRONTEND.md) — спецификация фронтенда
- [SPEC_EVENT_FILTER.md](SPEC_EVENT_FILTER.md) — виджет фильтра событий
