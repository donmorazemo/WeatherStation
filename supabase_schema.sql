-- Run this once in the Supabase SQL editor to create the remote table.

CREATE TABLE IF NOT EXISTS readings (
    id            BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL,
    temperature_c REAL        NOT NULL CHECK(temperature_c BETWEEN -40 AND 85),
    pressure_hpa  REAL        NOT NULL CHECK(pressure_hpa  BETWEEN 300 AND 1100)
);

CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts DESC);
