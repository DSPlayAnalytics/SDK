-- Schema SQLite para autenticacao multi-tenant do SDK de analytics.
-- Simplificado em relacao ao plano-clientes-ambientes.md:
--   * nao persistimos sdk_jwt (stateless via RS256)
--   * nao persistimos access/refresh do fluxo REST de consulta (essa frente ainda nao existe)
--   * sites e publishable_keys cobrem o fluxo de ingestao SDK -> backend.

CREATE TABLE IF NOT EXISTS sites (
    id              TEXT PRIMARY KEY,                -- uuid
    slug            TEXT NOT NULL UNIQUE,            -- identificador humano (ex.: "acme")
    nome            TEXT NOT NULL,
    ambiente        TEXT NOT NULL CHECK (ambiente IN ('development','test','staging','production')),
    plano           TEXT NOT NULL DEFAULT 'free',
    status          TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','suspenso','bloqueado')),
    bucket_name     TEXT UNIQUE,                     -- bucket Influx dedicado (null = legacy/compat)
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dominios permitidos por site; validacao do header Origin acontece aqui.
CREATE TABLE IF NOT EXISTS site_dominios (
    site_id         TEXT NOT NULL,
    dominio         TEXT NOT NULL,                   -- ex.: "https://cliente.com" (scheme + host, sem path)
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (site_id, dominio),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_site_dominios_dominio ON site_dominios(dominio);

-- Chaves publicas embarcadas no SDK. Varias por site sao permitidas (para rotacao suave).
CREATE TABLE IF NOT EXISTS publishable_keys (
    key_id          TEXT PRIMARY KEY,                -- uuid curto que aparece no valor da key
    site_id         TEXT NOT NULL,
    valor           TEXT NOT NULL UNIQUE,            -- string completa "pk_<ambiente>_<token>"
    nome            TEXT,                            -- label livre (ex.: "producao-principal")
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    revogado_em     TEXT,                            -- null = ativa
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_publishable_keys_site ON publishable_keys(site_id);

-- Quotas por site. Uma linha por site; valores nulos usam default do plano.
CREATE TABLE IF NOT EXISTS quotas (
    site_id                 TEXT PRIMARY KEY,
    eventos_por_minuto      INTEGER NOT NULL DEFAULT 600,
    eventos_por_dia         INTEGER NOT NULL DEFAULT 100000,
    emissoes_jwt_por_minuto INTEGER NOT NULL DEFAULT 5,
    retencao_dias           INTEGER NOT NULL DEFAULT 30,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

-- Log de emissoes de sdk_jwt para rate limit e auditoria.
-- Mantemos apenas a janela relevante; expurgo periodico via tenant_admin.py cleanup.
CREATE TABLE IF NOT EXISTS emissoes_jwt (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         TEXT NOT NULL,
    publishable_id  TEXT NOT NULL,
    origin          TEXT,
    ip              TEXT,
    jti             TEXT NOT NULL,
    emitido_em      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (publishable_id) REFERENCES publishable_keys(key_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_emissoes_site_tempo ON emissoes_jwt(site_id, emitido_em);

-- Contagem de eventos ingeridos por site/dia para controle de quota diaria.
-- Atualizada pela camada de ingestao quando a Onda 1 integrar com auth.
CREATE TABLE IF NOT EXISTS consumo_diario (
    site_id         TEXT NOT NULL,
    dia             TEXT NOT NULL,                   -- "YYYY-MM-DD"
    eventos         INTEGER NOT NULL DEFAULT 0,
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (site_id, dia),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

-- Eventos Stripe ja processados — chave de idempotencia.
-- Stripe re-entrega webhooks em retries (timeout, 5xx); sem essa tabela,
-- aplicar_plano() rodaria N vezes pro mesmo evento, podendo bagunçar
-- estado de assinatura. INSERT ON CONFLICT DO NOTHING e o gate.
CREATE TABLE IF NOT EXISTS stripe_eventos_processados (
    event_id        TEXT PRIMARY KEY,
    processado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- JWT embed revogados — defesa contra leak/cancelamento antes de exp.
-- TTL curto (60-600s) ja limita janela; tabela cobre revogacao explicita.
-- Limpeza periodica via expurgo (>24h apos exp).
CREATE TABLE IF NOT EXISTS embed_jwt_revogados (
    jti             TEXT PRIMARY KEY,
    motivo          TEXT,
    revogado_em     TEXT NOT NULL DEFAULT (datetime('now'))
);
