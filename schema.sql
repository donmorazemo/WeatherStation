-- LOCAL SQLite ONLY — do NOT run this in Supabase (use supabase_schema.sql instead).
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    temperature_c REAL    NOT NULL CHECK(temperature_c BETWEEN -40 AND 85),
    pressure_hpa  REAL    NOT NULL CHECK(pressure_hpa  BETWEEN 300 AND 1100),
    pushed        INTEGER NOT NULL DEFAULT 0 CHECK(pushed IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_readings_pushed ON readings(pushed);
