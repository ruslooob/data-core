import json
import os

import pandas as pd


def load_stock_data(csv_path: str) -> pd.DataFrame:
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


def get_ticker_splits(ticker: str, splits_path: str = "../stocks/splits.json") -> list[dict]:
    """Возвращает список сплитов по тикеру из splits.json."""
    with open(splits_path, "r", encoding="utf-8") as f:
        splits = json.load(f)
    return splits.get(ticker, [])


def load_normalized_stock(ticker: str, csv_path: str, splits_path: str = "../stocks/splits.json") -> pd.DataFrame:
    """Возвращает нормализованные данные котировок акции. Учитывает сплиты и обратные сплиты."""
    df = load_stock_data(csv_path)

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


def get_stock_data(ticker: str, normalized: bool = True) -> pd.DataFrame:
    """
    Возвращает DataFrame с котировками для указанного тикера.
    Определяет нужный файл по совпадению начала имени файла (prefix match).
    """
    ticker = ticker.upper()

    file_path = None
    for filename in os.listdir(STOCKS_FOLDER):
        if filename.startswith(ticker):
            file_path = os.path.join(STOCKS_FOLDER, filename)
            break

    if normalized:
        return load_normalized_stock(ticker, file_path)

    return load_stock_data(file_path)


STOCKS_FOLDER = "../stocks"
