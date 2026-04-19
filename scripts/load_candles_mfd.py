"""
Загрузка дневных котировок с mfd.ru.

Использование:
    # Скачать конкретные тикеры
    python scripts/load_candles_mfd.py GAZPN IRAO MAGN

    # Обновить все существующие тикеры до сегодня
    python scripts/load_candles_mfd.py --update-all

    # Указать интервал дат
    python scripts/load_candles_mfd.py GAZPN --start 2000-01-01 --end 2026-04-19

Маппинг тикер → mfd ID задаётся в TICKER_MAP ниже.
Если тикера нет в маппинге, скрипт выведет ошибку.
"""
import argparse
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks"
REQUEST_DELAY = 1.5  # пауза между запросами

# ── Маппинг тикер → (mfd_id, русское_имя) ──
# mfd_id = значение value из <option> на странице mfd.ru/export
# Добавляй сюда новые тикеры по мере необходимости
TICKER_MAP: dict[str, tuple[int, str]] = {
    # Уже есть в data/stocks
    "AFLT":  (183, "Аэрофлот"),
    "ALRS":  (41369, "АЛРОСА ао"),
    "CHMF":  (1476, "СевСт-ао"),
    "FEES":  (1712, "ФСК ЕЭС ао"),
    "GAZP":  (330, "ГАЗПРОМ ао"),
    "GMKN":  (336, "ГМКНорНик"),
    "LKOH":  (632, "ЛУКОЙЛ"),
    "MGNT":  (832, "Магнит ао"),
    "MOEX":  (51353, "МосБиржа"),
    "MTSS":  (826, "МТС-ао"),
    "NLMK":  (913, "НЛМК ао"),
    "NVTK":  (948, "Новатэк ао"),
    "RTKM":  (1383, "Ростел -ао"),
    "SBER":  (1463, "Сбербанк"),
    "TATN":  (1613, "Татнфт 3ао"),
    "UPRO":  (107301, "Юнипро ао"),
    "VTBR":  (258, "ВТБ ао"),
    # Новые
    "GAZPN": (346, "Газпрнефть"),
    "MAGN":  (716, "ММК"),
    "IRAO":  (17107, "ИнтерРАОао"),
    "PLZL":  (103315, "Полюс"),
    "HYDR":  (1389, "РусГидро"),
    "PHOR":  (37859, "ФосАгро ао"),
    "TRNFP": (1658, "Транснф ап"),
    "CBOM":  (82984, "МКБ ао"),
    "TCSG":  (606237, "ТКСХолд ао"),
    "MTLR":  (9060, "Мечел ао"),
    "LENT":  (311936, "Лента ао"),
    "FLOT":  (246840, "Совкомфлот"),
    "POSI":  (315688, "iПозитив"),
    "AFKS":  (1503, "Система ао"),
    "MVID":  (666, "М.видео"),
    "RASP":  (1359, "Распадская"),
    "NKNC":  (909, "НКНХ ао"),
    "MSNG":  (27734, "МосЭнерго"),
    "OGKB":  (967, "ОГК-2 ао"),
    "TRMK":  (1593, "ТМК ао"),
    "SGZH":  (275963, "Сегежа"),
    "PIKK":  (1019, "ПИК ао"),
    "ROSN":  (1373, "Роснефть"),
    "RUAL":  (246271, "РУСАЛ ао"),
    "SMLT":  (248949, "Самолет ао"),
    "SNGSP": (1543, "Сургнфгз-п"),
    "SVCB":  (582495, "Совкомбанк"),
    "TATNP": (1614, "Татнфт 3ап"),
    "RTKMP": (1384, "Ростел -ап"),
    "LSRG":  (629, "ЛСР ао"),
    "CNGS":  (1542, "Сургнфгз"),
    "CPBE":  (310778, "СПБ Биржа"),
    "AGRO":  (745751, "Русагро"),
    # Дополнительные популярные
    "YDEX":  (659459, "ЯНДЕКС"),
    "OZON":  (828495, "Озон"),
    "HHRU":  (674390, "Хэдхантер"),
    "VKCO":  (552045, 'МКПАО "ВК"'),
    "FIVE":  (731704, "КЦ ИКС 5"),
    "RENI":  (302658, "Ренессанс"),
    "CHKZ":  (1764, "ЧеркизГ-ао"),
    "BSPB":  (190, "БСП ао"),
    "SELG":  (39756, "Селигдар"),
    "SOFL":  (550773, "Софтлайн"),
}


def build_url(mfd_id: int, name: str, ticker: str, start: str, end: str) -> str:
    """Формирует URL для скачивания с mfd.ru."""
    start_fmt = start.replace("-", ".")  # 2000-01-01 → 01.01.2000
    end_fmt = end.replace("-", ".")
    # Переворачиваем: YYYY-MM-DD → DD.MM.YYYY
    start_dmy = f"{start_fmt[8:10]}.{start_fmt[5:7]}.{start_fmt[0:4]}"
    end_dmy = f"{end_fmt[8:10]}.{end_fmt[5:7]}.{end_fmt[0:4]}"
    start_compact = start.replace("-", "")
    end_compact = end.replace("-", "")

    filename = f"{ticker}_{name}_1day_{start_compact}_{end_compact}.txt"
    encoded_filename = quote(filename)

    params = (
        f"TickerGroup=16&Tickers={mfd_id}&Alias=false&Period=7"
        f"&timeframeValue=1&timeframeDatePart=day"
        f"&StartDate={start_dmy}&EndDate={end_dmy}"
        f"&SaveFormat=0&SaveMode=1"
        f"&FileName={encoded_filename}"
        f"&FieldSeparator=%3b&DecimalSeparator=."
        f"&DateFormat=yyyyMMdd&TimeFormat=HHmmss"
        f"&DateFormatCustom=&TimeFormatCustom="
        f"&AddHeader=true&RecordFormat=0&Fill=false"
    )
    return f"https://mfd.ru/export/handler.ashx/{encoded_filename}?{params}"


def download_ticker(ticker: str, start: str, end: str) -> bool:
    """Скачивает котировки одного тикера. Возвращает True при успехе."""
    if ticker not in TICKER_MAP:
        print(f"  [!] {ticker}: нет в TICKER_MAP, пропускаю")
        return False

    mfd_id, name = TICKER_MAP[ticker]
    url = build_url(mfd_id, name, ticker, start, end)

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            print(f"  [!] {ticker}: 404 Not Found")
            return False
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] {ticker}: ошибка загрузки: {e}")
        return False

    content = resp.content
    if len(content) < 100:
        print(f"  [!] {ticker}: пустой ответ ({len(content)} байт)")
        return False

    # Определяем имя файла
    start_compact = start.replace("-", "")
    end_compact = end.replace("-", "")
    filename = f"{ticker}_{name}_1day_{start_compact}_{end_compact}.txt"
    filepath = DATA_DIR / filename

    # Удаляем старые файлы этого тикера (могут быть с другими датами в имени)
    for old in DATA_DIR.glob(f"{ticker}_*_1day_*.txt"):
        if old != filepath:
            old.unlink()
            print(f"  Удалён старый файл: {old.name}")

    filepath.write_bytes(content)
    lines = content.decode("utf-8", errors="replace").strip().split("\n")
    print(f"  {ticker}: {len(lines) - 1} торговых дней → {filepath.name}")
    return True


def find_existing_tickers() -> list[str]:
    """Находит тикеры, для которых уже есть файлы в data/stocks."""
    tickers = set()
    for f in DATA_DIR.glob("*_1day_*.txt"):
        ticker = f.name.split("_")[0]
        if ticker in TICKER_MAP:
            tickers.add(ticker)
    return sorted(tickers)


def main():
    parser = argparse.ArgumentParser(description="Загрузка котировок с mfd.ru")
    parser.add_argument("tickers", nargs="*", help="Тикеры для загрузки")
    parser.add_argument("--update-all", action="store_true", help="Обновить все существующие тикеры")
    parser.add_argument("--start", default="2000-01-01", help="Дата начала (YYYY-MM-DD)")
    parser.add_argument("--end", default=date.today().isoformat(), help="Дата окончания (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.update_all:
        tickers = find_existing_tickers()
        print(f"Обновление {len(tickers)} существующих тикеров до {args.end}")
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        parser.print_help()
        return

    success = 0
    for ticker in tickers:
        if download_ticker(ticker, args.start, args.end):
            success += 1
        time.sleep(REQUEST_DELAY)

    print(f"\nГотово: {success}/{len(tickers)} тикеров загружено")


if __name__ == "__main__":
    main()
