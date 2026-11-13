BEGIN;
ALTER TABLE onmyoji_shards.shikigami ADD COLUMN IF NOT EXISTS display_order integer
    CHECK (display_order > 0);
CREATE UNIQUE INDEX IF NOT EXISTS shikigami_display_order_unique
    ON onmyoji_shards.shikigami(display_order);
COMMENT ON COLUMN onmyoji_shards.shikigami.display_order IS 'Release order supplied by owner; larger numbers display first. Unassigned entries are NULL.';
COMMIT;
