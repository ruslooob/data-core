"""Лёгкая обёртка для исполнения PQL-запросов на Postgres.

PQL-движок построен поверх Postgres: все UDF (`car`, `vol_ratio`,
`volume_ratio`, …) живут в самой БД (`scripts/init_postgres_udfs.py`),
системные рецепты в `saved_queries` создаются миграцией. Эта обёртка
нужна только чтобы прогревать общий pool коннектов при старте процесса.

Публичный API:
- `PrecedentEngine().execute(sql, params)` — выполнить произвольный SQL и
  вернуть курсор-результат как список кортежей + колонки (строится в
  вызывающем коде).

Поставщики данных (Stock/Market/Dividend) живут отдельно и читают
напрямую из Postgres через `core.postgres_db`.
"""
from __future__ import annotations

from core.postgres_db import get_pool


class PrecedentEngine:
    """Тонкий помощник: даёт коннект из pool по запросу.

    Параметры:
        stocks/market — игнорируются. Оставлены в сигнатуре чтобы не
                        ломать существующие call-site до полного refactor'а.
    """

    def __init__(self, stocks=None, market=None):
        del stocks, market
        # Pool ленивый, тут просто прогреваем его.
        get_pool()

    def close(self) -> None:
        """no-op: pool управляется глобально."""
        pass
