-- 结缘帖：碎片交换的独立数据库结构（初始建表脚本）。
-- 仅作用于 onmyoji_shards，不修改 lottery_app、public 或 auth 中的表。
-- 本文件不会由网站或 Render 启动流程自动执行。
-- 未来在 Supabase SQL Editor 中由数据库管理员执行；当前 Web 仍使用 Mock。
BEGIN;

CREATE SCHEMA IF NOT EXISTS onmyoji_shards;

-- 1. 式神图鉴；头像只保存持久化对象路径 / URL，不存图片二进制。
CREATE TABLE IF NOT EXISTS onmyoji_shards.shikigami (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (name = btrim(name) AND char_length(name) BETWEEN 1 AND 40),
    name_simplified text CHECK (name_simplified IS NULL OR (name_simplified = btrim(name_simplified) AND char_length(name_simplified) BETWEEN 1 AND 40)),
    display_order integer CHECK (display_order > 0),
    rarity text NOT NULL CHECK (rarity IN ('SSR', 'SP', 'UR', 'COLLAB')),
    image_path text CHECK (image_path IS NULL OR char_length(btrim(image_path)) > 0),
    collaboration_name text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS shikigami_name_unique
    ON onmyoji_shards.shikigami (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS shikigami_display_order_unique
    ON onmyoji_shards.shikigami (display_order);

-- 繁简体、其他名字及人工核对后认可的 OCR 别名。
-- 名字与别名跨两张表的冲突，仍需后端统一规范化后检查。
CREATE TABLE IF NOT EXISTS onmyoji_shards.shikigami_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id) ON DELETE CASCADE,
    alias text NOT NULL CHECK (alias = btrim(alias) AND char_length(alias) BETWEEN 1 AND 40),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS shikigami_alias_unique
    ON onmyoji_shards.shikigami_aliases (lower(alias));
CREATE INDEX IF NOT EXISTS aliases_shikigami_idx
    ON onmyoji_shards.shikigami_aliases (shikigami_id);

-- 2. 玩家：独立于游戏账号，也独立于 Web / Discord 身分。
CREATE TABLE IF NOT EXISTS onmyoji_shards.players (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL CHECK (char_length(btrim(display_name)) BETWEEN 1 AND 80),
    role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 一个玩家可绑定多个平台身分；同一平台 ID 不可绑定给两个玩家。
-- Discord ID 用 text 保存，避免传到 JavaScript 后超过安全整数范围。
-- external_subject 记录平台验证后的 ID，不能使用显示名称作为登录凭据。
CREATE TABLE IF NOT EXISTS onmyoji_shards.player_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('discord', 'supabase', 'web')),
    external_subject text NOT NULL CHECK (external_subject = btrim(external_subject)
        AND char_length(external_subject) BETWEEN 1 AND 255),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, external_subject)
);
CREATE INDEX IF NOT EXISTS identities_player_idx
    ON onmyoji_shards.player_identities (player_id);

-- 3. 一个玩家可拥有多个游戏账号，碎片按游戏账号分开管理。
CREATE TABLE IF NOT EXISTS onmyoji_shards.game_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES onmyoji_shards.players(id) ON DELETE CASCADE,
    nickname text NOT NULL CHECK (char_length(btrim(nickname)) BETWEEN 1 AND 80),
    game_uid text CHECK (game_uid IS NULL OR (game_uid = btrim(game_uid) AND char_length(game_uid) BETWEEN 1 AND 100)),
    region text NOT NULL DEFAULT 'unspecified' CHECK (region = btrim(region) AND char_length(region) BETWEEN 1 AND 40),
    server_name text NOT NULL CHECK (server_name = btrim(server_name) AND char_length(server_name) BETWEEN 1 AND 80),
    platform text NOT NULL DEFAULT 'unspecified' CHECK (platform = btrim(platform) AND char_length(platform) BETWEEN 1 AND 40),
    guild_name text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS accounts_player_idx
    ON onmyoji_shards.game_accounts (player_id);
CREATE UNIQUE INDEX IF NOT EXISTS game_account_identity_unique
    ON onmyoji_shards.game_accounts (region, server_name, platform, game_uid)
    WHERE game_uid IS NOT NULL;

-- 4. 可提供碎片：不是玩家所有碎片的总数，而是愿意拿来交换的数量。
-- 同一账号 + 同一式神只有一笔，以 UPDATE / UPSERT 更新，不重复新增或累加。
CREATE TABLE IF NOT EXISTS onmyoji_shards.fragment_offers (
    game_account_id uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id) ON DELETE CASCADE,
    shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id) ON DELETE RESTRICT,
    quantity integer NOT NULL CHECK (quantity BETWEEN 0 AND 99999),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (game_account_id, shikigami_id)
);
CREATE INDEX IF NOT EXISTS positive_offers_shikigami_idx
    ON onmyoji_shards.fragment_offers (shikigami_id, game_account_id)
    WHERE quantity > 0;

-- 5. 想要碎片：独立于提供清单；同一账号可以同时提供及需求同一式神。
CREATE TABLE IF NOT EXISTS onmyoji_shards.fragment_wants (
    game_account_id uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id) ON DELETE CASCADE,
    shikigami_id uuid NOT NULL REFERENCES onmyoji_shards.shikigami(id) ON DELETE RESTRICT,
    quantity integer NOT NULL CHECK (quantity BETWEEN 0 AND 99999),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (game_account_id, shikigami_id)
);
CREATE INDEX IF NOT EXISTS positive_wants_shikigami_idx
    ON onmyoji_shards.fragment_wants (shikigami_id, game_account_id)
    WHERE quantity > 0;

-- 6. OCR 导入暂存：保留来源与核对记录，避免 OCR 直接覆盖提供清单。
CREATE TABLE IF NOT EXISTS onmyoji_shards.fragment_imports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_account_id uuid NOT NULL REFERENCES onmyoji_shards.game_accounts(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('web', 'discord')),
    target text NOT NULL DEFAULT 'offers' CHECK (target IN ('offers', 'wants')),
    image_path text,
    original_filename text,
    status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'review', 'confirmed', 'applied', 'failed')),
    engine_name text,
    error_message text,
    applied_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'applied') = (applied_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS imports_account_created_idx
    ON onmyoji_shards.fragment_imports (game_account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS onmyoji_shards.fragment_import_rows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id uuid NOT NULL REFERENCES onmyoji_shards.fragment_imports(id) ON DELETE CASCADE,
    row_number smallint NOT NULL CHECK (row_number > 0),
    raw_name text NOT NULL DEFAULT '',
    raw_quantity text NOT NULL DEFAULT '',
    shikigami_id uuid REFERENCES onmyoji_shards.shikigami(id) ON DELETE RESTRICT,
    quantity integer CHECK (quantity BETWEEN 0 AND 99999),
    name_confidence numeric(5,4) CHECK (name_confidence BETWEEN 0 AND 1),
    quantity_confidence numeric(5,4) CHECK (quantity_confidence BETWEEN 0 AND 1),
    bbox jsonb,
    included boolean NOT NULL DEFAULT true,
    confirmed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (import_id, row_number),
    CHECK (NOT confirmed OR (included AND shikigami_id IS NOT NULL AND quantity IS NOT NULL)),
    CHECK (bbox IS NULL OR CASE WHEN jsonb_typeof(bbox) = 'array'
        THEN jsonb_array_length(bbox) = 4 ELSE false END)
);
CREATE INDEX IF NOT EXISTS import_rows_shikigami_idx
    ON onmyoji_shards.fragment_import_rows (shikigami_id);

-- 所有更新时间由数据库维护。后续撮合、交换记录等表仍可加在此 schema 下。
CREATE OR REPLACE FUNCTION onmyoji_shards.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'shikigami', 'shikigami_aliases', 'players', 'player_identities',
        'game_accounts', 'fragment_offers', 'fragment_wants',
        'fragment_imports', 'fragment_import_rows'
    ] LOOP
        EXECUTE format('ALTER TABLE onmyoji_shards.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP TRIGGER IF EXISTS set_updated_at ON onmyoji_shards.%I', table_name);
        EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON onmyoji_shards.%I '
            'FOR EACH ROW EXECUTE FUNCTION onmyoji_shards.touch_updated_at()', table_name);
    END LOOP;
END;
$$;

-- 默认仅供服务器使用数据库连接访问，不向浏览器开放此 schema。
-- RLS 暂不设置客户端策略；未来接正式身分系统后再设计玩家 / Admin 权限。
REVOKE ALL ON SCHEMA onmyoji_shards FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA onmyoji_shards FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA onmyoji_shards FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA onmyoji_shards
    REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA onmyoji_shards
    REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMIT;
