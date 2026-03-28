"""
tests/fixtures/payloads.py — Payloads de webhook para testes.
"""

# ── Z-API Payloads ───────────────────────────────────────────────────────────

ZAPI_VALID_TEXT = {
    "type": "ReceivedCallback",
    "fromMe": False,
    "phone": "5511999999999",
    "body": "Quero saber mais sobre o curso R1 intensivo",
    "senderName": "Joao Silva",
}

ZAPI_VALID_NESTED_TEXT = {
    "type": "ReceivedCallback",
    "fromMe": False,
    "phone": "5511988888888",
    "text": {"message": "Qual o preco do curso?"},
    "chatName": "Maria Santos",
}

ZAPI_FROM_ME = {
    "type": "ReceivedCallback",
    "fromMe": True,
    "phone": "5511999999999",
    "body": "Mensagem enviada por nos",
}

ZAPI_NON_TEXT_TYPE = {
    "type": "MessageStatusCallback",
    "fromMe": False,
    "phone": "5511999999999",
    "body": "Status update",
}

ZAPI_EMPTY_BODY = {
    "type": "ReceivedCallback",
    "fromMe": False,
    "phone": "5511999999999",
    "body": "",
}

ZAPI_NO_PHONE = {
    "type": "ReceivedCallback",
    "fromMe": False,
    "phone": "",
    "body": "Mensagem sem phone",
}

ZAPI_WITH_WHATSAPP_SUFFIX = {
    "type": "ReceivedCallback",
    "fromMe": False,
    "phone": "5511999999999@s.whatsapp.net",
    "body": "Mensagem com sufixo",
}

# ── Form Payloads ────────────────────────────────────────────────────────────

FORM_VALID = {
    "name": "Joao Silva",
    "phone": "11999999999",
}

FORM_VALID_CELULAR = {
    "nome": "Maria Santos",
    "celular": "(11) 98888-8888",
}

FORM_NO_PHONE = {
    "name": "Sem Telefone",
}

FORM_INVALID_PHONE = {
    "name": "Phone Invalido",
    "phone": "12345",
}

FORM_VALID_WITH_DDI = {
    "name": "Com DDI",
    "phone": "5511999999999",
}
