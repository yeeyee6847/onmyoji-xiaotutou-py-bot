BEGIN;
CREATE TABLE IF NOT EXISTS onmyoji_shards.trades(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 requester_id uuid NOT NULL REFERENCES onmyoji_shards.players(id),
 recipient_id uuid NOT NULL REFERENCES onmyoji_shards.players(id),
 requester_account uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id),
 recipient_account uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected','cancelled','completed')),
 requester_confirmed boolean NOT NULL DEFAULT false,recipient_confirmed boolean NOT NULL DEFAULT false,
 thread_id text,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 notification_threads jsonb NOT NULL DEFAULT '{}',
 CHECK(requester_id<>recipient_id),CHECK(requester_account<>recipient_account)
);
CREATE TABLE IF NOT EXISTS onmyoji_shards.trade_items(
 trade_id uuid NOT NULL REFERENCES onmyoji_shards.trades(id) ON DELETE CASCADE,
 direction text NOT NULL CHECK(direction IN ('give','receive')),
 shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id),
 quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 99999),
 PRIMARY KEY(trade_id,direction,shikigami_id)
);
CREATE TABLE IF NOT EXISTS onmyoji_shards.trade_reservations(
 trade_id uuid NOT NULL REFERENCES onmyoji_shards.trades(id) ON DELETE CASCADE,
 game_account_id uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id),
 shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id),
 target text NOT NULL CHECK(target IN ('offers','wants')),
 quantity integer NOT NULL CHECK(quantity>0),
 PRIMARY KEY(trade_id,game_account_id,shikigami_id,target)
);
CREATE INDEX IF NOT EXISTS reservations_stock_idx ON onmyoji_shards.trade_reservations(game_account_id,shikigami_id,target);
CREATE TABLE IF NOT EXISTS onmyoji_shards.trade_outbox(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 trade_id uuid NOT NULL REFERENCES onmyoji_shards.trades(id) ON DELETE CASCADE,
 event text NOT NULL,recipients jsonb NOT NULL DEFAULT '[]',status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','failed')),
 attempts integer NOT NULL DEFAULT 0,next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz,lease_token uuid,last_error text,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(trade_id,event)
);
CREATE INDEX IF NOT EXISTS outbox_pending_idx ON onmyoji_shards.trade_outbox(status,next_attempt_at);
ALTER TABLE onmyoji_shards.trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.trade_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.trade_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE onmyoji_shards.trade_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON onmyoji_shards.trades,onmyoji_shards.trade_items,onmyoji_shards.trade_reservations,onmyoji_shards.trade_outbox FROM PUBLIC,anon,authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA onmyoji_shards FROM PUBLIC,anon,authenticated;
COMMIT;
