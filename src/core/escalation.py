"""
Módulo de escalação para atendimento humano — FASE 2 (dados ricos).

Fluxo:
  1. IA detecta gatilho de escalação (tag [ESCALAR] ou fallback)
  2. Gera brief completo (dados do lead + resumo da conversa)
  3. Salva escalação no banco (tabela escalations)
  4. Marca sessão como "escalated"
  5. Envia notificação rica para supervisor via WhatsApp (Z-API)
  6. IA para de responder aquela sessão
  7. Humano atende e chama /escalation/resolve para devolver controle à IA
"""

import os
from src.core import database
from src.config import SUPERVISOR_PHONE, BOTMAKER_API_KEY, BOTMAKER_TEAM_ID
from src.core.wild_memory_lifecycle import lifecycle as _wild_lifecycle


# ── Formatação do brief para WhatsApp ─────────────────────────────────────────

def _format_brief_whatsapp(brief: dict, lead_phone: str) -> str:
    """
    Formata o brief de escalação em mensagem WhatsApp legível para o vendedor.
    Inclui dados do lead, estágio do funil e resumo da conversa.
    """
    ld = brief.get("lead_data", {})

    # Monta bloco de dados do lead (só inclui o que foi coletado)
    dados_lines = []
    if ld.get("especialidade"):
        dados_lines.append(f"  Especialidade: {ld['especialidade']}")
    if ld.get("prova"):
        dados_lines.append(f"  Prova-alvo: {ld['prova']}")
    if ld.get("ano_prova"):
        dados_lines.append(f"  Ano da prova: {ld['ano_prova']}")
    if ld.get("ja_estuda"):
        dados_lines.append(f"  Já estuda: {ld['ja_estuda']}")
    if ld.get("plataforma_atual"):
        dados_lines.append(f"  Plataforma atual: {ld['plataforma_atual']}")

    dados_block = "\n".join(dados_lines) if dados_lines else "  (nenhum dado coletado ainda)"

    stage = ld.get("stage", "desconhecido")
    motivo = ld.get("motivo_escalacao", "nao_especificado")
    total = brief.get("total_messages", 0)
    summary = brief.get("summary", "(sem resumo)")

    msg = (
        f"🔴 *ESCALAÇÃO — Lead aguardando atendimento*\n\n"
        f"📞 Telefone: {lead_phone}\n"
        f"📊 Estágio: {stage}\n"
        f"❗ Motivo: {motivo}\n\n"
        f"📋 *Dados coletados:*\n{dados_block}\n\n"
        f"💬 *Resumo ({total} msgs):*\n{summary}\n\n"
        f"_Para devolver à IA:_\n"
        f"POST /escalation/resolve {{\"phone\": \"{lead_phone}\"}}"
    )
    return msg


# ── Notificação via WhatsApp (Z-API) ─────────────────────────────────────────

def notify_supervisor(lead_phone: str, brief: dict) -> bool:
    """
    Avisa o supervisor via WhatsApp com brief rico do lead.
    """
    if not SUPERVISOR_PHONE:
        print("[ESCALATION] SUPERVISOR_PHONE não configurado — notificação ignorada.", flush=True)
        return False

    from src.core.whatsapp import send_message

    msg = _format_brief_whatsapp(brief, lead_phone)
    ok = send_message(SUPERVISOR_PHONE, msg)
    print(f"[ESCALATION] Supervisor notificado: {ok}", flush=True)
    return ok


# ── Integração futura: Botmaker ───────────────────────────────────────────────

def transfer_to_botmaker(lead_phone: str, lead_name: str = "Lead") -> bool:
    """
    [FUTURO] Transfere a conversa para um agente humano no Botmaker.
    Requer BOTMAKER_API_KEY e BOTMAKER_TEAM_ID configurados.
    """
    if not BOTMAKER_API_KEY:
        print("[ESCALATION] BOTMAKER_API_KEY não configurado — transfer ignorado.", flush=True)
        return False

    print("[ESCALATION] Botmaker configurado mas transfer ainda não implementado.", flush=True)
    return False


# ── Handler principal (FASE 2 — com brief rico) ──────────────────────────────

def handle_escalation(lead_phone: str, agent_memory, lead_name: str = "Lead",
                      agent=None, motivo: str = "nao_especificado") -> None:
    """
    Executa o fluxo completo de escalação com dados ricos:
      1. Gera brief completo (se agent disponível)
      2. Salva escalação no banco (tabela escalations)
      3. Marca sessão como 'escalated'
      4. Envia brief rico ao supervisor via WhatsApp
    """
    print(f"[ESCALATION] Iniciando escalação para {lead_phone} motivo={motivo}", flush=True)

    # 1. Gera brief completo
    if agent is not None:
        brief = agent.get_escalation_brief(lead_phone)
    else:
        # Fallback: brief básico sem dados estruturados
        summary = agent_memory.summary(lead_phone) or "(sem histórico)"
        brief = {
            "session_id": lead_phone,
            "lead_data": {"motivo_escalacao": motivo},
            "total_messages": len(agent_memory.get(lead_phone)),
            "summary": summary,
        }

    # Injeta motivo no brief se ainda não estiver
    if "lead_data" in brief and not brief["lead_data"].get("motivo_escalacao"):
        brief["lead_data"]["motivo_escalacao"] = motivo

    # 2. Salva escalação no banco
    session_id = agent_memory.get_session_id(lead_phone) if hasattr(agent_memory, 'get_session_id') else None
    saved = database.save_escalation(
        user_id=lead_phone,
        motivo=motivo,
        brief=brief,
        session_id=session_id,
    )
    if not saved:
        print(f"[ESCALATION WARN] Escalação não persistida no DB para {lead_phone[:8]}...", flush=True)

    # 3. Marca sessão como escalated
    agent_memory.set_status(lead_phone, "escalated")

    # 4. Notifica supervisor com brief rico
    notify_supervisor(lead_phone, brief)

    # 5. Sync escalação para HubSpot (se habilitado)
    try:
        from src.core import hubspot
        if hubspot.is_enabled():
            hubspot.sync_escalation(lead_phone, brief)
    except Exception as e:
        print(f"[ESCALATION HUBSPOT WARN] Sync falhou: {e}", flush=True)

    # 6. Wild Memory: registra feedback signal + distilação completa (Fase 4)
    _wild_lifecycle.on_escalation(
        session_id=session_id or lead_phone,
        user_id=lead_phone,
        metadata=brief.get("lead_data", {}),
    )


def resolve_escalation(lead_phone: str, agent_memory, resolution: str = None) -> None:
    """
    Retorna o controle da conversa para a IA após o atendimento humano.
    Registra a resolução no banco.
    """
    agent_memory.set_status(lead_phone, "active")
    database.update_lead_status(lead_phone, "active")
    database.resolve_escalation_record(lead_phone, resolution)
    print(f"[ESCALATION] Sessão {lead_phone[:8]}... retornada para IA. Resolução: {resolution}", flush=True)


def is_escalated(lead_phone: str, agent_memory) -> bool:
    """Retorna True se a sessão está aguardando atendimento humano."""
    return agent_memory.get_status(lead_phone) == "escalated"
