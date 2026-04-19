"""
Парсер дивидендов с dohod.ru.
Загружает историю дивидендных выплат и сохраняет в data/stocks/dividends_all.csv.

Использование:
    python scripts/load_dividends_dohod.py
"""
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.dohod.ru/ik/analytics/dividend"
DIVIDENDS_PATH = Path(__file__).resolve().parent.parent / "data" / "stocks" / "dividends_all.csv"
REQUEST_DELAY = 1.0  # пауза между запросами, чтобы не нагружать сервер


def fetch_dividends(ticker: str) -> pd.DataFrame:
    """Загружает дивиденды одного тикера с dohod.ru."""
    url = f"{BASE_URL}/{ticker.lower()}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    # Ищем таблицу с 4 колонками (дата объявления, дата закрытия, год, дивиденд)
    target = None
    for t in tables:
        headers = [th.get_text(strip=True) for th in t.find_all("th")]
        if len(headers) == 4 and any("объявл" in h.lower() or "дата" in h.lower() for h in headers):
            target = t
            break

    if target is None:
        print(f"  [!] {ticker}: таблица дивидендов не найдена")
        return pd.DataFrame()

    rows_data = []
    for row in target.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) != 4:
            continue

        announcement_raw, payment_raw, year_raw, dividend_raw = cells

        # Пропускаем прогнозные строки и строки без даты объявления
        if announcement_raw.lower() == "n/a":
            continue
        if "прогноз" in payment_raw.lower() or "прогноз" in announcement_raw.lower():
            continue

        # Парсим дату объявления
        announcement_date = _parse_date(announcement_raw)
        if announcement_date is None:
            continue

        # Парсим дату выплаты (закрытия реестра)
        payment_date = _parse_date(payment_raw)

        # Парсим год
        try:
            year = int(year_raw)
        except ValueError:
            continue

        # Парсим дивиденд
        dividend_str = dividend_raw.replace(",", ".").replace("\xa0", "")
        try:
            dividend = float(dividend_str)
        except ValueError:
            continue

        rows_data.append({
            "ticker": ticker.upper(),
            "announcement_date": announcement_date,
            "payment_date": payment_date,
            "dividend_per_share": dividend,
            "year": year,
        })

    df = pd.DataFrame(rows_data)
    print(f"  {ticker}: {len(df)} дивидендных выплат")
    return df


def _parse_date(s: str) -> str | None:
    """Парсит дату в формате DD.MM.YYYY, игнорируя лишний текст."""
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})", s)
    return m.group(1) if m else None


def load_existing() -> pd.DataFrame:
    """Загружает существующий dividends_all.csv."""
    if not DIVIDENDS_PATH.exists():
        return pd.DataFrame(columns=["ticker", "announcement_date", "payment_date", "dividend_per_share", "year"])
    return pd.read_csv(DIVIDENDS_PATH)


def compare_with_existing(new_df: pd.DataFrame, existing_df: pd.DataFrame, ticker: str) -> dict:
    """Сравнивает новые данные с существующими для одного тикера."""
    ex = existing_df[existing_df["ticker"] == ticker]
    result = {
        "ticker": ticker,
        "existing_count": len(ex),
        "new_count": len(new_df[new_df["ticker"] == ticker]),
        "matched": 0,
        "only_in_existing": 0,
        "only_in_new": 0,
    }

    if ex.empty:
        result["only_in_new"] = result["new_count"]
        return result

    ex_dates = set(ex["announcement_date"].astype(str))
    new_dates = set(new_df[new_df["ticker"] == ticker]["announcement_date"].astype(str))

    result["matched"] = len(ex_dates & new_dates)
    result["only_in_existing"] = len(ex_dates - new_dates)
    result["only_in_new"] = len(new_dates - ex_dates)
    return result


def main():
    # ── Дополнительные тикеры для загрузки (добавлять сюда) ──
    EXTRA_TICKERS: list[str] = [
        # "GAZP", "ROSN", "NVTK", "VTBR", "ALRS",
    ]

    existing = load_existing()
    existing_tickers = sorted(existing["ticker"].unique().tolist())
    all_tickers = sorted(set(existing_tickers + [t.upper() for t in EXTRA_TICKERS]))
    print(f"Тикеры в dividends_all.csv: {existing_tickers}")
    if EXTRA_TICKERS:
        print(f"Дополнительные тикеры: {EXTRA_TICKERS}")

    # Загрузка с dohod.ru
    all_new = []
    for ticker in all_tickers:
        df = fetch_dividends(ticker)
        if not df.empty:
            all_new.append(df)
        time.sleep(REQUEST_DELAY)

    if not all_new:
        print("Ничего не загружено!")
        return

    new_df = pd.concat(all_new, ignore_index=True)

    # Сравнение
    print("\n--- Сравнение с существующим файлом ---")
    for ticker in existing_tickers:
        comp = compare_with_existing(new_df, existing, ticker)
        status = "OK" if comp["only_in_existing"] == 0 else "MISMATCH"
        print(f"  {ticker}: было {comp['existing_count']}, стало {comp['new_count']}, "
              f"совпало {comp['matched']}, новых {comp['only_in_new']}, "
              f"пропало {comp['only_in_existing']} [{status}]")

    # Сохранение
    new_df = new_df.sort_values(["ticker", "announcement_date"]).reset_index(drop=True)
    new_df.to_csv(DIVIDENDS_PATH, index=False)
    print(f"\nСохранено {len(new_df)} записей в {DIVIDENDS_PATH}")


if __name__ == "__main__":
    main()
