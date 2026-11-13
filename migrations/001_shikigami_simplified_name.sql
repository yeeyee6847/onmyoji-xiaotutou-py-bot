-- Add a separate simplified name without changing the original catalogue name.
BEGIN;
ALTER TABLE onmyoji_shards.shikigami
    ADD COLUMN IF NOT EXISTS name_simplified text
    CHECK (name_simplified IS NULL OR
           (name_simplified = btrim(name_simplified) AND char_length(name_simplified) BETWEEN 1 AND 40));
COMMENT ON COLUMN onmyoji_shards.shikigami.name_simplified IS 'User-provided simplified Chinese name; name retains the original traditional name.';
COMMIT;
