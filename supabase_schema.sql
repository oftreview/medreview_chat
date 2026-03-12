-- ============================================================
-- Criatons — Schema Supabase
-- Execute no SQL Editor do Supabase (supabase.com → SQL Editor)
-- ============================================================

-- Tabela de leads (um registro por número de telefone)
CREATE TABLE IF NOT EXISTS leads (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    phone       TEXT        NOT NULL UNIQUE,
    name        TEXT,
    source      TEXT        DEFAULT 'form',
    status      TEXT        DEFAULT 'active',   -- active | escalated | closed
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Tabela de mensagens (histórico completo de todas as conversas)
CREATE TABLE IF NOT EXISTS messages (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    phone       TEXT        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para buscas rápidas por telefone
CREATE INDEX IF NOT EXISTS idx_messages_phone         ON messages(phone);
CREATE INDEX IF NOT EXISTS idx_messages_phone_created ON messages(phone, created_at);

-- Função que atualiza updated_at automaticamente na tabela leads
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Tabela conversations (unificada para todos os canais)
-- Usada pelo endpoint POST /chat (Botmaker, webchat, etc.)
-- user_id pode ser: número de telefone, UUID do webchat, etc.
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     TEXT        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT        NOT NULL,
    channel     TEXT,                              -- botmaker | webchat | whatsapp | api
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para buscas rápidas por user_id
CREATE INDEX IF NOT EXISTS idx_conversations_user_id         ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id_created ON conversations(user_id, created_at);
