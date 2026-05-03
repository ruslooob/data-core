# 15 стратегий для бэктеста

Подборка стратегий для проверки движка и поиска лучшей. Все они формулируются
двумя SQL-запросами правила: `trigger_sql` (кого затронуть на тике) и
`action_quantity_sql` (сколько акций купить/продать). Сверху по приоритету —
обычно стопы и фиксации, ниже — входы.

Доступные TA-функции (драфт 5.4): `close_price`, `open_price`, `volume`,
`avg_price`, `volume_ratio`, `sma`, `volume_sma`, `volatility`, `return_n_days`.
Доступные таблицы: `portfolio_state` (cash, equity), `portfolio_positions`
(лоты), `tagged_events` (события + теги), `run_context` (период).

## 0. Baseline

Цель — понять, бьёт ли сложная стратегия простой «купи и держи». Без бенчмарка
любые цифры доходности бессмысленны.

### Кандидаты на baseline

- **B0a — Buy-and-hold LKOH (одна покупка на старте).** Купить максимально
  возможное количество LKOH в первый день, держать до конца окружения.
  Дивиденды начисляются автоматически.
- **B0b — Buy-and-hold IMOEX-индекс.** Это «рынок целиком», академический
  стандарт. Однако сейчас `IMOEX` поступает в систему через
  `MarketDataProvider` как индекс, не как торговый тикер; чтобы покупать его
  как актив, нужно: (1) убедиться, что есть OHLCV-файл `IMOEX_*.txt` в формате
  обычного тикера (он есть); (2) проверить, что `StockDataProvider` его видит
  через `list_tickers()` и отдаёт через `get_candles('IMOEX', ...)`. Если да —
  покупаем как обычный тикер. Если нет — нужно дополнительно добавить его
  в общий список тикеров.

Рекомендую остановиться на **B0a** как первичном бенчмарке. B0b добавим, если
будет интересно сравнивать с «рынком».

```sql
-- B0a: trigger
SELECT 'LKOH' AS ticker
WHERE (SELECT current_date FROM run_context) = (SELECT date_start FROM run_context)

-- B0a: action_quantity
SELECT FLOOR(s.cash / open_price('LKOH', :tick))
FROM portfolio_state s
```

`actionType=buy`, `priority=10`. В первый день тикает trigger, quantity =
весь cash / цена открытия. Дальше — пусто, портфель просто держится и
зарабатывает дивиденды.

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

## Группа 6 — Комбинированные

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
