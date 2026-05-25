"""Скан всех CSV-файлов котировок на предмет подозрительных дневных скачков — возможных пропущенных сплитов."""
import pandas as pd
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STOCKS_DIR = os.path.join(HERE, '..', '..', 'data', 'stocks')

splits_df = pd.read_csv(os.path.join(STOCKS_DIR, 'splits.csv'))
splits: dict[str, list[dict]] = {}
for _, r in splits_df.iterrows():
    splits.setdefault(r['ticker'], []).append({
        'split_date': r['split_date'],
        'ratio': float(r['ratio']),
    })

files = sorted(glob.glob(os.path.join(STOCKS_DIR, '*.txt')))

THRESHOLD_UP = 3.0
THRESHOLD_DOWN = 1 / 3.0

print(f"Сканирую {len(files)} файлов (скачки >3x или <1/3x)\n")
print("Ticker     Date        PrevClose        Close         Ratio  Comment")
print('-' * 90)

for fpath in files:
    fname = os.path.basename(fpath)
    ticker = fname.split('_')[0]

    try:
        df = pd.read_csv(fpath, sep=';', header=0, encoding='utf-8')
        df.columns = df.columns.str.strip().str.replace(r'[<>]', '', regex=True).str.upper()
        df['DATE'] = pd.to_datetime(df['DATE'].astype(str), format='%Y%m%d')
        df = df.sort_values('DATE').reset_index(drop=True)
    except Exception as ex:
        print(f"{ticker}: read error: {ex}")
        continue

    if len(df) < 2:
        continue

    df['prev_close'] = df['CLOSE'].shift(1)
    df['ratio'] = df['CLOSE'] / df['prev_close']

    jumps = df[(df['ratio'] > THRESHOLD_UP) | (df['ratio'] < THRESHOLD_DOWN)]
    if jumps.empty:
        continue

    known_dates = set(pd.Timestamp(s['split_date']).date() for s in splits.get(ticker, []))

    for _, row in jumps.iterrows():
        date = row['DATE'].date()
        if any(abs((date - kd).days) <= 1 for kd in known_dates):
            continue
        comment = "possible forward split" if row['ratio'] < 0.5 else "possible reverse split"
        print(f"{ticker:<10} {str(date):<12} {row['prev_close']:>12.4f}  {row['CLOSE']:>12.4f}  {row['ratio']:>8.4f}  {comment}")
