# data-core

Система анализа влияния событий на котировки акций.

Пользователь вводит событие — система находит похожие исторические события, сопоставляет их с графиком выбранной акции и строит статистику по каждому: как изменилась цена, волатильность и объём торгов в окне вокруг даты события (CAR, vol_ratio, volume_ratio и др.).

## Установка

Рекомендуется использовать conda для управления зависимостями.

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd data-core

# 2. Установить зависимости
conda install -c conda-forge pandas numpy gensim plotly dash matplotlib nltk scikit-learn umap-learn hdbscan
conda install -c conda-forge spacy pymorphy3 ipywidgets notebook openpyxl duckdb

# spaCy модели
python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm

# 3. Установить пакет core в editable-режиме
pip install -e .
```

После `pip install -e .` пакет `core` доступен для импорта из любого места — ноутбуков, тестов, скриптов. При изменении кода в `core/` переустанавливать не нужно.

## Структура проекта

```
data-core/
├── core/                  # Python-пакет — все модули анализа
│   ├── event_impact_analyzer.py    # ядро: CAR, vol_ratio, window-анализ
│   ├── stock_data_provider.py      # загрузка котировок акций
│   ├── cpi_data_provider.py        # инфляционная нормализация (ИПЦ)
│   ├── plot_utils.py               # визуализация (Plotly / Dash)
│   ├── spacy_country_recognition.py
│   ├── air_plane_crash_classification.py
│   └── archive/
│
├── notebooks/             # Jupyter-ноутбуки (пронумерованы)
│
├── data/
│   ├── db/                # events.csv, event_tags.csv, tags.csv
│   ├── events/            # 1_raw, 2_struct, 3_countries
│   └── currencies/        # курсы валют (Excel)
│
├── stocks/                # котировки акций + splits.json
├── stats/                 # ИПЦ (Excel)
├── scripts/               # ETL-скрипты (парсинг, тэгирование)
├── reports/               # результаты анализа
├── tests/
└── assets/
```
