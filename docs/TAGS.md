# Система тегов событий

Каждое событие в системе описывается набором тегов из справочника. Теги заменяют жёсткие колонки (ticker, event_type) и позволяют гибко размечать события любой природы.

---

## Схема данных

Три таблицы:

### events
Основная таблица событий.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | UUID | Уникальный идентификатор |
| date_start | date | Дата начала события |
| date_end | date (nullable) | Дата окончания (если применимо) |
| event | text | Текстовое описание |

### tags
Справочник тегов.

| Колонка | Тип | Описание |
|---------|-----|----------|
| code | string (PK) | Короткий код: `LKOH`, `SANCTIONS`, `RUS` |
| name | string (nullable) | Полное название |
| type | string | Тип тега (см. иерархию ниже) |

### event_tags
Связь M2M.

| Колонка | Тип | Описание |
|---------|-----|----------|
| event_id | UUID (FK → events) | Событие |
| tag_code | string (FK → tags) | Тег |

---

## Иерархия типов тегов

```
actor           — кто действует / кого затрагивает
 ├── country    — государства, регионы (RUS, USA, CHN)
 ├── organization — организации, союзы (UN, NATO, OPEC, CBR)
 ├── company    — корпорации (LKOH, SBER, GAZPROM)
 ├── person     — персоны (PUTIN, BIDEN)
 └── region     — макрорегионы (EUROPE, ASIA)

event           — что произошло
 ├── topic      — тема события (PLANE_CRASH, EARTHQUAKE, DIVIDEND)
 ├── policy     — нормативные действия (SANCTIONS, LAW_REFORM, TAX_CHANGE)
 └── crisis     — кризисные явления (WAR, DEFAULT)

context         — контекст, в котором произошло
 ├── asset      — финансовые инструменты (OIL, GOLD, USD/RUB)
 ├── sector     — отрасли (ENERGY, TECH, FINANCE)
 └── metric     — экономические показатели (INFLATION, GDP)
```

---

## Примеры разметки

### Дивиденды LKOH
```
event: "Объявление дивидендов LKOH 85 руб/акция"
tags: LKOH (company), DIVIDEND (topic)
```

### Санкционный пакет ЕС
```
event: "6-й пакет санкций ЕС: эмбарго на нефть, отключение банков от SWIFT"
tags: RUS (country), SANCTIONS (policy), ENERGY (sector), OIL (asset), EU (organization)
```

### Решение ЦБ по ставке
```
event: "ЦБ РФ повысил ключевую ставку до 16%"
tags: RUS (country), CBR (organization), MONETARY_POLICY (policy), FINANCE (sector)
```

---

## Использование в запросах

Синтаксический сахар `HAS_TAG('X')` разворачивается в:
```sql
EXISTS (SELECT 1 FROM event_tags WHERE event_id = e.id AND tag_code = 'X')
```

Фильтрация по типу тега — через JOIN:
```sql
JOIN event_tags et ON e.id = et.event_id
JOIN tags t ON et.tag_code = t.code AND t.type = 'company'
```
