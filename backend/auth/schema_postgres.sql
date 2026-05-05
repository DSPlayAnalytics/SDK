-- Schema Postgres do banco de autenticacao multi-tenant.
-- Equivalente ao backend/auth/schema.sql (SQLite), com:
--   * uuid no lugar de text para `id`
--   * timestamptz no lugar de datetime
--   * ON CONFLICT ao inves de INSERT OR IGNORE
-- A interface publica de TenantsRepo e a mesma para ambos.

CREATE TABLE IF NOT EXISTS sites (
    id              UUID PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    nome            TEXT NOT NULL,
    ambiente        TEXT NOT NULL CHECK (ambiente IN ('development','test','staging','production')),
    plano           TEXT NOT NULL DEFAULT 'free',
    status          TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','suspenso','bloqueado')),
    bucket_name     TEXT UNIQUE,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migracao idempotente para DBs criados antes do bucket-per-cliente.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS bucket_name TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'sites_bucket_name_key'
    ) THEN
        CREATE UNIQUE INDEX sites_bucket_name_key ON sites(bucket_name)
            WHERE bucket_name IS NOT NULL;
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS site_dominios (
    site_id         UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    dominio         TEXT NOT NULL,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (site_id, dominio)
);

CREATE INDEX IF NOT EXISTS idx_site_dominios_dominio ON site_dominios(dominio);

CREATE TABLE IF NOT EXISTS publishable_keys (
    key_id          TEXT PRIMARY KEY,
    site_id         UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    valor           TEXT NOT NULL UNIQUE,
    nome            TEXT,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revogado_em     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_publishable_keys_site ON publishable_keys(site_id);

CREATE TABLE IF NOT EXISTS quotas (
    site_id                 UUID PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE,
    eventos_por_minuto      INTEGER NOT NULL DEFAULT 600,
    eventos_por_dia         INTEGER NOT NULL DEFAULT 100000,
    emissoes_jwt_por_minuto INTEGER NOT NULL DEFAULT 5,
    retencao_dias           INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS emissoes_jwt (
    id              BIGSERIAL PRIMARY KEY,
    site_id         UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    publishable_id  TEXT NOT NULL REFERENCES publishable_keys(key_id) ON DELETE CASCADE,
    origin          TEXT,
    ip              TEXT,
    jti             TEXT NOT NULL,
    emitido_em      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emissoes_site_tempo ON emissoes_jwt(site_id, emitido_em);

CREATE TABLE IF NOT EXISTS consumo_diario (
    site_id         UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    dia             DATE NOT NULL,
    eventos         BIGINT NOT NULL DEFAULT 0,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (site_id, dia)
);

-- Idempotencia de webhooks Stripe — evita aplicar a mesma mudanca de plano
-- N vezes quando Stripe retenta entregar (timeout/5xx).
CREATE TABLE IF NOT EXISTS stripe_eventos_processados (
    event_id        TEXT PRIMARY KEY,
    processado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- JWT embed revogados — TTL curto ja limita janela, mas cobre leak/banimento.
CREATE TABLE IF NOT EXISTS embed_jwt_revogados (
    jti             TEXT PRIMARY KEY,
    motivo          TEXT,
    revogado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
