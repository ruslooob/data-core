import os
import warnings

import pandas as pd

CURRENCY_FOLDER = '../data/currencies'


def list_avail_currency_pairs() -> list[str]:
    """
    Возвращает список всех валютных пар на основе файлов в папке CURRENCY_FOLDER.
    Например: 'USD_RUB_1day_20000101_20250905.xlsx' -> 'USD/RUB'
    """
    pairs = set()

    for filename in os.listdir(CURRENCY_FOLDER):
        name, _ = os.path.splitext(filename)

        parts = name.split('_')
        base, quote = parts[0].upper(), parts[1].upper()
        pairs.add(f"{base}/{quote}")
        pairs.add(f"{quote}/{base}")

    return sorted(pairs)


def is_currency_pair_available(pair: str) -> bool:
    """
    Проверяет, доступна ли валютная пара (в любом направлении).
    Например: 'USD/RUB' или 'RUB/USD'
    """
    pair = pair.upper()
    available_pairs = list_avail_currency_pairs()

    if pair in available_pairs:
        return True

    base, quote = pair.split('/')
    reversed_pair = f"{quote}/{base}"
    return reversed_pair in available_pairs


def get_currency_data(pair: str) -> pd.DataFrame:
    """Возвращает DataFrame с историей валютной пары (например, 'USD/RUB')"""
    if not is_currency_pair_available(pair):
        raise ValueError(
            f"Валютная пара '{pair}' не найдена. "
            f"Доступные пары: {', '.join(list_avail_currency_pairs())}"
        )
    pair = pair.upper().replace('/', '_')

    file_path = None
    invert = False

    for filename in os.listdir(CURRENCY_FOLDER):
        if filename.startswith(pair):
            file_path = os.path.join(CURRENCY_FOLDER, filename)
            break
    else:
        # если прямой пары нет — пробуем найти обратную
        base, quote = pair.split('_')
        reversed_pair = f"{quote}_{base}"
        for filename in os.listdir(CURRENCY_FOLDER):
            if filename.startswith(reversed_pair):
                file_path = os.path.join(CURRENCY_FOLDER, filename)
                invert = True
                break

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        df = pd.read_excel(file_path)
    df = df[['data', 'curs']]
    df = df.rename(columns={
        'data': 'date',
        'curs': 'value',
    })

    if invert:
        df['value'] = 1 / df['value']

    return df


def get_currency_value_on_date(pair: str, date: str) -> float:
    """
    Возвращает курс валютной пары на указанную дату.
    Если в этот день нет котировки (например, выходной), возвращает курс
    за последнюю доступную дату до неё.
    """
    df = get_currency_data(pair)
    target = pd.to_datetime(date)
    df_before = df[df['date'] <= target]

    if df_before.empty:
        first_date = df['date'].iloc[0].date()
        raise ValueError(
            f"Нет данных для {pair} на {target.date()} и ранее. "
            f"Первая доступная дата: {first_date}"
        )

    return df_before.iloc[0]['value']
