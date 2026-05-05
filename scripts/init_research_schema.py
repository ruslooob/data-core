"""Идемпотентная миграция схемы под исследования (Research).

Делает следующие шаги:
1. Создаёт таблицу `research`.
2. Засеивает системное `Default`-исследование с фиксированным id.
3. Добавляет колонку `research_id` в `strategies`, `rules`, `environments`,
   `backtest_results` (NULLable, REFERENCES research(id) ON DELETE CASCADE).
4. Привязывает все существующие `backtest_results.research_id` к Default,
   делает колонку NOT NULL.
5. Снимает старый глобальный UNIQUE(name) в strategies/rules/environments
   и ставит вместо него:
     - UNIQUE (research_id, name) — уникальность имени в пределах исследования;
     - partial UNIQUE (name) WHERE research_id IS NULL — уникальность имени
       среди общих сущностей.

Скрипт идемпотентен: повторный запуск не меняет состояние БД.
Запуск:
    python scripts/init_research_schema.py
"""
from __future__ import annotations

import sys

import psycopg

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PG_DSN = 'host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres'

DEFAULT_RESEARCH_ID = '00000000-0000-0000-0000-000000000001'
DEFAULT_RESEARCH_NAME = 'Default'

OWNED_TABLES = ('strategies', 'rules', 'environments')


def _column_exists(cur: psycopg.Cursor, table: str, column: str) -> bool:
    cur.execute(
        'SELECT 1 FROM information_schema.columns '
        'WHERE table_name = %s AND column_name = %s',
        [table, column],
    )
    return cur.fetchone() is not None


def _column_is_nullable(cur: psycopg.Cursor, table: str, column: str) -> bool:
    cur.execute(
        'SELECT is_nullable FROM information_schema.columns '
        'WHERE table_name = %s AND column_name = %s',
        [table, column],
    )
    row = cur.fetchone()
    return row is not None and row[0] == 'YES'


def _constraint_exists(cur: psycopg.Cursor, table: str, name: str) -> bool:
    cur.execute(
        'SELECT 1 FROM pg_constraint '
        'WHERE conrelid = %s::regclass AND conname = %s',
        [table, name],
    )
    return cur.fetchone() is not None


def _index_exists(cur: psycopg.Cursor, name: str) -> bool:
    cur.execute('SELECT 1 FROM pg_indexes WHERE indexname = %s', [name])
    return cur.fetchone() is not None


def main() -> None:
    pg = psycopg.connect(PG_DSN, autocommit=False)
    try:
        with pg.cursor() as cur:
            print('1. CREATE TABLE research')
            cur.execute("""
                CREATE TABLE IF NOT EXISTS research (
                    id          VARCHAR PRIMARY KEY,
                    name        VARCHAR NOT NULL UNIQUE,
                    description TEXT,
                    conclusion  TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            print(f'2. seed Default-research id={DEFAULT_RESEARCH_ID}')
            cur.execute(
                'INSERT INTO research (id, name) VALUES (%s, %s) '
                'ON CONFLICT (id) DO NOTHING',
                [DEFAULT_RESEARCH_ID, DEFAULT_RESEARCH_NAME],
            )

            print('3. ADD COLUMN research_id (NULL) в стратегии/правила/окружения/прогоны')
            for tbl in OWNED_TABLES + ('backtest_results',):
                cur.execute(
                    f'ALTER TABLE {tbl} '
                    f'ADD COLUMN IF NOT EXISTS research_id VARCHAR '
                    f'REFERENCES research(id) ON DELETE CASCADE'
                )

            print('4. backtest_results: bind to Default + SET NOT NULL')
            cur.execute(
                'UPDATE backtest_results SET research_id = %s WHERE research_id IS NULL',
                [DEFAULT_RESEARCH_ID],
            )
            if _column_is_nullable(cur, 'backtest_results', 'research_id'):
                cur.execute(
                    'ALTER TABLE backtest_results ALTER COLUMN research_id SET NOT NULL'
                )

            print('5. UNIQUE constraints: drop old, create new')
            for tbl in OWNED_TABLES:
                old_cons = f'{tbl}_name_key'
                if _constraint_exists(cur, tbl, old_cons):
                    cur.execute(f'ALTER TABLE {tbl} DROP CONSTRAINT {old_cons}')
                composite_idx = f'{tbl}_research_id_name_uniq'
                cur.execute(
                    f'CREATE UNIQUE INDEX IF NOT EXISTS {composite_idx} '
                    f'ON {tbl} (research_id, name)'
                )
                shared_idx = f'{tbl}_shared_name_uniq'
                cur.execute(
                    f'CREATE UNIQUE INDEX IF NOT EXISTS {shared_idx} '
                    f'ON {tbl} (name) WHERE research_id IS NULL'
                )

        pg.commit()
        print('done.')
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()


if __name__ == '__main__':
    main()
