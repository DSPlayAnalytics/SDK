-- Migração 003 — 2FA TOTP para clientes_users
-- Aplicar manualmente em prod: psql $DATABASE_URL -f migrations/003_add_totp.sql

ALTER TABLE clientes_users ADD COLUMN IF NOT EXISTS totp_habilitado BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE clientes_users ADD COLUMN IF NOT EXISTS totp_secret TEXT;
