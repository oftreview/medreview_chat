-- =============================================================================
-- FASE 5 — Migration: Índices para Analytics Avançado
-- Data: 2026-03-16
-- Executar no Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- =============================================================================

-- Índices para acelerar queries de analytics
-- (as tabelas já existem das migrations anteriores)

-- Conversations: busca por role + message_type (usado no keywords e quality)
CREATE INDEX IF NOT EXISTS idx_conversations_role_type
    ON conversations(role, message_type);

-- Conversations: busca por user_id + message_type (usado no quality por lead)
CREATE INDEX IF NOT EXISTS idx_conversations_user_type
    ON conversations(user_id, message_type);

-- Conversations: ordenação por data (usado em todas as queries de analytics)
CREATE INDEX IF NOT EXISTS idx_conversations_created_at
    ON conversations(created_at DESC);

-- Lead metadata: busca por funnel_stage (usado no funil)
-- (já criado na migration 002, mas garante que existe)
CREATE INDEX IF NOT EXISTS idx_lead_metadata_funnel_stage
    ON lead_metadata(funnel_stage);
