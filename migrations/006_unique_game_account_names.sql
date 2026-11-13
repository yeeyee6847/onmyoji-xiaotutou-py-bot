BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS game_accounts_nickname_unique
 ON onmyoji_shards.game_accounts(lower(btrim(nickname)));
COMMIT;
