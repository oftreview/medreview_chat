-- =============================================================================
-- FASE 4 — Migration: Corrections (aprendizado contínuo)
-- Data: 2026-03-16
-- Executar no Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- =============================================================================

-- Tabela CORRECTIONS — correções de erros do agente (fonte de verdade)
-- O JSON local (data/corrections.json) continua como cache para performance.
CREATE TABLE IF NOT EXISTS corrections (
    id BIGSERIAL PRIMARY KEY,
    correction_id TEXT NOT NULL UNIQUE,          -- ex: COR-001, COR-002
    categoria TEXT DEFAULT 'outro',              -- alucinacao, tom_inadequado, link_errado, etc.
    severidade TEXT DEFAULT 'alta',              -- critica, alta, media, baixa
    gatilho TEXT,                                -- o que o lead disse que causou o erro
    resposta_errada TEXT,                        -- o que o agente fez de errado
    resposta_correta TEXT,                       -- o que deveria ter feito
    regra TEXT,                                  -- a lição aprendida
    status TEXT DEFAULT 'ativa',                 -- ativa, arquivada, exemplo
    reincidencia BOOLEAN DEFAULT false,          -- se já aconteceu mais de uma vez
    reincidencia_count INTEGER DEFAULT 0,        -- quantas vezes reincidiu
    last_reincidence_at TIMESTAMPTZ,             -- última reincidência
    conversation_user_id TEXT,                   -- link: telefone do lead da conversa original
    conversation_message_id BIGINT,              -- link: ID da mensagem na tabela conversations
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Índices para consultas comuns
CREATE INDEX IF NOT EXISTS idx_corrections_status ON corrections(status);
CREATE INDEX IF NOT EXISTS idx_corrections_categoria ON corrections(categoria);
CREATE INDEX IF NOT EXISTS idx_corrections_severidade ON corrections(severidade);
CREATE INDEX IF NOT EXISTS idx_corrections_reincidencia ON corrections(reincidencia) WHERE reincidencia = true;

-- Trigger para atualizar updated_at automaticamente
-- (usa a mesma function criada na migration 002)
DROP TRIGGER IF EXISTS trigger_corrections_updated_at ON corrections;
CREATE TRIGGER trigger_corrections_updated_at
    BEFORE UPDATE ON corrections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
