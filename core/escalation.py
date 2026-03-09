"""
Módulo de escalação para atendimento humano.

Fluxo atual:
  1. IA detecta gatilho de escalação
  2. Marca sessão como "escalated" no Supabase
  3. Envia notificação para supervisor via WhatsApp (Z-API)
  4. IA para de responder aquela sessão
  5. Humano atende via canal preferido (Botmaker, WhatsApp direto, etc.)
  6. Após atendimento, humano chama /escalation/resolve para devolver controle à IA

Futuro — Botmaker:
  - Substituir notify_supervisor() por transfer_to_botmaker()
  - Requer: BOTMAKER_API_KEY + documentação da API de transferência
"""

import os
from dotenv import load_dotenv
from core import database

load_dotenv()

SUPERVISOR_PHONE = os.getenv("SUPERVISOR_PHONE", "")      # Ex: 5531999990000
BOTMAKER_API_KEY = os.getenv("BOTMAKER_API_KEY", "")      # Futuro: API Botmaker
BOTMAKER_TEAM_ID = os.getenv("BOTMAKER_TEAM_ID", "")      # Futuro: ID do time no Botmaker


# ── Notificação atual (WhatsApp via Z-API) ─────────────────────────────────────

def notify_supervisor(lead_phone: str, lead_name: str, summary: str) -> bool:
    """
    Avisa o supervisor humano via WhatsApp que um lead precisa de atendimento.
    Usa Z-API (mesmo canal do agente) para enviar a notificação.
    """
    if not SUPERVISOR_PHONE:
        print("[ESCALATION] SUPERVISOR_PHONE não configurado — notificação ignorada.", flush=True)
        return False

    from core.whatsapp import send_message

    msg = (
        f"🔴 *Lead aguardando atendimento humano*\n\n"
        f"Nome: {lead_name}\n"
        f"Telefone: {lead_phone}\n\n"
        f"Resumo da conversa:\n{summary}\n\n"
        f"Para devolver para a IA após atendimento:\n"
        f"POST /escalation/resolve {{\"phone\": \"{lead_phone}\"}}"
    )

    ok = send_message(SUPERVISOR_PHONE, msg)
    print(f"[ESCALATION] Supervisor {SUPERVISOR_PHONE} notificado: {ok}", flush=True)
    return ok


# ── Integração futura: Botmaker ────────────────────────────────────────────────

def transfer_to_botmaker(lead_phone: str, lead_name: str) -> bool:
    """
    [FUTURO] Transfere a conversa para um agente humano no Botmaker.

    Para ativar:
      1. Defina BOTMAKER_API_KEY e BOTMAKER_TEAM_ID nas variáveis de ambiente
      2. Consulte a documentação da API Botmaker para o endpoint correto
      3. Descomente e ajuste o bloco abaixo

    Documentação Botmaker: https://developers.botmaker.com
    """
    if not BOTMAKER_API_KEY:
        print("[ESCALATION] BOTMAKER_API_KEY não configurado — transfer Botmaker ignorado.", flush=True)
        return False

    # TODO: descomentar e ajustar quando tiver a documentação da API
    #
    # import httpx
    # url = "https://api.botmaker.com/v2.0/conversations/transfer"
    # headers = {
    #     "access-token": BOTMAKER_API_KEY,
    #     "Content-Type": "application/json",
    # }
    # payload = {
    #     "phone": lead_phone,
    #     "teamId": BOTMAKER_TEAM_ID,
    #     # "agentId": "...",  # opcional: agente específico
    # }
    # try:
    #     r = httpx.post(url, json=payload, headers=headers, timeout=10)
    #     r.raise_for_status()
    #     print(f"[ESCALATION] Botmaker transfer OK para {lead_phone}", flush=True)
    #     return True
    # except Exception as e:
    #     print(f"[ESCALATION] Erro Botmaker transfer: {e}", flush=True)
    #     return False

    print("[ESCALATION] Botmaker configurado mas transfer ainda não implementado.", flush=True)
    return False


# ── Handler principal ──────────────────────────────────────────────────────────

def handle_escalation(lead_phone: str, agent_memory, lead_name: str = "Lead") -> None:
    """
    Executa o fluxo completo de escalação:
      1. Marca sessão como 'escalated' no Supabase
      2. Envia resumo ao supervisor via WhatsApp
      3. (Futuro) Transfere para Botmaker
    """
    print(f"[ESCALATION] Iniciando escalação para {lead_phone}", flush=True)

    # 1. Atualiza status — IA para de responder essa sessão
    agent_memory.set_status(lead_phone, "escalated")

    # 2. Monta resumo para o supervisor
    summary = agent_memory.summary(lead_phone) or "(sem histórico disponível)"

    # 3. Notifica supervisor (canal atual)
    notify_supervisor(lead_phone, lead_name, summary)

    # 4. (Futuro) Transfere para Botmaker — descomente quando integrado
    # transfer_to_botmaker(lead_phone, lead_name)


def resolve_escalation(lead_phone: str, agent_memory) -> None:
    """
    Retorna o controle da conversa para a IA após o atendimento humano.
    Chamado via POST /escalation/resolve.
    """
    agent_memory.set_status(lead_phone, "active")
    database.update_lead_status(lead_phone, "active")
    print(f"[ESCALATION] Sessão {lead_phone} retornada para IA.", flush=True)


def is_escalated(lead_phone: str, agent_memory) -> bool:
    """Retorna True se a sessão está aguardando atendimento humano."""
    return agent_memory.get_status(lead_phone) == "escalated"
