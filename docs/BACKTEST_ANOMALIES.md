# Журнал поиска аномалий

Этот файл — рабочий журнал поиска аномалий через PQL. Цель — найти паттерны, которые потом можно превратить в стратегию (см. [BACKTEST_STRATEGIES.md](BACKTEST_STRATEGIES.md)).

Цикл:
1. Сформулировать гипотезу: «такой-то тип события на таких-то тикерах вызывает такую-то аномальную реакцию».
2. Написать PQL-запрос (через виджет редактора прецедентов или напрямую через `POST /api/precedents/search`).
3. Записать результат в раздел «Гипотезы»: количество найденных событий, распределение метрики, важные кейсы.
4. Сделать вывод: устойчив ли паттерн, и можно ли превратить его в trigger-rule стратегии.

Если паттерн устойчив (повторяется на разных тикерах/периодах, имеет значимый размер эффекта) — переходим в `BACKTEST_STRATEGIES.md` и формулируем стратегию.

---

## Доступные функции и таблицы

**TA/PQL-функции** (PL/Python в Postgres):
- `car(ticker, event_date, model='market_model', window_before=5, window_after=5, estimation=200, outlier_threshold=NULL, max_date=NULL)` — накопленная аномальная доходность.
- `vol_ratio(ticker, event_date, window_before=5, window_after=5, max_date=NULL)` — отношение std доходностей после/до события.
- `volume_ratio(ticker, event_date, window_before=5, window_after=5, max_date=NULL)` — отношение средних объёмов после/до.

Подробности — [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md), модели CAR — [EXPECTED_RETURN_MODELS.md](EXPECTED_RETURN_MODELS.md).

**Persistent-таблицы:**
- `tagged_events(event_id, date_start, date_end, event, tag, tag_name, tag_type)` — события с тегами.
- `tags(code, name, type)` — справочник тегов (`type`: `company`, `topic`, `sector`).
- `events(...)`, `event_tags(...)` — нормализованная схема под VIEW `tagged_events`.
- `stocks`, `stock_candles`, `risk_free_rate`, `dividends` — рыночные данные (для UDF, обычно не дёргаем напрямую).

---

## Антипаттерны

### A1. SELECT-алиас в `WHERE` или `ORDER BY ABS(<алиас>)`

DuckDB допускал `WHERE ABS(my_alias) > 0.05`, в Postgres это **синтаксическая ошибка**: `column "my_alias" does not exist`. `WHERE` исполняется до `SELECT`-списка по стандарту SQL.

**Решение:** подставлять выражение целиком.

```sql
-- ✗ НЕ работает в Postgres
SELECT car('LKOH', date_start) AS car_pre
FROM tagged_events
WHERE ABS(car_pre) > 0.05
ORDER BY ABS(car_pre) DESC

-- ✓ Работает
SELECT car('LKOH', date_start) AS car_pre
FROM tagged_events
WHERE ABS(car('LKOH', date_start)) > 0.05
ORDER BY ABS(car('LKOH', date_start)) DESC
```

UDF кэшируется в SD per-сессии, повтор вызова дёшев.

### A2. Запрос без фильтра `tags.type = 'company'`

Без него VIEW `tagged_events` отдаст события с тегами-топиками (`DIVIDEND_PAYMENT`, `SANCTIONS`, …) как «тикеры». В UDF `car('DIVIDEND_PAYMENT', …)` вернёт NULL — получится тихий пропуск. Всегда добавлять фильтр на `t.type = 'company'`, если нужны именно компании.

---

## Валидные шаблоны

### Многофакторная оценка аномальности

```sql
WITH scored AS (
  SELECT te.date_start, te.event, te.tag AS ticker,
         CASE WHEN ABS(car(te.tag, te.date_start)) > 0.05 THEN 1 ELSE 0 END
       + CASE WHEN volume_ratio(te.tag, te.date_start) > 2.0 THEN 1 ELSE 0 END
       + CASE WHEN vol_ratio(te.tag, te.date_start) > 2.0    THEN 1 ELSE 0 END
         AS score
  FROM tagged_events te
  JOIN tags t ON t.code = te.tag AND t.type = 'company'
)
SELECT date_start, event, ticker, score
FROM scored
WHERE score >= 2
ORDER BY score DESC, date_start DESC
LIMIT 20;
```

### CAR на event-study со ссылкой на topic-тег

```sql
SELECT te.date_start, te.event,
       car(te.tag, te.date_start) AS car
FROM tagged_events te
JOIN tagged_events te2 ON te2.event_id = te.event_id
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE te2.tag = 'DIVIDEND_ANNOUNCEMENT'
ORDER BY ABS(car(te.tag, te.date_start)) DESC
LIMIT 20;
```

### Pre-event utечка (CAR до t=0)

```sql
SELECT te.date_start, te.event, te.tag AS ticker,
       car(te.tag, te.date_start, window_after => -1) AS car_pre
FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE ABS(car(te.tag, te.date_start, window_after => -1)) > 0.03
ORDER BY ABS(car(te.tag, te.date_start, window_after => -1)) DESC
LIMIT 30;
```

---

## Гипотезы и проверки

> Формат: **Гипотеза → PQL-запрос → Результат (количество кейсов, распределение метрики) → Вывод → Связь со стратегией**.

### A1 — Объявления дивидендов LKOH дают значимый положительный CAR

> Гипотеза: после `DIVIDEND_ANNOUNCEMENT` для LKOH цена в окне `[-5, +5]` показывает положительную аномальную доходность — рынок «вознаграждает» за анонс выплаты.

**PQL-запрос (агрегаты):**
```sql
WITH cars AS (
  SELECT car('LKOH', te.date_start) AS car
  FROM tagged_events te
  JOIN tagged_events te2 ON te2.event_id = te.event_id
  WHERE te.tag = 'LKOH' AND te2.tag = 'DIVIDEND_ANNOUNCEMENT'
)
SELECT COUNT(*) FILTER (WHERE car IS NOT NULL) AS n,
       AVG(car), STDDEV(car), MIN(car), MAX(car),
       COUNT(*) FILTER (WHERE car > 0) AS positive
FROM cars;
```

**Результаты:**

| n | Mean CAR | Std | Min | Max | % positive | strong_pos (>3%) | strong_neg (<-3%) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 36 | **−0.05%** | 3.78% | −6.4% | +7.9% | 47% | 9 | 10 |

Top-5 положительных:
- 2019-10-16 (LKOH 192 ₽ за 2019): +7.86%
- 2003-04-16 (19.50 ₽): +5.62%
- 2017-10-25 (85 ₽): +5.51%
- 2015-10-27 (65 ₽): +4.86%
- 2022-10-28 (537 ₽): +4.66%

**Вывод A1:** **отвергнута для LKOH.** Средний CAR практически нулевой (−0.05%), 47% положительных — это шум. Strong positive (9) почти равно strong negative (10). На LKOH-выборке размером 36 событий нет значимой реакции на объявления дивидендов в окне `[-5, +5]`. Возможные причины: эффект уже заложен в цену до объявления (см. A3), или окно слишком короткое.

---

### A2 — Скачок объёма (volume_ratio > 2) предсказывает положительный post-event CAR

> Гипотеза: события со значимым всплеском объёма (volume_ratio > 2) на следующие 5 торговых дней показывают положительный CAR — momentum-сигнал. Большой объём = сильное движение, и это движение продолжается.

**PQL-запрос (агрегаты):**
```sql
WITH spikes AS (
  SELECT car(te.tag, te.date_start, window_before => -1, window_after => 5) AS car_post
  FROM tagged_events te
  JOIN tags t ON t.code = te.tag AND t.type = 'company'
  WHERE volume_ratio(te.tag, te.date_start) > 2.0
)
SELECT COUNT(*) FILTER (WHERE car_post IS NOT NULL) AS n,
       AVG(car_post), STDDEV(car_post), ...
FROM spikes;
```

**Результаты:**

| n | Mean CAR | Std | % positive | strong_pos (>3%) | strong_neg (<-3%) |
|---:|---:|---:|---:|---:|---:|
| 118 | **+1.69%** | 6.70% | **60%** | 43 | 29 |

T-статистика: 1.69 / (6.70/√118) ≈ **2.74 — значимо** (>2.0).

Top-5 максимальных post-event CAR:
- 2017-04-12 GCHE (объявление див.) vol_x=4.23, car_post=+22.7%
- 2023-05-18 LSRG (объявление див.) vol_x=6.19, car_post=+17.4%
- 2023-07-26 TRMK (объявление див.) vol_x=3.23, car_post=+17.4%
- 2022-08-30 GAZP (объявление див.) vol_x=4.30, car_post=+16.7%
- 2022-05-17 MTSS (объявление див.) vol_x=3.45, car_post=+14.5%

**Вывод A2:** **подтвердилась.** Volume-spike в день события — устойчивый сигнал положительного движения в следующие 5 дней. Top-5 показывает что это **в основном дивидендные объявления с пробоем объёма** — то есть объём подтверждает силу позитивной новости.

**Связь со стратегией:** trigger «купить на день volume-spike (любого company-events), держать 5 дней». Это **новая гипотеза для `BACKTEST_STRATEGIES.md` — H16**.

⚠ Caveat: top-5 — это все дивидендные объявления. Может, A2 — просто маска для A4 («дивидендные объявления → +CAR»). Стоит сравнить эффекты после фильтра «без DIVIDEND_ANNOUNCEMENT в te2».

---

### A3 — Pre-event «утечка»: значимый |CAR| до t=0

> Гипотеза: для скольких events движение цены **до** события превышает 3%? Если много — это либо инсайдерская торговля, либо рынок предсказуемо реагирует на ожидаемые события.
>
> Окно: `window_after = -1` означает только до события, без самого дня.

**Результаты:**

| n | Mean abs CAR_pre | leak >3% | leak >5% | leak up >3% | leak down >3% |
|---:|---:|---:|---:|---:|---:|
| 1754 | **3.28%** | **711** (40%) | 339 (19%) | 282 | **429** |

Top-5 максимальных |CAR_pre|:
- 2022-03-30 IRAO (объявление див. 0.24 ₽): −80.67%
- 2025-01-08 TATNP (выплата 17.39 ₽): −44.19%
- 2025-01-08 TATN (выплата 17.39 ₽): −40.43%
- 2019-04-22 NKNCP (выплата 19.94 ₽): −36.14%
- 2008-05-21 PLZL (объявление 0.29 ₽): +31.37%

**Вывод A3:** **подтверждено наполовину.** Pre-event движение действительно широко распространено — 40% событий имеют |CAR| > 3% за 5 дней до. Но **направление преимущественно негативное** (leak_down 429 vs leak_up 282), что противоречит «инсайдерская торговля = positive front-running».

Top-5 — экстремальные случаи (-80%, -44%, -40%) — это шоковые события (санкции 2022 для IRAO, выплата TATN после провала, и т.п.). Их CAR-кейсы загрязнены **самим шоком**, не утечкой инсайда. **Чистый инсайдерский паттерн отдельно не вычленяется** без выкидывания outliers.

**Связь со стратегией:** trigger «sell за 5 дней до события, если |CAR_pre| уже > 3%» — реализуем не получится без знания будущей даты события (lookahead). Это **диагностический паттерн**, не торговый.

---

### A4 — Дивидендные объявления (любая компания) дают значимый положительный CAR

> Гипотеза: расширенная версия A1 на все компании. Если на большой выборке средний CAR положительный — паттерн универсальный, его можно превратить в стратегию.

**Результаты:**

| n | Mean CAR | Std | % positive | strong_pos (>3%) | strong_neg (<-3%) |
|---:|---:|---:|---:|---:|---:|
| **886** | **+0.84%** | 7.15% | 54% | **261** | 203 |

T-статистика: 0.84 / (7.15/√886) ≈ **3.5 — высоко значимо**.

Top-5 максимальных CAR (вся выборка):
- 2019-03-11 NKNCP: +53.66%
- 2021-03-12 TRMK: +40.79%
- 2021-07-30 TRMK: +35.81%
- 2019-03-11 NKNC: +30.78%
- 2021-08-20 RASP: +28.85%

**Вывод A4:** **подтвердилась.** На выборке 886 событий средний CAR после дивидендных объявлений — **+0.84%** при std 7.15%. T-stat ≈ 3.5 — устойчиво значимо. Асимметрия в пользу роста: 261 strong-up vs 203 strong-down.

Top-5 — компании 2-эшелона (NKNCP, TRMK, RASP) с экстремальными +30..+50% — это малоликвидные тикеры с большой волатильностью. Эффект на больших именах (LKOH, GAZP, SBER) меньше, но в среднем — положительный.

**Связь со стратегией:** trigger «купить на день DIVIDEND_ANNOUNCEMENT (любая компания), держать 5–10 дней» — кандидат в **H17 для `BACKTEST_STRATEGIES.md`**. Размер эффекта (+0.84% за 5 дней = ~40% годовых на бумаге, но это для каждой сделки отдельно; в портфеле эффект надо считать через бэктест).

---

## Сводный вывод

Из 4 проверенных гипотез:
- **A1** (дивиденды LKOH only) — отвергнута, выборка слишком мала.
- **A2** (volume spike → +5d CAR) — подтверждена, но возможно дублирует A4.
- **A3** (pre-event утечка) — присутствует, но загрязнена шоковыми событиями; не торгуема.
- **A4** (все дивидендные объявления → +CAR) — подтверждена надёжно, t-stat 3.5.

Два подтверждённых паттерна → две новые гипотезы стратегий: **H16 (volume-spike momentum)** и **H17 (dividend announcement buy)**. Они идут в очередь `BACKTEST_STRATEGIES.md`.

---

## Связь со стратегиями

Найденная аномалия становится trigger-правилом стратегии так:
1. PQL-запрос аномалии возвращает множество `(ticker, event_date)`.
2. В trigger-rule стратегии повторяем то же условие, но как **фильтр на текущем тике** — `WHERE EXISTS (... AND te.date_start = :tick - N)`.
3. Action — buy/sell с заданным размером и priority.
4. Прогоняем на всей истории, смотрим что доходность статегии лучше пассивного бенчмарка.

Это путь от «нашёл паттерн в данных» к «использую его как сигнал». Каждая подтверждённая гипотеза в этом файле — кандидат на новую гипотезу `H<N>` в `BACKTEST_STRATEGIES.md`.

---

## Связанные документы

- [BACKTEST_STRATEGIES.md](BACKTEST_STRATEGIES.md) — журнал стратегий (куда трансформируются подтверждённые аномалии).
- [ANOMALY_DETECTION.md](ANOMALY_DETECTION.md) — концепция «аномалия = результат запроса», три масштаба анализа.
- [SPEC_PRECEDENT_LANGUAGE.md](SPEC_PRECEDENT_LANGUAGE.md) — синтаксис и контракт PQL.
- [TAGS.md](TAGS.md) — система тегов событий.
- [METRICS.md](METRICS.md) — что значат CAR, vol_ratio, volume_ratio.
