BEGIN;
CREATE TABLE IF NOT EXISTS onmyoji_shards.fragment_current (
 game_account_id uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id) ON DELETE CASCADE,
 shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id) ON DELETE RESTRICT,
 target text NOT NULL CHECK(target IN ('offers','wants')),
 quantity integer NOT NULL CHECK(quantity BETWEEN 0 AND 99999),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(game_account_id,shikigami_id,target)
);
-- Carry forward the latest confirmed quantities once; never overwrite newer current edits on rerun.
INSERT INTO onmyoji_shards.fragment_current(game_account_id,shikigami_id,target,quantity,updated_at)
 SELECT DISTINCT ON(i.game_account_id,r.shikigami_id,i.target)
 i.game_account_id,r.shikigami_id,i.target,r.quantity,i.created_at
 FROM onmyoji_shards.fragment_imports i JOIN onmyoji_shards.fragment_import_rows r ON r.import_id=i.id
 WHERE i.status IN ('confirmed','applied') AND r.confirmed AND r.included AND r.shikigami_id IS NOT NULL
 ORDER BY i.game_account_id,r.shikigami_id,i.target,i.created_at DESC,i.id DESC
 ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS onmyoji_shards.portrait_samples (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 player_id uuid NOT NULL REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
 job_id uuid NOT NULL, row_number integer NOT NULL,
 crop_png bytea NOT NULL CHECK(octet_length(crop_png)<=262144),
 portrait_png bytea NOT NULL CHECK(octet_length(portrait_png)<=262144),
 raw_name text NOT NULL DEFAULT '',
 shikigami_id uuid REFERENCES onmyoji_shards.shikigami(id) ON DELETE RESTRICT,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 reviewed_by uuid REFERENCES onmyoji_shards.players(id),
 reviewed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(job_id,row_number),
 CHECK(status<>'approved' OR (shikigami_id IS NOT NULL AND reviewed_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS portrait_review_idx ON onmyoji_shards.portrait_samples(status,created_at DESC);
CREATE INDEX IF NOT EXISTS fragment_lookup_idx ON onmyoji_shards.fragment_current(shikigami_id,target) WHERE quantity>0;
ALTER TABLE onmyoji_shards.fragment_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.portrait_samples ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON onmyoji_shards.fragment_current,onmyoji_shards.portrait_samples FROM PUBLIC,anon,authenticated;
COMMIT;
