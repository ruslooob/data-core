# 15 стратегий для бэктеста

Подборка стратегий для проверки движка и поиска лучшей. Все они формулируются
двумя SQL-запросами правила: `trigger_sql` (кого затронуть на тике) и
`action_quantity_sql` (сколько акций купить/продать). Сверху по приоритету —
обычно стопы и фиксации, ниже — входы.

Доступные TA-функции (драфт 5.4): `close_price`, `open_price`, `volume`,
`avg_price`, `volume_ratio`, `sma`, `volume_sma`, `volatility`, `return_n_days`.
Доступные таблицы: `portfolio_state` (cash, equity), `portfolio_positions`
(лоты), `tagged_events` (события + теги), `run_context` (период).

## 0. Baseline (с чем сравниваемся)

Стратегию имеет смысл оценивать не «дала ли она прибыль», а «бьёт ли она
рынок». Для этого нужен явный benchmark.

### B0 — Market: IMOEX buy-and-hold (price return)

Это **главный baseline**. На первом торговом дне окружения покупаем условные
«акции» IMOEX на весь cash и держим до конца. `StockDataProvider` отдаёт
файл `IMOEX_Индекс_МосБиржи_*.txt` как обычный тикер с OHLCV-структурой,
поэтому никакой специальной поддержки не нужно.

```sql
-- B0: trigger (срабатывает только на первом тике прогона)
SELECT 'IMOEX' AS ticker
WHERE (SELECT index FROM run_context) = 0

-- B0: action_quantity
SELECT FLOOR(s.cash / open_price('IMOEX', :tick))
FROM portfolio_state s
```

`actionType=buy`, `priority=10`. Триггер сработает один раз и заберёт почти
весь капитал в IMOEX; дальше equity = `qty × close_price('IMOEX', :tick)`
автоматически.

> **Ограничение.** Это price-return версия рынка: дивиденды компонентов
> индекса в неё не входят. Total-return бенчмарк — это MCFTR (Total Return
> Index Мосбиржи), которого в проекте пока нет. Когда добавим, B0 заменится
> на «MCFTR buy-and-hold», и сравнение станет честнее (особенно на длинных
> горизонтах: дивидендная составляющая российского рынка — несколько
> процентов в год).

### B1 — Buy LKOH each day (DCA на одной фишке)

Уже создана и используется. Покупает 1 акцию LKOH в каждый торговый день
независимо от условий. На полной истории 2002–2025 даёт **+1802%** при
капитале 1М ₽. Хороший кандидат «нижнего бара» для стратегий по LKOH в
частности — стратегия по этому же тикеру обязана быть не хуже простого DCA.

### B2 — Депозит / RUONIA (безрисковая доходность)

Депозит реализован как **псевдо-тикер `DEPOSIT_RUONIA`**. Это OHLCV-файл
в `data/stocks/`, сгенерированный скриптом `scripts/generate_deposit_ticker.py`
из ряда RUONIA: цена начинается с 1000 ₽ и каждый торговый день растёт на
дневную долю безрисковой ставки. Никаких отдельных механик в движке не
требуется — депозит ведёт себя как обычный актив.

```sql
-- B2: trigger
SELECT 'DEPOSIT_RUONIA' AS ticker
WHERE (SELECT index FROM run_context) = 0

-- B2: action_quantity
SELECT FLOOR(s.cash / open_price('DEPOSIT_RUONIA', :tick))
FROM portfolio_state s
```

Свойства:
- Минимальный лот = 1000 ₽ (стартовая цена «единицы депозита»). Это
  моделирует требование «минимальный взнос».
- Нет волатильности (Sharpe в коротких прогонах получается фантастически
  большой — это артефакт, не показатель).
- Нет дивидендов.
- Можно совмещать с любыми другими активами в одной стратегии — как
  cash-эквивалент в Permanent Portfolio (P4).

> **Замечание о точности.** В `RUONIA_*.xlsx` ряд начинается с 2010 года.
> До 2010 в нашем `MarketDataProvider` ставка отсутствует, и генератор
> подставляет 0 — поэтому на длинном окружении 2002–2025 итоговая
> доходность депозита занижена (~5% годовых вместо реалистичных 7–8%).
> При желании заменить нули на MIBOR-ряд до 2010-го — отдельная задача.

Перегенерация файла (если RUONIA пополнился новыми данными):
`python scripts/generate_deposit_ticker.py`. Скрипт идемпотентен —
старый файл удаляется, новый записывается с актуальным диапазоном дат.

---

## Группа 1 — Momentum (тренд продолжается)

### 1. Volume spike entry

Гипотеза: всплеск объёма сигнализирует приток покупателей.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND volume(t.code, :tick - 1) > 1.5 * volume_sma(t.code, :tick, 20)

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

### 2. Long momentum (пробой вверх)

Купить тикеры, выросшие за 20 дней более чем на 5%.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND return_n_days(t.code, :tick, 20) > 0.05

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

### 3. Crossover SMA200

Классика: `close > SMA200` — рынок в восходящем тренде.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND close_price(t.code, :tick - 1) > sma(t.code, :tick, 200)

-- action_quantity
SELECT FLOOR(s.cash * 0.03 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

### 4. Dual SMA (золотой крест)

Купить, когда SMA50 пересекает SMA200 снизу вверх (упрощённо: SMA50 > SMA200).

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND sma(t.code, :tick, 50) > sma(t.code, :tick, 200)

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

---

## Группа 2 — Mean reversion (откат к среднему)

### 5. Buy the dip (5-day)

Купить тикер, упавший за 5 дней более чем на 7%.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND return_n_days(t.code, :tick, 5) < -0.07

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

### 6. Below SMA50 (контртренд)

Купить тикер, цена которого на 10% ниже своей 50-дневной скользящей.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND close_price(t.code, :tick - 1) < sma(t.code, :tick, 50) * 0.90

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

---

## Группа 3 — Risk-targeted sizing (объём, обратный волатильности)

### 7. Low-volatility filter

Покупаем только спокойные тикеры (волатильность < 1.5% дневной std).

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND volatility(t.code, :tick, 20) < 0.015

-- action_quantity
SELECT FLOOR(s.cash * 0.05 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

### 8. Vol-targeted sizing

Размер позиции обратно пропорционален волатильности — все позиции имеют
одинаковый риск-вклад.

```sql
-- trigger
SELECT t.code AS ticker FROM tags t
WHERE t.type = 'company'
  AND volatility(t.code, :tick, 20) IS NOT NULL
  AND return_n_days(t.code, :tick, 20) > 0

-- action_quantity (доля 0.5% риска от equity на тикер)
SELECT FLOOR(
    (s.equity * 0.005)
    / (close_price(:ticker, :tick - 1) * volatility(:ticker, :tick, 20))
)
FROM portfolio_state s
```

---

## Группа 4 — Stop-loss / take-profit (выходы)

Эти правила обычно ставятся в стратегию вместе с какой-то «входной» из выше.

### 9. Hard stop-loss 5%

Sell весь лот, если цена упала на 5% от средней цены входа.

```sql
-- trigger
SELECT pp.ticker FROM portfolio_positions pp
WHERE close_price(pp.ticker, :tick - 1) < avg_price(pp.ticker) * 0.95
GROUP BY pp.ticker

-- action_quantity
SELECT SUM(quantity) FROM portfolio_positions WHERE ticker = :ticker
```

`actionType=sell`, `priority=300` (высокий — стопы исполняются первыми).

### 10. Trailing take-profit 10% (продаём половину)

Sell половину, если цена выросла на 10% от средней цены входа.

```sql
-- trigger
SELECT pp.ticker FROM portfolio_positions pp
WHERE close_price(pp.ticker, :tick - 1) > avg_price(pp.ticker) * 1.10
GROUP BY pp.ticker

-- action_quantity
SELECT FLOOR(SUM(quantity) / 2)
FROM portfolio_positions WHERE ticker = :ticker
```

`actionType=sell`, `priority=200`.

### 11. Time-based exit (продать через 90 дней)

Закрыть позицию, если держим её больше 90 торговых дней.

```sql
-- trigger
SELECT pp.ticker FROM portfolio_positions pp
WHERE pp.buy_date <= :tick - 90
GROUP BY pp.ticker

-- action_quantity
SELECT SUM(quantity) FROM portfolio_positions WHERE ticker = :ticker
```

`actionType=sell`, `priority=150`.

---

## Группа 5 — Event-driven (события)

### 12. Dividend capture

Купить 100 акций тикера за 1 день до объявления дивидендов, продать через
неделю. Грубая «дивидендная стрижка».

```sql
-- trigger BUY (вход)
SELECT te.tag AS ticker FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE EXISTS (
  SELECT 1 FROM tagged_events te2
  WHERE te2.event_id = te.event_id
    AND te2.tag = 'DIVIDEND_ANNOUNCEMENT'
    AND te2.date_start = :tick
)

-- action_quantity
SELECT 100
```

`actionType=buy`, `priority=50`.

Сэлл-выход через time-based exit (см. правило 11) или явный — через 7 дней.

### 13. Anti-sanctions rebound

Купить тикер через 5 дней после события `SANCTIONS` (ставка на отскок после
эмоциональной просадки).

```sql
-- trigger
SELECT te.tag AS ticker FROM tagged_events te
JOIN tags t ON t.code = te.tag AND t.type = 'company'
WHERE EXISTS (
  SELECT 1 FROM tagged_events te2
  WHERE te2.event_id = te.event_id
    AND te2.tag = 'SANCTIONS'
    AND te2.date_start = :tick - 5
)

-- action_quantity
SELECT FLOOR(s.cash * 0.10 / close_price(:ticker, :tick - 1))
FROM portfolio_state s
```

`actionType=buy`, `priority=50`. Удерживается через time-based exit или
take-profit.

---

## Группа 6 — Портфельные (multi-asset)

Это диверсифицированные стратегии, которые держат корзину активов с
заданными целевыми весами и периодически ребалансируют. Без них
«дисциплина улучшения стратегий» неполная — именно эти портфели традиционно
используют как baseline'ы для оценки риск-скорректированной доходности.

> **Внимание.** Нескольким стратегиям ниже **не хватает данных** или
> **механик движка** — детали в секции «Что нужно добавить, чтобы
> запустить портфельные стратегии» в конце документа. Сначала смотри
> туда, потом возвращайся к конкретной стратегии.

### P1 — Депозит (безрисковая доходность, RUONIA)

См. `B2` выше. Реализовано как псевдо-тикер `DEPOSIT_RUONIA`.

### P2 — 60/40 (Stocks/Bonds), классика

60% IMOEX + 40% облигации (RGBI или ETF SBGB), ребалансировка ежеквартально.

**Чего не хватает:**
- **Облигационный benchmark.** Нет файла индекса RGBI (Гособлигационный
  индекс Мосбиржи) и нет ETF SBGB. Нужно загрузить хотя бы один из них
  в `data/stocks/` в формате обычного OHLCV-CSV (как остальные тикеры).
- **Механика ребалансировки.** Нужны два правила:
  1. Триггер «доля тикера > таргет + допустимое отклонение» с `sell` до
     таргета.
  2. Триггер «доля тикера < таргет − допустимое отклонение» с `buy` до
     таргета.
  Для расчёта текущей доли нужно либо новая TA-функция
  `position_value(ticker)` (стоимость позиции по close), либо в SQL
  подсчитывать `SUM(quantity) * close_price(ticker, :tick - 1) / equity`.
  Второй вариант рабочий, но `quantity_sql` становится длинным и
  трудночитаемым.
- **Триггер «раз в квартал».** В DuckDB реализуется через
  `EXTRACT(MONTH FROM :tick) IN (1,4,7,10) AND EXTRACT(DAY FROM :tick) <= 7
  AND :tick = первый_торговый_день_окна`. Это упирается в отсутствие
  TA-функции «является ли :tick первым торговым днём периода». Можно
  добавить, либо обходиться приближением.

### P3 — 50/50 (равные веса акций и облигаций)

То же, что P2, но 50/50. Формула те же, веса другие.

### P4 — Permanent Portfolio (Гарри Браун)

25% акций + 25% долгосрочных облигаций + 25% золото + 25% краткосрочные
обязательства / cash. Ежегодная ребалансировка. Идея: каждый из четырёх
активов выигрывает в одном из четырёх макро-режимов (рост / рецессия /
инфляция / стагфляция).

**Чего не хватает:**
- **Золото в RUB.** В `data/stocks/` нет ни XAU/USD, ни XAU/RUB, ни ETF
  на золото (TGLD, SBGD, FXGD). Нужно загрузить хотя бы один.
- Всё, что у P2: облигации + ребалансировка + квартальный/годовой
  триггер.

### P5 — Risk-parity (равный вклад в риск)

Веса между классами активов выбираются обратно пропорционально их
волатильности — каждый класс вносит одинаковый вклад в общий риск
портфеля. На стабильно низковолатильных классах (облигации) вес выше,
на акциях — ниже. Считается одним из «честных» multi-asset подходов.

**Чего не хватает:**
- Все требования P4.
- Дополнительно: нужна функция «волатильность класса активов» — у нас
  есть `volatility(ticker, date, w)` для одного тикера, но придётся
  «классы» представить тикером-прокси (IMOEX = акции, RGBI = облигации,
  TGLD = золото).

---

## Группа 7 — Комбинированные

### 14. Volume momentum + protective stop

Стратегия из двух правил:
- Правило A: вход — Volume spike entry (см. №1), `priority=50`.
- Правило B: стоп — Hard stop-loss 5% (см. №9), `priority=300`.
- Правило C: тейк-профит — Trailing 10% (см. №10), `priority=200`.

### 15. Equal-weight blue chips rebalanced quarterly

Раз в квартал выравнивать веса между LKOH, GAZP, SBER (или любым набором
заранее выбранных тикеров) — тикер, чья доля в портфеле упала ниже 30%,
докупается до 33%.

Реализация требует более сложного `quantity_sql`, может стать стартом для
расширения функциональности (например, добавить отдельную TA-функцию
«доля тикера в equity»). В рамках текущего MVP это — кандидат на
post-MVP, помечается как «вызов».

---

## Что нужно добавить, чтобы запустить портфельные стратегии

Запуск Группы 6 (multi-asset) упирается в три класса нехваток. Перечислены
по приоритету.

### A. Данные

| Класс активов | Что есть | Что нужно загрузить | Источник |
|---|---|---|---|
| Акции в РФ | IMOEX-индекс, ~60 тикеров отдельных эмитентов | — | уже есть |
| Облигации | — | **RGBI** (Гособлигационный индекс Мосбиржи, OHLCV-дневки) ИЛИ ETF на ОФЗ (например `SBGB`) | moex.com → исторические данные → индексы / акции |
| Золото | — | **XAU/RUB** или ETF на золото (`TGLD`, `SBGD`, `FXGD`) | moex.com → исторические данные → ETF |
| Безрисковая ставка | RUONIA через `MarketDataProvider` | — (но требует движковую механику, см. ниже) | уже есть |

Ожидаемый формат файлов — такой же, как у обычного тикера в
`data/stocks/`: `<TICKER>;<PER>;<DATE>;<TIME>;<O>;<H>;<L>;<C>;<V>;<OPENINT>`,
кодировка UTF-8, разделитель `;`. После выгрузки они автоматически становятся
доступны через `StockDataProvider.list_tickers()` и могут участвовать в
триггерах как обычные тикеры.

### B. Механика «положить на депозит» (реализовано через псевдо-тикер)

Решение: депозит как обычный «купи-и-держи» актив через сгенерированный
псевдо-тикер `DEPOSIT_RUONIA` (см. B2). Никаких изменений в движке не
потребовалось — стратегия может покупать и продавать депозит как любую
акцию.

Стратегии, которые хотят держать часть капитала «в безриске» (например
P4 Permanent Portfolio), просто включают `DEPOSIT_RUONIA` как один из
тикеров портфеля.

### C. Механика ребалансировки

Это самое сложное. Минимум:

1. **Доступ к доле актива в equity.** Без новой TA-функции это можно
   выразить SQL'ем, но получится длинно. Чище добавить
   `position_share(ticker)` → доля стоимости открытых лотов тикера в
   equity.
2. **Триггер «раз в период»** (квартал / месяц / год). Можно через
   `EXTRACT(...)`-конструкции, но это негибко. Лучше — TA-функция
   `is_first_trading_day_of_period(period)` где `period ∈ {'month',
   'quarter', 'year'}`.
3. **Quantity «купить до доли X»** и **«продать до доли X»**. Это
   уже выражается через `(target_value − current_value) / open_price`,
   но требует обоих helper'ов выше.

Без этих helper'ов портфельные стратегии можно реализовать «грубо» —
например, ребалансироваться календарно через `EXTRACT(MONTH/DAY FROM :tick)`
и считать доли в SQL. Получится, но читать и поддерживать — больно.

---

## Что нужно проверить / добавить, прежде чем запускать сравнение

1. **IMOEX как покупаемый тикер.** Файл `IMOEX_Индекс_МосБиржи_1day_*.txt`
   присутствует в `data/stocks/`, формат тот же. Нужен smoke-тест:
   `provider.get_candles('IMOEX')` должен работать. Если работает — `B0b`
   доступна. Если нет — `MarketDataProvider` уже использует IMOEX как индекс,
   возможен конфликт; либо добавить псевдо-тикер `IMOEX-ETF`, либо взять
   ETF на индекс (например, `MOEX` — но это акция Московской биржи, не сам
   индекс).

2. **Тег `SANCTIONS` в БД.** События со санкционным тегом нужны для №13.
   Сейчас в `tagged_events` они есть (см. историю работы с
   `19_sanctions_on_stocks_effect.ipynb`), но стоит сверить, что тег
   называется именно `SANCTIONS` и привязан к тикерам компаний.

3. **Семантика `:tick - N` для DATE.** В DuckDB вычитание из DATE целого
   числа даёт `DATE`, отступая на N **календарных** дней. Триггер №11 («время
   удержания > 90 дней») использует календарные дни, не торговые. Это
   допустимое упрощение; если нужны именно торговые — потребуется отдельная
   функция `tick_index() - buy_tick_index()`, чего сейчас нет.

4. **Метрики сравнения.** Win rate и Profit factor сейчас игнорируют
   dividend-строки в `pnl_realized`. Для buy-and-hold это даёт `—`. Перед
   массовым прогоном стоит решить: либо включать dividend в gain (для
   buy-and-hold metrics станут содержательными), либо считать отдельную
   метрику «доходность от дивидендов».

5. **Размеры позиций как % от cash.** Большинство стратегий используют
   `FLOOR(s.cash * 0.05 / close_price(...))`. На раннем этапе прогона cash
   большой, и при множестве сигналов в один тик первый кандидат заберёт
   много — последующие могут не получить ничего. Это поведение `FIFO`-
   исполнения и корректно по драфту 3.2 «исполнение с частичным
   заполнением». Но для честного сравнения стратегий лучше использовать
   `s.equity * 0.05` (доля от полного капитала, не от свободного), чтобы
   ранние входы не блокировали поздние.

---

## Рекомендованная последовательность прогонов

1. Прогнать `B0a` (Buy-and-hold LKOH) на длинном окружении 2002-01-08…
   2025-09-05. Это даст твёрдый baseline.
2. Прогнать каждую из стратегий 1–15 на том же окружении.
3. Открыть **Архив** в `BacktestEditor`, отсортировать по `Σ доходность`
   и `Sharpe`. Сравнить:
   - Какие стратегии бьют B0a по Σ доходности.
   - Какие — по Sharpe (риск-скорректировано).
   - У кого минимальный max drawdown.
4. Для интересных стратегий открывать карточку, смотреть equity-кривую и
   журнал сделок (особенно дивиденды vs торговые pnl).

После этой прогонки можно строить мнение о том, какая стратегия годится для
дальнейшего исследования.
