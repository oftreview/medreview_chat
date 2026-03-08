"""
Integração com Z-API para envio e recebimento de mensagens WhatsApp.
Docs: https://developer.z-api.io
"""
import re
import httpx
from core.config import ZAPI_INSTANCE_ID, ZAPI_TOKEN, ZAPI_CLIENT_TOKEN

BASE_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}"


def format_phone(phone: str) -> str:
    """
    Normaliza número para formato Z-API: só dígitos, com DDI 55.
    Remove sufixos como @s.whatsapp.net ou @c.us.
    Ex: (11) 99999-9999 → 5511999999999
    Ex: 5511999999999@s.whatsapp.net → 5511999999999
    """
    # Remove sufixos do WhatsApp antes de processar
    if "@" in phone:
        phone = phone.split("@")[0]
    digits = re.sub(r'\D', '', phone)
    if not digits.startswith('55'):
        digits = '55' + digits
    return digits


def send_message(phone: str, message: str) -> bool:
    """Envia mensagem de texto via Z-API. Retorna True se sucesso."""
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
        print("[Z-API] Credenciais não configuradas — pulando envio.")
        return False

    phone = format_phone(phone)
    url = f"{BASE_URL}/send-text"
    headers = {"client-token": ZAPI_CLIENT_TOKEN} if ZAPI_CLIENT_TOKEN else {}
    payload = {"phone": phone, "message": message}

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[Z-API] Erro ao enviar mensagem para {phone}: {e}")
        return False


def parse_incoming(data: dict) -> dict | None:
    """
    Extrai phone e body de um webhook Z-API.
    Retorna None se não for mensagem recebida de lead.
    Suporta payload texto em 'body' ou em 'text.message'.
    """
    # Ignorar mensagens enviadas por nós mesmos
    if data.get("fromMe") is True:
        return None

    # Aceitar apenas callbacks de mensagem recebida
    # Z-API usa "ReceivedCallback" para mensagens recebidas
    msg_type = data.get("type", "")
    if msg_type != "ReceivedCallback":
        return None

    phone = data.get("phone", "")

    # O Z-API pode enviar o texto em 'body' (direto) ou em 'text.message' (aninhado)
    body = (
        data.get("body")
        or (data.get("text") or {}).get("message")
        or ""
    ).strip()

    name = data.get("senderName") or data.get("chatName") or "Lead"

    if not phone or not body:
        return None

    return {
        "phone": format_phone(phone),
        "message": body,
        "name": name,
    }
