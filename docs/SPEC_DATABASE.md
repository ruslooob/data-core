# База данных и миграции

Postgres-схема и PL/Python-функции управляются Liquibase. Главный файл — `db/changelog/changelog-master.xml`. Имена файлов с числовым префиксом задают порядок применения.

## Запуск миграций

Liquibase живёт как отдельный сервис в `docker-compose.yml` под профилем `migrate`. Команды:

```bash
# Применить все pending changesets
docker compose --profile migrate run --rm liquibase update

# Посмотреть, какие changesets ещё не применены
docker compose --profile migrate run --rm liquibase status

# Откатить последний changeset
docker compose --profile migrate run --rm liquibase rollbackCount 1

# Прогнать changelog на временной БД
docker compose --profile migrate run --rm \
  -e LIQUIBASE_COMMAND_URL=jdbc:postgresql://postgres:5432/test_db \
  liquibase update
```
## Загрузка данных

После создания схемы данные грузит отдельный скрипт `scripts/load_data_to_postgres.py`. Все INSERT'ы через `ON CONFLICT DO NOTHING` — повторный запуск безопасен. Пользовательские данные этим скриптом **не** заливаются — они восстанавливаются отдельно из `pg_dump`-снапшота при необходимости.

## Правила changeset'а

Один changeset — одно атомарное изменение. **Не редактируй уже применённые changesets** — Liquibase отметит конфликт по checksum и откажется работать. Дополнительные требования к каждому changeset'у:

### Идемпотентность

Changeset должен переживать повторное выполнение без побочек. Liquibase сам пропускает применённые changesets по checksum, но эта защита работает только пока файл не менялся. Идемпотентность нужна явно, когда:

- В файле стоит `runOnChange="true"` (типично для UDF через `<sqlFile>`) — Liquibase запустит его заново при любом изменении тела.
- Changeset вставляет данные — `INSERT ... ON CONFLICT DO NOTHING` или эквивалент через `<preConditions>`.
- Состояние БД могло быть частично накатано вручную перед миграцией.

Для DDL — `CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION` либо проверка через `<preConditions>`.

### Rollback

Liquibase автоматически откатывает только то, что генерирует из нативных тегов (`<createTable>`, `<addColumn>`, `<createIndex>`). Для `<sql>` и `<sqlFile>` нужен явный `<rollback>` — без него `rollbackCount` будет no-op:

```xml
<changeSet id="..." author="...">
    <sql>CREATE INDEX events_announce_idx ON events (announce_date)</sql>
    <rollback>DROP INDEX events_announce_idx</rollback>
</changeSet>
```

Rollback пишется сразу, даже если в текущем dev-цикле не нужен — без него возврат к предыдущей версии перед боевым деплоем невозможен.

### Preconditions

Когда changeset нужно штатно пропустить при определённом состоянии БД, используется `<preConditions onFail="MARK_RAN">`:

```xml
<changeSet id="..." author="...">
    <preConditions onFail="MARK_RAN">
        <not><tableExists tableName="events"/></not>
    </preConditions>
    <createTable tableName="events"> ... </createTable>
</changeSet>
```

`MARK_RAN` помечает changeset выполненным и идёт дальше; `HALT` (по умолчанию) — падает с ошибкой. Применяется там, где changeset может оказаться не нужен на «странной» БД (например, после ручного восстановления из дампа или миграции с другой ветки).

## Восстановление пользовательских данных из дампа

`docker compose down -v` сносит всё, включая пользовательские данные. `load_data_to_postgres.py` грузит только референсные данные. Чтобы вернуть пользовательские — накатываем их поверх свежей схемы из последнего дампа (см. `scripts/backup_postgres.py`):

```bash
# 1. Удалить системное Default-исследование, чтобы не было PK-конфликта.
#    Changeset 003-seed-default-research уже создал его при `liquibase update`;
#    в дампе оно тоже есть с тем же UUID.
docker exec data-core-postgres psql -U postgres -d postgres \
    -c "DELETE FROM research WHERE id = '00000000-0000-0000-0000-000000000001';"

# 2. Накатить данные из дампа. BACKUP_DIR — папка из data/db/backup_*.
docker cp data/db/$BACKUP_DIR/full.dump data-core-postgres:/tmp/full.dump
docker exec data-core-postgres pg_restore -U postgres -d postgres \
    --data-only --disable-triggers --single-transaction /tmp/full.dump
```

`--data-only` — схема уже накатана Liquibase, из дампа берём только строки. `--disable-triggers` — иначе FK-проверки могут сломать загрузку при произвольном порядке таблиц в дампе.
