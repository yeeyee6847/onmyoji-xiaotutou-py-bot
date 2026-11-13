BEGIN;
CREATE TABLE IF NOT EXISTS onmyoji_shards.login_tokens (
    token_hash text PRIMARY KEY CHECK (char_length(token_hash)=64),
    player_id uuid NOT NULL REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS login_tokens_player_idx ON onmyoji_shards.login_tokens(player_id);
CREATE TABLE IF NOT EXISTS onmyoji_shards.password_credentials (
    player_id uuid PRIMARY KEY REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
    password_hash text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS onmyoji_shards.web_sessions (
    token_hash text PRIMARY KEY CHECK (char_length(token_hash)=64),
    player_id uuid NOT NULL REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
    auth_method text NOT NULL CHECK (auth_method IN ('discord_link','password')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_player_idx ON onmyoji_shards.web_sessions(player_id);
CREATE TABLE IF NOT EXISTS onmyoji_shards.login_rate_limits (
    key_hash text PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 1,
    resets_at timestamptz NOT NULL
);
ALTER TABLE onmyoji_shards.login_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.password_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.web_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.login_rate_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON onmyoji_shards.login_tokens, onmyoji_shards.password_credentials,
    onmyoji_shards.web_sessions, onmyoji_shards.login_rate_limits FROM PUBLIC, anon, authenticated;
COMMIT;
