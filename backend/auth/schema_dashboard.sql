-- Equivalente SQLite de schema_dashboard_postgres.sql.
-- Usado em testes e dev local. Interface do repo e a mesma.

CREATE TABLE IF NOT EXISTS clientes_users (
    id              TEXT PRIMARY KEY,
    site_id         TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    senha_hash      TEXT,
    papel           TEXT NOT NULL DEFAULT 'viewer' CHECK (papel IN ('admin','viewer')),
    ativo           INTEGER NOT NULL DEFAULT 1,
    ultimo_login    TEXT,
    criado_em       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_users_email ON clientes_users(email COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_clientes_users_site ON clientes_users(site_id);

CREATE TABLE IF NOT EXISTS clientes_users_sessoes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES clientes_users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    ip              TEXT,
    user_agent      TEXT,
    expira_em       TEXT NOT NULL,
    revogada_em     TEXT,
    criada_em       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clientes_sessoes_user ON clientes_users_sessoes(user_id);

-- tipo: 'login' (legado, entra direto) ou 'reset' (consumir nao cria sessao,
-- redireciona pra form de nova senha). Default 'login' por compat.
CREATE TABLE IF NOT EXISTS clientes_magic_links (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES clientes_users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    expira_em       TEXT NOT NULL,
    consumido_em    TEXT,
    ip_solicitacao  TEXT,
    tipo            TEXT NOT NULL DEFAULT 'login' CHECK (tipo IN ('login','reset')),
    criada_em       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clientes_magic_user ON clientes_magic_links(user_id);
