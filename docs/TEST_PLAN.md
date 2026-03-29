# План покрытия тестами

## P0 — критично, ломают результаты

### expected_return_models.py
- MeanAdjustedModel: fit запоминает среднее, predict возвращает константу на все даты
- MarketModel: fit находит α и β, predict возвращает α + β·r_market
- CAPMModel: fit находит β, predict возвращает rf + β·(r_market − rf)
- Все модели: kwargs не вызывают ошибку (лишние аргументы проглатываются)

### stock_data_provider.py
- get_log_returns: возвращает pd.Series с DatetimeIndex, значения — логдоходности
- Корректировка сплитов: цена до сплита делится на ratio

## P1 — важно для надёжности

### dividend_data_provider.py
- load_dividends: возвращает list[DividendEvent], 110 событий, даты парсятся корректно

### market_data_provider.py
- load_risk_free_rate: возвращает pd.Series, значения > 0, индекс — даты
- load_market_index: возвращает pd.Series логдоходностей, индекс — даты

## P2 — интеграционные

### EventStudy.analyze (core/event_study.py)
- Результат не None для валидного события
- CAR — float в разумных пределах (например, |CAR| < 1)
- estimation_std > 0
- n_days соответствует размеру событийного окна
- mean_adjusted работает без market/rf
- market_model работает с market, без rf
- capm работает с market и rf