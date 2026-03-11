"""
core/followup.py — Gerenciamento de follow-up e estado pós-conversa.

Controla o ciclo de vida completo de um lead após o primeiro contato:
  - Agenda follow-ups (d3, d7, d14) para leads que não responderam
  - Agenda CSAT (48h) para compradores
  - Marca estado da conversa (purchased, cold, rejected, etc.)
  - Expõe funções para o endpoint /followup/* e para o worker externo

Tabela Supabase: followups
  id, phone, trigger_event, scheduled_at, status, csat_score, metadata
"""

import json
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from core import database
from core.whatsapp import send_message
from core.logger import log_security_event

# ── Constantes ────────────────────────────────────────────────────────────────

FOLLOWUP_DELAYS = {
    "cold_d3":  timedelta(days=3),
    "cold_d7":  timedelta(days=7),
    "cold_d14": timedelta(days=14),
    "csat_48h": timedelta(hours=48),
}

FOLLOWUP_SEQUENCE = ["cold_d3", "cold_d7", "cold_d14"]

# Horário permitido para envio (horário local aproximado via UTC-3 Brasil)
SEND_HOUR_MIN = 9    # 09:00
SEND_HOUR_MAX = 20   # 20:00


# ── Helpers de banco de dados ─────────────────────────────────────────────────

def _db():
    """Retorna cliente Supabase. None se não configurado."""
    if not database.is_enabled():
        return None
    from supabase import create_client
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _brazil_hour(dt: datetime) -> int:
    """Retorna hora no fuso de Brasília (UTC-3)."""
    return (dt.hour - 3) % 24


# ── Agendamento ───────────────────────────────────────────────────────────────

def schedule_followup(
    phone: str,
    trigger: str,
    delay: Optional[timedelta] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """
    Agenda um follow-up para o lead.

    Args:
        phone:    número do lead (com DDI, ex: "5511999999999")
        trigger:  tipo de follow-up ("cold_d3", "cold_d7", "cold_d14", "csat_48h")
        delay:    override do atraso padrão (opcional)
        metadata: dados extras (ex: nome, especialidade, nota_csat)

    Returns:
        True se agendado com sucesso, False se Supabase não disponível.
    """
    db = _db()
    if not db:
        print(f"[FOLLOWUP] Supabase não configurado — follow-up {trigger} para {phone} não agendado.", flush=True)
        return False

    actual_delay = delay or FOLLOWUP_DELAYS.get(trigger, timedelta(days=3))
    scheduled_at = _now_utc() + actual_delay

    try:
        db.table("followups").insert({
            "phone":        phone,
            "trigger_event": trigger,
            "scheduled_at": scheduled_at.isoformat(),
            "status":       "pending",
            "metadata":     json.dumps(metadata or {}),
        }).execute()
        print(f"[FOLLOWUP] Agendado: {trigger} para {phone} em {scheduled_at.strftime('%d/%m %H:%M UTC')}", flush=True)
        return True
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao agendar {trigger} para {phone}: {e}", flush=True)
        return False


def schedule_cold_sequence(phone: str, name: str = "", specialty: str = "", prova: str = "") -> bool:
    """
    Agenda a sequência completa de re-engajamento para um lead frio.
    Agenda cold_d3, cold_d7 e cold_d14 de uma vez.
    """
    metadata = {"name": name, "specialty": specialty, "prova": prova}
    ok = True
    for trigger in FOLLOWUP_SEQUENCE:
        ok = ok and schedule_followup(phone, trigger, metadata=metadata)
    return ok


def schedule_csat(phone: str, name: str = "", specialty: str = "") -> bool:
    """
    Agenda CSAT para 48h após a compra.
    """
    metadata = {"name": name, "specialty": specialty, "type": "csat"}
    return schedule_followup(phone, "csat_48h", metadata=metadata)


def cancel_pending_followups(phone: str) -> bool:
    """
    Cancela todos os follow-ups pendentes de um lead.
    Use quando o lead responder (reiniciar o ciclo) ou comprar (cancelar cold).
    """
    db = _db()
    if not db:
        return False
    try:
        db.table("followups") \
            .update({"status": "cancelled"}) \
            .eq("phone", phone) \
            .eq("status", "pending") \
            .execute()
        print(f"[FOLLOWUP] Follow-ups cancelados para {phone}", flush=True)
        return True
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao cancelar follow-ups de {phone}: {e}", flush=True)
        return False


# ── Consulta de pendentes ─────────────────────────────────────────────────────

def get_pending_followups(limit: int = 50) -> list[dict]:
    """
    Retorna follow-ups que já passaram do horário agendado e ainda estão pendentes.
    Filtra pelo horário permitido de envio (9h-20h Brasília).

    Use em um worker/cron que roda a cada 15-30 minutos.
    """
    db = _db()
    if not db:
        return []

    now = _now_utc()
    brazil_hour = _brazil_hour(now)

    # Fora do horário permitido — não envia
    if not (SEND_HOUR_MIN <= brazil_hour < SEND_HOUR_MAX):
        print(f"[FOLLOWUP] Fora do horário de envio ({brazil_hour}h Brasília) — pulando.", flush=True)
        return []

    try:
        result = db.table("followups") \
            .select("*") \
            .eq("status", "pending") \
            .lte("scheduled_at", now.isoformat()) \
            .limit(limit) \
            .execute()
        return result.data or []
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao buscar pendentes: {e}", flush=True)
        return []


def mark_sent(followup_id: str) -> bool:
    """Marca um follow-up como enviado."""
    db = _db()
    if not db:
        return False
    try:
        db.table("followups") \
            .update({"status": "sent", "sent_at": _now_utc().isoformat()}) \
            .eq("id", followup_id) \
            .execute()
        return True
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao marcar enviado {followup_id}: {e}", flush=True)
        return False


def mark_responded(phone: str) -> bool:
    """Marca o follow-up mais recente como respondido quando o lead voltar a falar."""
    db = _db()
    if not db:
        return False
    try:
        db.table("followups") \
            .update({"status": "responded"}) \
            .eq("phone", phone) \
            .eq("status", "sent") \
            .execute()
        return True
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao marcar respondido para {phone}: {e}", flush=True)
        return False


def save_csat_score(phone: str, score: int) -> bool:
    """Salva a nota CSAT do lead."""
    db = _db()
    if not db:
        return False
    try:
        db.table("followups") \
            .update({"csat_score": score, "status": "completed"}) \
            .eq("phone", phone) \
            .eq("trigger_event", "csat_48h") \
            .eq("status", "sent") \
            .execute()
        print(f"[FOLLOWUP] CSAT salvo: {phone} nota={score}", flush=True)
        return True
    except Exception as e:
        print(f"[FOLLOWUP] Erro ao salvar CSAT de {phone}: {e}", flush=True)
        return False


# ── Montagem de mensagens de follow-up ───────────────────────────────────────

def _load_finalization_kb() -> dict:
    """Carrega o KB de finalização."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data/finalization.json"
    )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_followup_message(trigger: str, metadata: dict) -> str:
    """
    Monta a mensagem de follow-up correta para o trigger dado.
    Substitui placeholders {nome}, {especialidade_ou_prova}, {mes_atual_mais_dois}.
    """
    kb = _load_finalization_kb()
    name = metadata.get("name", "").split()[0] if metadata.get("name") else ""
    specialty = metadata.get("specialty", "residência")
    prova = metadata.get("prova", "")

    # Calcular mês atual + 2 para mensagens de urgência
    now = _now_utc()
    future_month = (now.month + 2 - 1) % 12 + 1
    months_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    mes_futuro = months_pt[future_month - 1]

    # Mapeamento entre trigger (chave do banco) e chave do KB de finalização
    trigger_to_kb = {
        "cold_d3":  "followup_d3",
        "cold_d7":  "followup_d7",
        "cold_d14": "followup_d14",
        "cold_final": "followup_d14",
    }

    if trigger == "csat_48h":
        template = kb["csat"]["fluxo_comprador"]["mensagem_1_nps"]["mensagem"]
    elif trigger in trigger_to_kb:
        kb_key = trigger_to_kb[trigger]
        messages = kb["sequencia_reengajamento_cold"][kb_key]["mensagens"]
        template = random.choice(messages)
    else:
        template = "Oi {nome}! Passando para saber como você está. Ainda podemos te ajudar com a preparação para residência 😊"

    # Substituir placeholders
    msg = template \
        .replace("{nome}", name if name else "tudo bem?") \
        .replace("{especialidade_ou_prova}", prova or specialty) \
        .replace("{mes_atual_mais_dois}", mes_futuro)

    return msg


def build_csat_reply(score: int, name: str = "") -> str:
    """Retorna a mensagem de resposta ao CSAT baseada na nota."""
    kb = _load_finalization_kb()
    csat = kb["csat"]["fluxo_comprador"]
    first_name = name.split()[0] if name else ""

    if score >= 9:
        msg = csat["mensagem_2a_promotor"]["mensagem"]
    elif score >= 7:
        msg = csat["mensagem_2b_neutro"]["mensagem"]
    else:
        msg = csat["mensagem_2c_critico"]["mensagem"]

    return msg.replace("{nome}", first_name)


# ── Worker de envio (chamado pelo endpoint /followup/process) ─────────────────

def process_pending_followups(agent) -> dict:
    """
    Processa todos os follow-ups pendentes: monta a mensagem e envia via WhatsApp.
    Retorna um relatório de execução.

    Args:
        agent: instância de SalesAgent (para adicionar mensagem à memória)
    """
    pending = get_pending_followups()
    sent = []
    errors = []

    for item in pending:
        phone = item["phone"]
        trigger = item["trigger_event"]
        followup_id = item["id"]
        try:
            meta = json.loads(item.get("metadata") or "{}")
        except Exception:
            meta = {}

        try:
            message = build_followup_message(trigger, meta)
            ok = send_message(phone, message)

            if ok:
                mark_sent(followup_id)
                # Registra na memória do agente para contexto futuro
                agent.memory.add(phone, "assistant", message, channel="whatsapp_followup")
                sent.append({"phone": phone, "trigger": trigger})
                print(f"[FOLLOWUP] Enviado: {trigger} → {phone}", flush=True)
            else:
                errors.append({"phone": phone, "trigger": trigger, "error": "send_failed"})
        except Exception as e:
            errors.append({"phone": phone, "trigger": trigger, "error": str(e)})
            print(f"[FOLLOWUP] Erro ao enviar {trigger} para {phone}: {e}", flush=True)

    return {
        "processed": len(pending),
        "sent": len(sent),
        "errors": len(errors),
        "sent_detail": sent,
        "error_detail": errors,
    }
