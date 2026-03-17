-- =============================================================================
-- FASE 2 — Migration: Lead Metadata + Escalations (dados ricos para vendedores)
-- Data: 2026-03-16
-- Executar no Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- =============================================================================

-- 1. Tabela LEAD_METADATA — dados estruturados coletados pela IA durante a conversa
-- Cada lead (user_id) tem uma única linha que é atualizada conforme a IA coleta dados.
CREATE TABLE IF NOT EXISTS lead_metadata (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    funnel_stage TEXT DEFAULT 'desconhecido',   -- abertura, qualificacao, diagnostico, etc.
    especialidade TEXT,                          -- ex: cardiologia, ortopedia
    prova_alvo TEXT,                             -- ex: USP, UNIFESP, ENARE
    ano_prova TEXT,                              -- ex: 2026, 2027
    ja_estuda TEXT,                              -- sim, nao, parcialmente
    plataforma_atual TEXT,                       -- ex: Medcel, Sanar, nenhuma
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Índices para busca rápida
CREATE INDEX IF NOT EXISTS idx_lead_metadata_user_id ON lead_metadata(user_id);
CREATE INDEX IF NOT EXISTS idx_lead_metadata_funnel_stage ON lead_metadata(funnel_stage);

-- 2. Tabela ESCALATIONS — registro de todas as escalações para atendimento humano
-- Cada escalação gera uma linha com o motivo, brief completo e status de resolução.
CREATE TABLE IF NOT EXISTS escalations (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id UUID,                             -- referência à sessão (se disponível)
    motivo TEXT NOT NULL DEFAULT 'nao_especificado',  -- desconto_acima_5pct, credito_recorrente, etc.
    brief JSONB,                                 -- brief completo: lead_data + resumo da conversa
    status TEXT DEFAULT 'pending',               -- pending | resolved
    resolution TEXT,                             -- texto livre: como foi resolvido
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Índices para consultas comuns
CREATE INDEX IF NOT EXISTS idx_escalations_user_id ON escalations(user_id);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
CREATE INDEX IF NOT EXISTS idx_escalations_created_at ON escalations(created_at DESC);

-- 3. Trigger para atualizar updated_at automaticamente na lead_metadata
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_lead_metadata_updated_at ON lead_metadata;
CREATE TRIGGER trigger_lead_metadata_updated_at
    BEFORE UPDATE ON lead_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- VERIFICAÇÃO: Execute após a migration para confirmar que tudo está OK
-- =============================================================================
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'lead_metadata';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'escalations';
