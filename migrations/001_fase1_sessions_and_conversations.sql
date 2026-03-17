-- =============================================================================
-- FASE 1 — Migration: Sessions + Conversations unificadas
-- Data: 2026-03-16
-- Executar no Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- =============================================================================

-- 1. Tabela SESSIONS — agrupa mensagens de uma mesma conversa
-- Cada vez que um lead começa uma nova interação, um session_id UUID é gerado.
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    channel TEXT,                    -- 'whatsapp' | 'sandbox' | 'api' | 'botmaker'
    status TEXT DEFAULT 'active',    -- 'active' | 'escalated' | 'closed'
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Índice para buscar sessões por user_id
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

-- 2. Adicionar colunas novas na tabela CONVERSATIONS (se não existirem)
-- session_id: liga a mensagem a uma sessão específica
-- message_type: diferencia mensagens de conversa vs mensagens brutas pré-debounce
DO $$
BEGIN
    -- Adiciona session_id se não existir
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'session_id'
    ) THEN
        ALTER TABLE conversations ADD COLUMN session_id UUID;
    END IF;

    -- Adiciona message_type se não existir
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'message_type'
    ) THEN
        ALTER TABLE conversations ADD COLUMN message_type TEXT DEFAULT 'conversation';
    END IF;
END $$;

-- Índices para as novas colunas
CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_message_type ON conversations(message_type);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id_type ON conversations(user_id, message_type);

-- 3. FK de conversations.session_id → sessions.id (opcional, não bloqueia se sessions não existir)
-- Comentado por segurança — descomente se quiser enforce de integridade referencial.
-- ALTER TABLE conversations ADD CONSTRAINT fk_conversations_session
--     FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL;

-- 4. Marcar mensagens existentes como 'conversation' (preencher message_type para dados legados)
UPDATE conversations SET message_type = 'conversation' WHERE message_type IS NULL;

-- =============================================================================
-- VERIFICAÇÃO: Execute após a migration para confirmar que tudo está OK
-- =============================================================================
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'conversations';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'sessions';
-- SELECT count(*) FROM conversations WHERE message_type = 'conversation';
