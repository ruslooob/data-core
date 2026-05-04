-- Запускается при первом старте контейнера (initdb-фаза).
-- Включает PL/Python в БД postgres, которую создаёт сам контейнер по
-- POSTGRES_DB. Дальше отдельные UDF (car, vol_ratio и т.д.) создаются
-- скриптами миграции — здесь только инфраструктурный extension.
CREATE EXTENSION IF NOT EXISTS plpython3u;
