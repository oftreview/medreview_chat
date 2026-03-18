"""
Backlog items — CRUD + analytics + JSON fallback.
Gerencia itens de backlog de produto com priorização RICE.
"""
import os
import json
import math
from datetime import datetime, timezone
from .client import _get_client


# ── JSON Fallback Helpers ──────────────────────────────────────────────────────


def _get_backlog_json_path() -> str:
    """Caminho padrão para o arquivo de backlog JSON (fallback)."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "backlog.json"
    )


def _load_backlog_json(path: str = None) -> list:
    """Carrega backlog do arquivo JSON local."""
    if path is None:
        path = _get_backlog_json_path()
    if not os.path.exists(path):
        return _get_seed_data()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or []
            return data if data else _get_seed_data()
    except Exception as e:
        print(f"[DB WARN] _load_backlog_json: {e}", flush=True)
        return _get_seed_data()


def _save_backlog_json(items: list, path: str = None) -> bool:
    """Salva backlog no arquivo JSON local."""
    if path is None:
        path = _get_backlog_json_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[DB WARN] _save_backlog_json: {e}", flush=True)
        return False


def _calc_rice(item: dict) -> float:
    """Calcula RICE score localmente."""
    r = item.get("reach", 100)
    i = item.get("impact", 1.0)
    c = item.get("confidence", 0.8)
    e = item.get("effort", 2.0)
    if e <= 0:
        return 0
    return round((r * i * c) / e, 1)


# ── CRUD Operations ───────────────────────────────────────────────────────────


def load_backlog(status: str = None, phase: str = None) -> list:
    """
    Carrega itens do backlog. Tenta Supabase, fallback para JSON.
    Retorna lista ordenada por rice_score DESC.
    """
    db = _get_client()
    if db is not None:
        try:
            query = db.table("backlog_items").select("*")
            if status:
                query = query.eq("status", status)
            if phase:
                query = query.eq("phase", phase)
            query = query.order("rice_score", desc=True)
            result = query.execute()
            if result.data:
                return result.data
        except Exception as e:
            print(f"[DB WARN] load_backlog: {e}", flush=True)

    # Fallback: JSON
    items = _load_backlog_json()
    for item in items:
        if "rice_score" not in item:
            item["rice_score"] = _calc_rice(item)
    if status:
        items = [i for i in items if i.get("status") == status]
    if phase:
        items = [i for i in items if i.get("phase") == phase]
    items.sort(key=lambda x: x.get("rice_score", 0), reverse=True)
    return items


def save_backlog_item(item: dict) -> bool:
    """
    Salva ou atualiza um item do backlog (upsert por item_id).
    Dual-write: Supabase + JSON.
    """
    item_id = item.get("item_id", "").strip()
    if not item_id:
        return False

    # Calcular RICE localmente (para JSON e para validação)
    item["rice_score"] = _calc_rice(item)
    item["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Supabase
    db = _get_client()
    db_ok = False
    if db is not None:
        try:
            row = {
                "item_id": item_id,
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "item_type": item.get("item_type", "feature"),
                "module": item.get("module", "core"),
                "status": item.get("status", "backlog"),
                "phase": item.get("phase", "Phase 2"),
                "reach": item.get("reach", 100),
                "impact": item.get("impact", 1.0),
                "confidence": item.get("confidence", 0.8),
                "effort": item.get("effort", 2.0),
                "estimate": item.get("estimate", ""),
                "dependencies": item.get("dependencies", ""),
                "notes": item.get("notes", ""),
                "sort_order": item.get("sort_order", 0),
            }
            db.table("backlog_items").upsert(row, on_conflict="item_id").execute()
            db_ok = True
        except Exception as e:
            print(f"[DB ERROR] save_backlog_item {item_id}: {e}", flush=True)

    # JSON dual-write
    items = _load_backlog_json()
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), None)
    if idx is not None:
        items[idx].update(item)
    else:
        items.append(item)
    _save_backlog_json(items)

    return db_ok


def delete_backlog_item(item_id: str) -> bool:
    """Remove um item do backlog por item_id."""
    db = _get_client()
    if db is not None:
        try:
            db.table("backlog_items").delete().eq("item_id", item_id).execute()
        except Exception as e:
            print(f"[DB WARN] delete_backlog_item: {e}", flush=True)

    # JSON
    items = _load_backlog_json()
    items = [i for i in items if i.get("item_id") != item_id]
    _save_backlog_json(items)
    return True


def get_next_item_id() -> str:
    """Gera próximo ID sequencial (CLO-XXX)."""
    items = load_backlog()
    max_num = 0
    for item in items:
        iid = item.get("item_id", "")
        if iid.startswith("CLO-"):
            try:
                num = int(iid.replace("CLO-", ""))
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"CLO-{max_num + 1:03d}"


def reorder_backlog(ordered_ids: list) -> bool:
    """Atualiza sort_order baseado na lista de IDs ordenada."""
    items = _load_backlog_json()
    id_to_order = {iid: idx for idx, iid in enumerate(ordered_ids)}
    for item in items:
        if item.get("item_id") in id_to_order:
            item["sort_order"] = id_to_order[item["item_id"]]
    _save_backlog_json(items)

    db = _get_client()
    if db is not None:
        try:
            for iid, order in id_to_order.items():
                db.table("backlog_items").update(
                    {"sort_order": order}
                ).eq("item_id", iid).execute()
        except Exception as e:
            print(f"[DB WARN] reorder_backlog: {e}", flush=True)
    return True


def backlog_analytics() -> dict:
    """Retorna resumo analítico do backlog."""
    items = load_backlog()
    total = len(items)

    by_status = {}
    by_phase = {}
    by_type = {}
    total_effort = 0

    for item in items:
        st = item.get("status", "backlog")
        ph = item.get("phase", "Phase 2")
        tp = item.get("item_type", "feature")
        by_status[st] = by_status.get(st, 0) + 1
        by_phase[ph] = by_phase.get(ph, 0) + 1
        by_type[tp] = by_type.get(tp, 0) + 1
        if st not in ("done", "cancelled"):
            total_effort += item.get("effort", 0)

    scores = [i.get("rice_score", 0) for i in items if i.get("status") not in ("done", "cancelled")]
    avg_rice = round(sum(scores) / len(scores), 1) if scores else 0

    blocked = [
        {"item_id": i["item_id"], "title": i.get("title", "")}
        for i in items if i.get("status") == "blocked"
    ]

    top5 = sorted(
        [i for i in items if i.get("status") not in ("done", "cancelled")],
        key=lambda x: x.get("rice_score", 0),
        reverse=True
    )[:5]

    return {
        "total": total,
        "by_status": by_status,
        "by_phase": by_phase,
        "by_type": by_type,
        "total_effort_weeks": round(total_effort, 1),
        "avg_rice_score": avg_rice,
        "blocked_items": blocked,
        "top5_rice": [
            {"item_id": i["item_id"], "title": i.get("title", ""), "rice_score": i.get("rice_score", 0)}
            for i in top5
        ],
    }


# ── Seed Data ─────────────────────────────────────────────────────────────────


def _get_seed_data() -> list:
    """Dados iniciais do backlog baseados na análise técnica do projeto."""
    seed = [
        {
            "item_id": "CLO-001", "title": "Follow-up Scheduler",
            "description": "Sistema de follow-up automático: 24h após primeiro contato, 3-5 dias sem resposta, 7-10 dias último contato. Precisa de background job (APScheduler ou Celery).",
            "item_type": "feat", "module": "core", "status": "backlog", "phase": "Phase 2",
            "reach": 500, "impact": 3.0, "confidence": 0.8, "effort": 5.0,
            "estimate": "2w", "dependencies": "", "notes": "Prompt já define regras de timing", "sort_order": 0,
        },
        {
            "item_id": "CLO-002", "title": "Webhook Hotmart (Pagamento)",
            "description": "Receber webhook de confirmação de pagamento da Hotmart. Ativar Stage 6 (pós-venda) automaticamente. Atualizar status do lead para converted.",
            "item_type": "feat", "module": "integrations", "status": "backlog", "phase": "Phase 2",
            "reach": 200, "impact": 3.0, "confidence": 0.8, "effort": 3.0,
            "estimate": "1w", "dependencies": "", "notes": "Sem isso não detectamos conversão real", "sort_order": 1,
        },
        {
            "item_id": "CLO-003", "title": "Persistir Estágio do Funil",
            "description": "Garantir que stage extraído via [META] seja persistido na tabela leads em toda transição. Crítico para analytics confiável.",
            "item_type": "fix", "module": "database", "status": "backlog", "phase": "Phase 2",
            "reach": 1000, "impact": 2.0, "confidence": 1.0, "effort": 2.0,
            "estimate": "3d", "dependencies": "", "notes": "Hoje extrai mas nem sempre salva", "sort_order": 2,
        },
        {
            "item_id": "CLO-004", "title": "Unificar Tabelas messages/conversations",
            "description": "Eliminar redundância entre tabelas. Migrar dados, atualizar queries em todos os módulos de database.",
            "item_type": "refactor", "module": "database", "status": "backlog", "phase": "Phase 2",
            "reach": 100, "impact": 1.0, "confidence": 0.8, "effort": 2.0,
            "estimate": "3d", "dependencies": "", "notes": "Criar migration SQL", "sort_order": 3,
        },
        {
            "item_id": "CLO-005", "title": "Dashboard Métricas de Conversão",
            "description": "Dashboard real-time: taxa de conversão por estágio, tempo médio por estágio, leads ativos vs perdidos, revenue estimado.",
            "item_type": "feat", "module": "dashboard", "status": "backlog", "phase": "Phase 2",
            "reach": 100, "impact": 2.0, "confidence": 0.8, "effort": 3.0,
            "estimate": "1w", "dependencies": "CLO-003", "notes": "Depende de CLO-003 para dados confiáveis", "sort_order": 4,
        },
        {
            "item_id": "CLO-006", "title": "HubSpot Events Completos",
            "description": "Enviar eventos para HubSpot em todas as transições de estágio. Timeline completa no CRM.",
            "item_type": "perf", "module": "integrations", "status": "backlog", "phase": "Phase 2",
            "reach": 50, "impact": 1.0, "confidence": 0.8, "effort": 2.0,
            "estimate": "2d", "dependencies": "", "notes": "", "sort_order": 5,
        },
        {
            "item_id": "CLO-007", "title": "Monitorar Memory Leak (Cache TTL)",
            "description": "TTL cleanup implementado mas precisa de monitoramento em produção. Verificar se sessions dict cresce indefinidamente.",
            "item_type": "fix", "module": "core", "status": "next", "phase": "Phase 2",
            "reach": 1000, "impact": 2.0, "confidence": 0.5, "effort": 1.0,
            "estimate": "1d", "dependencies": "", "notes": "Adicionar métricas de tamanho do cache", "sort_order": 6,
        },
        {
            "item_id": "CLO-008", "title": "Few-shot Examples no Prompt",
            "description": "Adicionar 3-5 exemplos de conversas reais bem-sucedidas ao system prompt. Usar dados reais anonimizados.",
            "item_type": "perf", "module": "agent", "status": "backlog", "phase": "Phase 2",
            "reach": 500, "impact": 2.0, "confidence": 0.5, "effort": 2.0,
            "estimate": "3d", "dependencies": "", "notes": "Medir impacto na qualidade das respostas", "sort_order": 7,
        },
        {
            "item_id": "CLO-009", "title": "A/B Testing de Prompts",
            "description": "Framework para testar variações de prompt. Distribuir leads entre variantes, medir conversão por variante.",
            "item_type": "feat", "module": "agent", "status": "backlog", "phase": "Phase 3",
            "reach": 500, "impact": 2.0, "confidence": 0.5, "effort": 5.0,
            "estimate": "2w", "dependencies": "CLO-003", "notes": "Precisa de infraestrutura de experimentação", "sort_order": 8,
        },
        {
            "item_id": "CLO-010", "title": "Seleção Dinâmica de Oferta",
            "description": "Agente escolhe oferta baseado no perfil do lead (orçamento, urgência, momento). Hoje segue hierarquia fixa.",
            "item_type": "feat", "module": "agent", "status": "backlog", "phase": "Phase 3",
            "reach": 500, "impact": 2.0, "confidence": 0.5, "effort": 3.0,
            "estimate": "1w", "dependencies": "", "notes": "Usar dados de commercial_rules.json como base", "sort_order": 9,
        },
        {
            "item_id": "CLO-011", "title": "Desconto Dinâmico (até 10%)",
            "description": "Agente pode oferecer desconto progressivo: 5% após 2ª objeção de preço, até 10% como última cartada.",
            "item_type": "feat", "module": "agent", "status": "backlog", "phase": "Phase 3",
            "reach": 200, "impact": 2.0, "confidence": 0.5, "effort": 2.0,
            "estimate": "3d", "dependencies": "", "notes": "Precisa de regras claras e logging", "sort_order": 10,
        },
        {
            "item_id": "CLO-012", "title": "Integração Botmaker (Transfer Direto)",
            "description": "Transferir conversa para atendente humano via Botmaker API quando escalar. Já tem config vars preparadas.",
            "item_type": "feat", "module": "integrations", "status": "backlog", "phase": "Phase 3",
            "reach": 100, "impact": 1.0, "confidence": 0.5, "effort": 3.0,
            "estimate": "1w", "dependencies": "", "notes": "BOTMAKER_API_KEY e BOTMAKER_TEAM_ID já existem no config", "sort_order": 11,
        },
        {
            "item_id": "CLO-013", "title": "Testes de Integração E2E",
            "description": "Testes end-to-end: simular lead completo (form → conversa → escalação → resolução). Usar fixtures.",
            "item_type": "refactor", "module": "devops", "status": "backlog", "phase": "Phase 3",
            "reach": 50, "impact": 2.0, "confidence": 0.8, "effort": 3.0,
            "estimate": "1w", "dependencies": "", "notes": "Rodar no CI", "sort_order": 12,
        },
        {
            "item_id": "CLO-014", "title": "Rate Limiting por Sessão",
            "description": "Adicionar rate limiting por sessão para evitar abuse de sessões múltiplas.",
            "item_type": "perf", "module": "core", "status": "backlog", "phase": "Phase 3",
            "reach": 200, "impact": 1.0, "confidence": 0.8, "effort": 1.0,
            "estimate": "1d", "dependencies": "", "notes": "Rate limiter atual é por user_id", "sort_order": 13,
        },
        {
            "item_id": "CLO-015", "title": "Multi-tenant (Outros Produtos)",
            "description": "Abstrair Closi AI para suportar múltiplos produtos/clientes além da MedReview. Tenant isolation.",
            "item_type": "feat", "module": "core", "status": "backlog", "phase": "Phase 4",
            "reach": 50, "impact": 3.0, "confidence": 0.5, "effort": 13.0,
            "estimate": "6w", "dependencies": "", "notes": "Visão de longo prazo", "sort_order": 14,
        },
        {
            "item_id": "CLO-016", "title": "Voice Messages (Áudio WhatsApp)",
            "description": "Receber e transcrever áudios de WhatsApp (Whisper API). Responder considerando contexto do áudio.",
            "item_type": "feat", "module": "integrations", "status": "backlog", "phase": "Phase 4",
            "reach": 200, "impact": 2.0, "confidence": 0.5, "effort": 8.0,
            "estimate": "3w", "dependencies": "", "notes": "Whisper API para transcrição", "sort_order": 15,
        },
        {
            "item_id": "CLO-017", "title": "Agente Autônomo de Desenvolvimento",
            "description": "V2: agentes de IA consultam este backlog para pegar tasks e construir features 24/7 autonomamente.",
            "item_type": "research", "module": "devops", "status": "backlog", "phase": "Phase 4",
            "reach": 10, "impact": 3.0, "confidence": 0.5, "effort": 8.0,
            "estimate": "4w", "dependencies": "", "notes": "Requer formato machine-readable + guardrails", "sort_order": 16,
        },
    ]
    # Calcular RICE para cada
    for item in seed:
        item["rice_score"] = _calc_rice(item)
    return seed


def seed_backlog_if_empty() -> bool:
    """Popula backlog com dados iniciais se estiver vazio."""
    items = load_backlog()
    if items:
        return False

    seed = _get_seed_data()
    for item in seed:
        save_backlog_item(item)

    print(f"[DB] Backlog seeded with {len(seed)} items", flush=True)
    return True
