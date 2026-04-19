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

### event_study.py — outlier_threshold
- С фильтрацией estimation_std <= чем без
- outliers_removed > 0 при наличии выбросов
- outliers_removed = 0 при outlier_threshold=None

## P1 — важно для надёжности

### dividend_data_provider.py
- load_dividends: возвращает list[DividendEvent], даты парсятся корректно

### market_data_provider.py
- load_daily_risk_free_rate: возвращает pd.Series, значения > 0, индекс — даты
- load_market_index_log_returns: возвращает pd.Series логдоходностей, индекс — даты

### anomaly_detector.py
- detect_anomalies: возвращает AnomalyResult для валидного события, None для невалидного
- Каждый флаг (significant_car, volume_spike, vol_spike, pre_event_car) срабатывает при превышении порога и не срабатывает ниже
- detect_anomalies_batch: возвращает список отсортированный по anomaly_score desc

### event_study.py — analyze_aggregate
- Возвращает результат при >= 2 событиях, None при 0
- n_events совпадает с количеством успешных анализов
- mean_car имеет длину = размер окна
- p_value в диапазоне [0, 1]

## P2 — интеграционные

### EventStudy.analyze (core/event_study.py)
- Результат не None для валидного события
- CAR — float в разумных пределах (например, |CAR| < 1)
- estimation_std > 0
- n_days соответствует размеру событийного окна
- mean_adjusted работает без market/rf
- market_model работает с market, без rf
- capm работает с market и rf
- Результат None при недостаточных данных (слишком ранняя дата)
