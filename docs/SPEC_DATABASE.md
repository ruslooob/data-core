# База данных и миграции

Postgres-схема и PL/Python-функции управляются Liquibase. Скрипты на Python, которые раньше создавали схему вручную (`init_research_schema.py`, `migrate_*_to_postgres.py`, `init_postgres_*_udfs.py`), удалены — их роль перенесена в changelog.

## Где живут changelog'и

```
db/
└── changelog/
    ├── changelog-master.xml          ← главный файл, через <include> подключает остальные
    └── changes/
        ├── 001-initial-schema.xml    ← все таблицы + индексы текущей prod-схемы
        ├── 002-udfs.xml              ← XML-обёртка с <sqlFile>
        ├── 002-udfs.sql              ← тела PL/Python-функций
        └── 003-seed-default-research.xml ← INSERT системного Default-исследования
```

Имена с числовым префиксом задают порядок применения. **Один changeset — одно атомарное изменение.**

## Запуск миграций

Liquibase живёт как отдельный сервис в `docker-compose.yml` под профилем `migrate` — он не стартует при обычном `docker compose up`. Команды:

```bash
# Применить все pending changesets
docker compose --profile migrate run --rm liquibase update

# Посмотреть, какие changesets ещё не применены
docker compose --profile migrate run --rm liquibase status

# Откатить последний changeset (опасно — для DDL без rollback это no-op)
docker compose --profile migrate run --rm liquibase rollbackCount 1

# Прогнать changelog на временной БД (без применения к рабочей)
docker compose --profile migrate run --rm \
  -e LIQUIBASE_COMMAND_URL=jdbc:postgresql://postgres:5432/test_db \
  liquibase update
```

## Когда писать новый changeset

Любое изменение схемы или PL/Python-функции — новый файл в `changes/` с увеличенным префиксом. **Не редактируй уже применённые changesets** — Liquibase отметит конфликт по checksum и откажется работать. Исключение — файлы с `runOnChange="true"` (см. ниже).

### DDL (CREATE TABLE, ALTER TABLE, индексы) — XML-теги

Используем нативные теги Liquibase: `<createTable>`, `<addColumn>`, `<createIndex>`, `<addForeignKeyConstraint>`, `<insert>`. Postgres-специфика, которую Liquibase не выражает (например, partial UNIQUE-индексы), идёт через `<sql>`.

Пример атомарного changeset'а:

```xml
<changeSet id="004-add-event-priority" author="ruslan">
    <addColumn tableName="events">
        <column name="priority" type="INTEGER" defaultValueNumeric="0">
            <constraints nullable="false"/>
        </column>
    </addColumn>
</changeSet>
```

### PL/Python-функции — SQL-файл через `<sqlFile>`

Функции на `LANGUAGE plpython3u` — обычные `CREATE OR REPLACE FUNCTION` в SQL-файле, подключаются через XML-обёртку с двумя обязательными атрибутами:

- `runOnChange="true"` — пересоздать функцию при изменении файла; безопасно для `CREATE OR REPLACE`.
- `splitStatements="false"` — внутри Python-тел встречаются `;`, Liquibase не должен резать файл.

```xml
<changeSet id="002-udfs" author="ruslan" runOnChange="true">
    <sqlFile path="002-udfs.sql"
             relativeToChangelogFile="true"
             splitStatements="false"
             stripComments="false"
             encoding="UTF-8"/>
</changeSet>
```

## Загрузка данных

После создания схемы данные грузит отдельный скрипт `scripts/load_data_to_postgres.py` — котировки, RUONIA, накопительный счёт SAVINGS_MIACR (синтетический индекс под овернайт-ставку MIACR), дивиденды, теги, события, сохранённые PQL-запросы. Все INSERT'ы через `ON CONFLICT DO NOTHING` — повторный запуск безопасен. Пользовательские данные (research, strategies, rules, backtest_results, trade_journal) этим скриптом **не** заливаются — они восстанавливаются отдельно из `pg_dump`-снапшота при необходимости.

## End-to-end сценарий «с нуля»

```bash
# 1. Перед сносом: дамп данных
docker exec data-core-postgres pg_dump -U postgres -d postgres \
    --format=custom --file=/tmp/full.dump
docker cp data-core-postgres:/tmp/full.dump data/db/backup_<timestamp>/full.dump

# 2. Снести volume и поднять чистый Postgres
docker compose down -v
docker compose up -d postgres

# 3. Применить changelog
docker compose --profile migrate run --rm liquibase update

# 4. Загрузить референсные данные
python scripts/load_data_to_postgres.py

# 5. (Опционально) Восстановить пользовательские данные из дампа.
#    Default-исследование удаляем перед restore — оно есть в дампе.
docker exec data-core-postgres psql -U postgres -d postgres \
    -c "DELETE FROM research WHERE id = '00000000-0000-0000-0000-000000000001';"
docker cp data/db/backup_<timestamp>/full.dump data-core-postgres:/tmp/full.dump
docker exec data-core-postgres pg_restore -U postgres -d postgres \
    --data-only --disable-triggers --single-transaction /tmp/full.dump

# 6. Проверка
cd backend && python -m pytest tests/ -v
```
