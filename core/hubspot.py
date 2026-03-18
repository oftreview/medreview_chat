"""
Módulo de integração HubSpot — Fase 3 (Closi AI → HubSpot).

Direção: unidirecional (Closi AI → HubSpot).
O agente envia dados para o HubSpot conforme interage com leads.

Mapeamento:
  - Lead → HubSpot Contact (by phone)
  - Funnel stage → HubSpot Deal Pipeline
  - Conversa resumida → HubSpot Timeline Note
  - Escalação → HubSpot Deal + Note

Configuração necessária (.env):
  HUBSPOT_ACCESS_TOKEN=pat-na1-xxxxx
  HUBSPOT_PIPELINE_ID=default (ou ID customizado)
  HUBSPOT_ENABLED=true
"""

import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PIPELINE_ID = os.getenv("HUBSPOT_PIPELINE_ID", "default")
HUBSPOT_ENABLED = os.getenv("HUBSPOT_ENABLED", "false").lower() in ("true", "1", "yes")

# Base URL da API v3 do HubSpot
_BASE = "https://api.hubapi.com"

# Mapeamento: funnel_stage (Closi AI) → deal stage ID (HubSpot)
# O usuário pode customizar via /api/hubspot/mapping ou variável de ambiente
# Por padrão usa nomes descritivos — precisam ser mapeados ao pipeline real
_DEFAULT_STAGE_MAP = {
    "abertura": "qualifiedtobuy",
    "qualificacao": "qualifiedtobuy",
    "diagnostico": "qualifiedtobuy",
    "apresentacao": "presentationscheduled",
    "objecao": "presentationscheduled",
    "negociacao": "decisionmakerboughtin",
    "fechamento": "closedwon",
    "pos_venda": "closedwon",
    "desqualificado": "closedlost",
    "escalado": "decisionmakerboughtin",
}

# Cache em memória do mapeamento customizado
_custom_stage_map: dict = {}


def _get_stage_map() -> dict:
    """Retorna mapeamento de stages, priorizando customizado sobre default."""
    if _custom_stage_map:
        return {**_DEFAULT_STAGE_MAP, **_custom_stage_map}
    return _DEFAULT_STAGE_MAP


def set_stage_mapping(mapping: dict) -> None:
    """Atualiza mapeamento customizado de stages (via API /api/hubspot/mapping)."""
    global _custom_stage_map
    _custom_stage_map = mapping
    print(f"[HUBSPOT] Stage mapping atualizado: {len(mapping)} regras", flush=True)


def is_enabled() -> bool:
    """Retorna True se a integração HubSpot está ativa e configurada."""
    return HUBSPOT_ENABLED and bool(HUBSPOT_ACCESS_TOKEN)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _request(method: str, endpoint: str, payload: dict = None, timeout: int = 10) -> dict | None:
    """
    Faz request HTTP para a API HubSpot.
    Retorna dict do response ou None em caso de erro.
    Usa httpx para não bloquear (compatível com gevent).
    """
    if not is_enabled():
        return None

    import httpx

    url = f"{_BASE}{endpoint}"
    try:
        if method == "GET":
            r = httpx.get(url, headers=_headers(), timeout=timeout)
        elif method == "POST":
            r = httpx.post(url, headers=_headers(), json=payload, timeout=timeout)
        elif method == "PATCH":
            r = httpx.patch(url, headers=_headers(), json=payload, timeout=timeout)
        else:
            print(f"[HUBSPOT ERROR] Método HTTP não suportado: {method}", flush=True)
            return None

        if r.status_code in (200, 201):
            return r.json()
        elif r.status_code == 409:
            # Conflito — contact já existe (normal no create)
            return {"status": "conflict", "detail": r.text}
        else:
            print(f"[HUBSPOT ERROR] {method} {endpoint} → {r.status_code}: {r.text[:300]}", flush=True)
            return None

    except Exception as e:
        print(f"[HUBSPOT ERROR] {method} {endpoint} → {type(e).__name__}: {e}", flush=True)
        return None


# ── Contacts ──────────────────────────────────────────────────────────────────

def find_contact_by_phone(phone: str) -> dict | None:
    """
    Busca contact no HubSpot pelo telefone.
    Retorna dict com id e properties, ou None se não encontrar.
    """
    payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "phone",
                "operator": "EQ",
                "value": phone,
            }]
        }],
        "properties": ["firstname", "lastname", "email", "phone", "lifecyclestage"],
        "limit": 1,
    }
    result = _request("POST", "/crm/v3/objects/contacts/search", payload)
    if result and result.get("total", 0) > 0:
        return result["results"][0]
    return None


def upsert_contact(phone: str, name: str = "", lead_data: dict = None) -> str | None:
    """
    Cria ou atualiza contact no HubSpot.
    Retorna o contact_id ou None em caso de erro.
    """
    if not is_enabled():
        return None

    lead_data = lead_data or {}

    # Monta properties
    properties = {
        "phone": phone,
        "lifecyclestage": "lead",
    }

    if name and name != "Lead":
        parts = name.split(maxsplit=1)
        properties["firstname"] = parts[0]
        if len(parts) > 1:
            properties["lastname"] = parts[1]

    # Mapeia dados do lead para custom properties do HubSpot
    if lead_data.get("especialidade") and lead_data["especialidade"] != "desconhecido":
        properties["especialidade_medica"] = lead_data["especialidade"]
    if lead_data.get("prova") and lead_data["prova"] != "desconhecido":
        properties["prova_alvo"] = lead_data["prova"]
    if lead_data.get("ano_prova") and lead_data["ano_prova"] != "desconhecido":
        properties["ano_prova"] = lead_data["ano_prova"]
    if lead_data.get("plataforma_atual") and lead_data["plataforma_atual"] != "desconhecido":
        properties["plataforma_atual"] = lead_data["plataforma_atual"]

    # Tenta encontrar existente primeiro
    existing = find_contact_by_phone(phone)

    if existing:
        contact_id = existing["id"]
        result = _request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", {"properties": properties})
        if result:
            print(f"[HUBSPOT] Contact atualizado: {contact_id}", flush=True)
            return contact_id
    else:
        result = _request("POST", "/crm/v3/objects/contacts", {"properties": properties})
        if result and result.get("id"):
            contact_id = result["id"]
            print(f"[HUBSPOT] Contact criado: {contact_id}", flush=True)
            return contact_id

    return None


# ── Deals ─────────────────────────────────────────────────────────────────────

def find_deal_by_phone(phone: str) -> dict | None:
    """
    Busca deal associado ao contact com esse telefone.
    Retorna o deal mais recente ou None.
    """
    contact = find_contact_by_phone(phone)
    if not contact:
        return None

    contact_id = contact["id"]
    result = _request("GET", f"/crm/v3/objects/contacts/{contact_id}/associations/deals")
    if result and result.get("results"):
        deal_id = result["results"][0]["id"]
        deal = _request("GET", f"/crm/v3/objects/deals/{deal_id}?properties=dealname,dealstage,pipeline,amount")
        return deal
    return None


def upsert_deal(phone: str, name: str = "Lead", funnel_stage: str = "abertura",
                lead_data: dict = None) -> str | None:
    """
    Cria ou atualiza deal no HubSpot pipeline.
    Associa ao contact pelo telefone.
    Retorna deal_id ou None.
    """
    if not is_enabled():
        return None

    stage_map = _get_stage_map()
    hubspot_stage = stage_map.get(funnel_stage, "qualifiedtobuy")

    # Garante que o contact existe
    contact_id = upsert_contact(phone, name, lead_data)
    if not contact_id:
        print(f"[HUBSPOT WARN] Não conseguiu criar/encontrar contact para deal", flush=True)
        return None

    # Busca deal existente
    existing_deal = find_deal_by_phone(phone)

    deal_name = f"MedReview R1 — {name}"

    if existing_deal:
        deal_id = existing_deal["id"]
        update = {"properties": {"dealstage": hubspot_stage}}
        result = _request("PATCH", f"/crm/v3/objects/deals/{deal_id}", update)
        if result:
            print(f"[HUBSPOT] Deal atualizado: {deal_id} stage={hubspot_stage}", flush=True)
            return deal_id
    else:
        payload = {
            "properties": {
                "dealname": deal_name,
                "dealstage": hubspot_stage,
                "pipeline": HUBSPOT_PIPELINE_ID,
            },
            "associations": [{
                "to": {"id": contact_id},
                "types": [{
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": 3,  # Deal → Contact
                }],
            }],
        }
        result = _request("POST", "/crm/v3/objects/deals", payload)
        if result and result.get("id"):
            deal_id = result["id"]
            print(f"[HUBSPOT] Deal criado: {deal_id} stage={hubspot_stage}", flush=True)
            return deal_id

    return None


# ── Notes (Timeline) ─────────────────────────────────────────────────────────

def add_note(phone: str, body: str) -> str | None:
    """
    Adiciona nota (engagement) ao contact no HubSpot.
    Usada para registrar resumos de conversa e escalações.
    Retorna note_id ou None.
    """
    if not is_enabled():
        return None

    contact = find_contact_by_phone(phone)
    if not contact:
        print(f"[HUBSPOT WARN] Contact não encontrado para nota", flush=True)
        return None

    contact_id = contact["id"]

    payload = {
        "properties": {
            "hs_timestamp": str(int(time.time() * 1000)),
            "hs_note_body": body,
        },
        "associations": [{
            "to": {"id": contact_id},
            "types": [{
                "associationCategory": "HUBSPOT_DEFINED",
                "associationTypeId": 202,  # Note → Contact
            }],
        }],
    }

    result = _request("POST", "/crm/v3/objects/notes", payload)
    if result and result.get("id"):
        note_id = result["id"]
        print(f"[HUBSPOT] Nota adicionada: {note_id}", flush=True)
        return note_id

    return None


# ── Sync principal (chamado pelo agent/app) ───────────────────────────────────

def sync_lead(phone: str, name: str = "Lead", funnel_stage: str = "abertura",
              lead_data: dict = None) -> dict:
    """
    Sync completo de um lead para o HubSpot:
      1. Upsert Contact
      2. Upsert Deal (com stage mapeado)

    Retorna dict com contact_id e deal_id (ou None em cada).
    Chamado automaticamente pelo agent após cada interação.
    """
    if not is_enabled():
        return {"contact_id": None, "deal_id": None, "synced": False, "reason": "disabled"}

    contact_id = upsert_contact(phone, name, lead_data)
    deal_id = upsert_deal(phone, name, funnel_stage, lead_data)

    synced = contact_id is not None
    print(f"[HUBSPOT] Sync lead: contact={contact_id} deal={deal_id} stage={funnel_stage}", flush=True)

    return {
        "contact_id": contact_id,
        "deal_id": deal_id,
        "synced": synced,
    }


def sync_escalation(phone: str, brief: dict) -> bool:
    """
    Registra escalação no HubSpot como nota no contact.
    Chamado pelo módulo de escalação.
    """
    if not is_enabled():
        return False

    lead_data = brief.get("lead_data", {})
    motivo = lead_data.get("motivo_escalacao", "nao_especificado")
    summary = brief.get("summary", "(sem resumo)")

    body = (
        f"<h3>🔴 Escalação — Atendimento Humano</h3>"
        f"<p><b>Motivo:</b> {motivo}</p>"
        f"<p><b>Estágio:</b> {lead_data.get('stage', 'desconhecido')}</p>"
        f"<p><b>Especialidade:</b> {lead_data.get('especialidade', 'desconhecido')}</p>"
        f"<p><b>Prova:</b> {lead_data.get('prova', 'desconhecido')}</p>"
        f"<p><b>Resumo:</b> {summary}</p>"
    )

    note_id = add_note(phone, body)
    return note_id is not None


def get_status() -> dict:
    """
    Retorna status da integração HubSpot.
    Usado pelo health check e dashboard.
    """
    status = {
        "enabled": HUBSPOT_ENABLED,
        "configured": bool(HUBSPOT_ACCESS_TOKEN),
        "pipeline_id": HUBSPOT_PIPELINE_ID,
        "stage_mapping": _get_stage_map(),
        "connected": False,
    }

    if not is_enabled():
        return status

    # Testa conexão real
    result = _request("GET", "/crm/v3/objects/contacts?limit=1")
    status["connected"] = result is not None

    return status
