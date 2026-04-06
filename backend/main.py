"""FastAPI backend для data-core."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.stock_data_provider import list_avail_tickers

# Служебные файлы, которые не являются тикерами акций
_NON_TICKER_FILES = {"DIVIDENDS", "IMOEX", "RUONIA", "SPLITS"}

app = FastAPI(title="data-core API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tickers")
def get_tickers() -> list[str]:
    """Возвращает список доступных тикеров акций (без служебных файлов)."""
    return [t for t in list_avail_tickers() if t not in _NON_TICKER_FILES]
