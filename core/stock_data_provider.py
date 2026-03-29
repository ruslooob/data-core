import json
import os

import pandas as pd

STOCKS_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'data', 'stocks')


def list_avail_tickers() -> list[str]:
    """Возвращает список доступных тикеров на основе файлов в папке STOCKS_FOLDER."""
    tickers = []
    for filename in os.listdir(STOCKS_FOLDER):
        name, _ = os.path.splitext(filename)
        ticker = name.split('_')[0].upper()
        tickers.append(ticker)
    return sorted(tickers)


def _load_stock_data(csv_path: str) -> pd.DataFrame:
    """
    Загружает данные котировок из CSV в формате:
    <TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>
    Идентификатор инструмента;Период;Дата;Время;Цена открытия;Макс. цена;Цена закрытия;Объем торгов;Открытый интерес (для фьючерсов)
    """
    dtypes = {
        "TICKER": "string",
        "PER": "string",
        "OPEN": "float64",
        "HIGH": "float64",
        "LOW": "float64",
        "CLOSE": "float64",
        "VOL": "float64",
        "OPENINT": "float64"
    }
    df = pd.read_csv(csv_path, sep=";", header=0, dtype=dtypes, encoding="utf-8")
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r"[<>]", "", regex=True)
        .str.upper()
    )

    df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    df["TIME"] = pd.to_datetime(df["TIME"].astype(str).str.zfill(6), format="%H%M%S").dt.time

    return df[['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOL']]


_SPLITS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'stocks', 'splits.json')


def get_ticker_splits(ticker: str, splits_path: str = _SPLITS_PATH) -> list[dict]:
    """Возвращает список сплитов по тикеру из splits.json."""
    with open(splits_path, "r", encoding="utf-8") as f:
        splits = json.load(f)
    return splits.get(ticker, [])


def _load_normalized_stock(ticker: str, csv_path: str, splits_path: str = _SPLITS_PATH) -> pd.DataFrame:
    """Возвращает нормализованные данные котировок акции. Учитывает сплиты и обратные сплиты."""
    df = _load_stock_data(csv_path)

    splits = get_ticker_splits(ticker, splits_path)

    df["ADJ_FACTOR"] = 1.0

    if splits:
        events = sorted(splits, key=lambda e: e["split_date"])
        for event in events:
            split_date = pd.to_datetime(event["split_date"])
            ratio = event["ratio"]
            df.loc[df["DATE"] < split_date, "ADJ_FACTOR"] *= ratio

    for col in ["OPEN", "HIGH", "LOW", "CLOSE"]:
        df[col] = df[col] / df["ADJ_FACTOR"]
    df["VOL"] = df["VOL"] * df["ADJ_FACTOR"]

    return df.drop('ADJ_FACTOR', axis=1)


def _find_stock_file(ticker: str) -> str:
    """Возвращает путь к файлу котировок по тикеру или бросает ValueError."""
    for filename in os.listdir(STOCKS_FOLDER):
        if filename.startswith(ticker):
            return os.path.join(STOCKS_FOLDER, filename)
    raise ValueError(
        f"Тикер '{ticker}' не найден. "
        f"Доступные тикеры: {', '.join(list_avail_tickers())}"
    )


def get_stock_data(
        ticker: str,
        normalized: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
) -> pd.DataFrame:
    """
    Возвращает DataFrame с котировками для указанного тикера.
    Определяет нужный файл по совпадению начала имени файла (prefix match).

    Параметры:
        ticker:     тикер акции (например, 'LKOH')
        normalized: учитывать сплиты и обратные сплиты
        start_date: фильтр с даты включительно (например, '2020-01-01')
        end_date:   фильтр по дату включительно (например, '2022-12-31')
    """
    ticker = ticker.upper()
    file_path = _find_stock_file(ticker)

    df = _load_normalized_stock(ticker, file_path) if normalized else _load_stock_data(file_path)

    if start_date is not None:
        df = df[df['DATE'] >= pd.Timestamp(start_date)]
    if end_date is not None:
        df = df[df['DATE'] <= pd.Timestamp(end_date)]

    return df.reset_index(drop=True)


def get_log_returns(
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
) -> 'pd.Series':
    """
    Возвращает дневные логарифмические доходности для тикера.

    Учитывает сплиты. Возвращает pd.Series с DatetimeIndex.
    """
    import numpy as np

    df = get_stock_data(ticker, normalized=True, start_date=start_date, end_date=end_date)
    prices = df.set_index('DATE')['CLOSE']
    log_ret = np.log(prices / prices.shift(1)).dropna()
    log_ret.index.name = 'date'
    return log_ret


def get_ticker_info(
        ticker: str,
        normalized: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
) -> dict:
    """
    Возвращает метаинформацию о тикере.

    Параметры:
        ticker:     тикер акции
        start_date: начало периода (опционально)
        end_date:   конец периода (опционально)

    Возвращает словарь с ключами:
        ticker:        тикер акции
        date_from:     первая дата в данных (с учётом фильтра)
        date_to:       последняя дата в данных (с учётом фильтра)
        trading_days:  количество торговых дней (с учётом фильтра)
        has_splits:    есть ли сплиты в splits.json
        splits:        список сплитов с датами и коэффициентами
    """
    ticker = ticker.upper()
    file_path = _find_stock_file(ticker)
    df = _load_normalized_stock(ticker, file_path) if normalized else _load_stock_data(file_path)
    splits = get_ticker_splits(ticker)

    if start_date is not None:
        df = df[df['DATE'] >= pd.Timestamp(start_date)]
    if end_date is not None:
        df = df[df['DATE'] <= pd.Timestamp(end_date)]

    return {
        "ticker": ticker,
        "date_from": df['DATE'].min().date(),
        "date_to": df['DATE'].max().date(),
        "trading_days": len(df),
        "has_splits": len(splits) > 0,
        "splits": splits,
    }
