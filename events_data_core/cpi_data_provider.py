from enum import Enum

import pandas as pd


class IpcType(Enum):
    """Возможные страницы Excel-файла с индексами потребительских цен (ИПЦ или CPI)."""
    GOODS_AND_SERVICES = 1  # Потребительские цены на товары и услуги
    FOOD = 2  # Потребительские цены на продовольственные товары
    NONFOOD = 3  # Потребительские цены на непродовольственные товары
    SERVICES = 4  # Потребительские цены на услуги


def load_ipc_data(ipc_type: IpcType = IpcType.GOODS_AND_SERVICES) -> pd.DataFrame:
    """
    Загружает и обрабатывает указанный лист Excel-файла с данными ИПЦ.
    Табличный формат удобен для восприятия и обработки.

    Исходный файл Росстата содержит данные с 1991 года.
    iloc[1:13] — берём только строки месяцев (12 штук), пропуская заголовок.
    drop(columns[1:10]) — отбрасываем столбцы 1991–1999, оставляем с 2000 года.
    """
    df = pd.read_excel('../stats/ipc_mes_08-2025.xlsx', sheet_name=ipc_type.value, skiprows=3)
    df = df.iloc[1:13]           # строки месяцев (январь–декабрь)
    df = df.drop(df.columns[1:10], axis=1)  # убираем годы 1991–1999
    df.columns.values[0] = 'месяц'
    return df


def load_normalized_ipc_data(
        ipc_type: IpcType = IpcType.GOODS_AND_SERVICES,
        base_year: str = '2000-01-01'
) -> pd.DataFrame:
    """
    Загружает CPI, рассчитывает накопленный индекс и реальную покупательную
    способность рубля относительно базового месяца.

    Возвращает DataFrame с колонками: date, cpi, cumulative_cpi, real_ruble.
    real_ruble = 1.0 в базовом месяце, убывает с ростом инфляции.
    """
    df = load_melted_ipc_data(ipc_type)
    base_date = pd.Timestamp(base_year)

    df['cumulative_cpi'] = (df['cpi'] / 100).cumprod()

    base_value = df.loc[df['date'] == base_date, 'cumulative_cpi'].values[0]
    df['real_ruble'] = base_value / df['cumulative_cpi']

    return df[['date', 'cpi', 'cumulative_cpi', 'real_ruble']]


def load_melted_ipc_data(ipc_type: IpcType = IpcType.GOODS_AND_SERVICES) -> pd.DataFrame:
    """
    Возвращает преобразованный DataFrame с колонками 'date' и 'cpi'.
    Сплющенный формат, вместо табличного, удобнее для построения графиков.
    """
    df = load_ipc_data(ipc_type)

    # --- "Расплавляем" таблицу ---
    df_melted = df.melt(id_vars='месяц', var_name='год', value_name='cpi')
    df_melted = df_melted.dropna(subset=['cpi'])

    month_map = {
        'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
        'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
        'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
    }
    df_melted['month_num'] = df_melted['месяц'].map(month_map)
    df_melted['год'] = df_melted['год'].astype(int)

    df_melted['date'] = pd.to_datetime(
        df_melted['год'].astype(str) + '-' + df_melted['month_num'].astype(str) + '-01'
    )

    # --- Выбираем только нужные столбцы ---
    df_melted = df_melted[['date', 'cpi']].reset_index(drop=True)
    return df_melted
