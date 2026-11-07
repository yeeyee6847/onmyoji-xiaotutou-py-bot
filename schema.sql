-- 独立 schema，不改动现有 bot 的表，也不暴露给 Supabase Data API。
CREATE SCHEMA IF NOT EXISTS lottery_app;
CREATE TABLE IF NOT EXISTS lottery_app.draws (
    id uuid PRIMARY KEY,
    state jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE lottery_app.draws ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS lottery_draws_created_idx
    ON lottery_app.draws (created_at DESC);
