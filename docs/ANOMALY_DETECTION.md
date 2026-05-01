# Поиск аномалий

## Идея

Аномалия — это **результат запроса**, а не отдельная сущность. Пользователь формулирует, что считается «аномальным», в виде SQL-условия на языке поиска прецедентов (PQL) и прогоняет запрос по событиям. Один и тот же набор событий может быть аномальным по одному критерию и нормальным по другому — критерий выбирает аналитик.

Поиск аномалий не имеет отдельного виджета: это один из сценариев использования редактора PQL. Подробности языка — в [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md), система тегов событий — в [TAGS.md](TAGS.md).

---

## Три масштаба анализа аномалий

Документ делит сценарии по охвату данных. Каждый масштаб — это просто разные формы PQL-запроса; никакой архитектурной разницы нет.

### Масштаб 1 — одно событие, один тикер

Аномалии, видимые на графике одной акции вокруг известного события.

| Аномалия | Идея | Как выразить в PQL |
|---|---|---|
| Значимый CAR | Накопленная аномальная доходность вышла за нормальный диапазон | `car(ticker, event_date) > 0.05` |
| Всплеск объёма | Объём после события резко вырос относительно фона | `volume_ratio(ticker, event_date) > 1.5` |
| Рост волатильности | После события цена стала «нервничать» | `vol_ratio(ticker, event_date) > 2.0` |
| Утечка до объявления | CAR двигается ДО даты события | `ABS(car(ticker, event_date, window_after => -1)) > 0.03` |

Пример запроса:

```sql
SELECT te.date_start, te.event,
       car(te.tag, te.date_start) AS car
FROM tagged_events te
JOIN tagged_events te2 ON te2.event_id = te.event_id
WHERE te.tag = 'LKOH'
  AND te2.tag = 'DIVIDEND_ANNOUNCEMENT'
  AND ABS(car(te.tag, te.date_start)) > 0.03
ORDER BY ABS(car) DESC;
```

### Масштаб 2 — сравнение с рынком и сектором

Аномалии, которые видны только при сопоставлении одной акции с другими.

| Аномалия | Идея | Как выразить в PQL |
|---|---|---|
| Специфичная для компании | CAR акции значим, CAR индекса — нет | `car('LKOH', d) > 0.05 AND ABS(car('IMOEX', d)) < 0.01` (если индекс доступен как тикер) |
| Секторальный эффект | Несколько компаний одного сектора показали реакцию одновременно | `JOIN tagged_events` по тегу-сектору + агрегация `COUNT(...) HAVING ≥ K` |
| Кросс-актив | Реакция одной акции коррелирует с реакцией другой | `car('GAZP', d) < -0.05 AND car('NVTK', d) < -0.05` |

Пример (одновременная реакция компаний нефтяного сектора):

```sql
SELECT te.date_start, te.event,
       COUNT(*) AS n_oil_companies_reacted
FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
JOIN tagged_events te_sector
     ON te_sector.event_id = te.event_id AND te_sector.tag = 'OIL'
WHERE car(te.tag, te.date_start) < -0.03
GROUP BY te.event_id, te.date_start, te.event
HAVING COUNT(*) >= 3
ORDER BY n_oil_companies_reacted DESC;
```

### Масштаб 3 — поиск неизвестных событий

Инвертированная задача: сначала находим аномальное движение цены, потом ищем, какое событие за ним стоит.

| Аномалия | Идея | Как выразить в PQL |
|---|---|---|
| Необъяснённое движение | Доходность далеко за пределами нормы, событие в БД на эту дату не зафиксировано | требуется отдельный TA-запрос по ряду цен — пост-MVP, через расширение функций |
| Кластер аномалий | Несколько тикеров одновременно показали аномалию на одном дне | агрегация по дате + `HAVING COUNT(...) ≥ K` |
| Предвестник события | Аномалия за 1–5 дней до даты события в БД | `car(ticker, event_date, window_after => -1) > 0.03` |

Масштаб 3 в текущей версии PQL покрыт частично: для поиска аномалий на конкретных датах есть утечка через `car(..., window_after => -1)`. Полноценный поиск аномалий «без привязки к событию» требует функций сканирования временного ряда — расширение, которое появится после внедрения пользовательских функций (`CREATE FUNCTION ... LANGUAGE SQL`, см. [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md), раздел «Что не входит в MVP»).

---

## Многофакторная оценка

PQL позволяет комбинировать несколько критериев в один балл «аномальности» через `CASE WHEN` и `HAVING`:

```sql
WITH scored AS (
  SELECT te.date_start, te.event, te.tag AS ticker,
         CASE WHEN ABS(car(te.tag, te.date_start)) > 0.05 THEN 1 ELSE 0 END
       + CASE WHEN volume_ratio(te.tag, te.date_start) > 2.0  THEN 1 ELSE 0 END
       + CASE WHEN vol_ratio(te.tag, te.date_start) > 2.0     THEN 1 ELSE 0 END
       + CASE WHEN ABS(car(te.tag, te.date_start, window_after => -1)) > 0.03 THEN 1 ELSE 0 END
         AS anomaly_score
  FROM tagged_events te
  JOIN tags t ON t.code = te.tag AND t.type = 'company'
  WHERE EXISTS (
    SELECT 1 FROM tagged_events te2
    WHERE te2.event_id = te.event_id AND te2.tag = 'DIVIDEND_ANNOUNCEMENT'
  )
)
SELECT * FROM scored
WHERE anomaly_score >= 2
ORDER BY anomaly_score DESC, date_start DESC
LIMIT 20;
```

Сработало два или больше из четырёх критериев — событие попадает в выдачу.

---

## Системные рецепты

В таблице `precedent_queries` хранится несколько системных шаблонов с префиксом `★` (см. план в [drafts/ANOMALY_TO_PQL_PLAN.md](drafts/ANOMALY_TO_PQL_PLAN.md)). Аналитик открывает редактор PQL, нажимает «Загрузить» и видит готовые рецепты под типичные сценарии — всплеск объёма, рост волатильности, возможный инсайд, многофакторная оценка. Дальше — правит под свою задачу.

---

## Связанные документы

- [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md) — синтаксис и видимая схема PQL.
- [SPEC_DATA_PROVIDERS.md](SPEC_DATA_PROVIDERS.md) — контракт TA-функций (`car`, `volume_ratio`, `vol_ratio`).
- [METRICS.md](METRICS.md) — интерпретация CAR и связанных метрик.
- [EXPECTED_RETURN_MODELS.md](EXPECTED_RETURN_MODELS.md) — модели ожидаемой доходности, используемые в `car()`.
