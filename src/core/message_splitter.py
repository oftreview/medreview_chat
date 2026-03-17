"""
Quebra inteligente de respostas do agente em múltiplas mensagens curtas.

Simula o comportamento natural de um humano no WhatsApp:
  - Mensagens curtas (até MAX_CHARS cada)
  - Máximo de MAX_MESSAGES por resposta
  - Separação por contexto (parágrafos), nunca no meio de uma frase

Uso:
  from src.core.message_splitter import split_response
  parts = split_response("Texto longo do Claude...")
  # → ["Parte 1", "Parte 2"]  (lista de 1 a MAX_MESSAGES strings)
"""

import re

# ── Configuração ────────────────────────────────────────────────────────────
MAX_CHARS = 300       # Limite de caracteres por mensagem
MAX_MESSAGES = 3      # Máximo de mensagens por resposta
DELAY_SECONDS = 3     # Delay entre mensagens (usado pelo caller, não aqui)

# Regex para encontrar fim de frase (. ! ? seguido de espaço ou fim de string)
_SENTENCE_END = re.compile(r'[.!?](?:\s|$)')


def _split_paragraph(text: str, max_chars: int) -> list[str]:
    """
    Quebra um parágrafo longo em pedaços menores, cortando na última
    fronteira de frase antes do limite de caracteres.

    Se não encontrar fronteira de frase, corta na última palavra inteira.
    Nunca corta no meio de uma palavra.
    """
    chunks = []
    remaining = text.strip()

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Procura a última fronteira de frase antes do limite
        search_area = remaining[:max_chars]
        best_cut = -1

        for match in _SENTENCE_END.finditer(search_area):
            best_cut = match.end()

        if best_cut > 0:
            # Corta na fronteira de frase
            chunks.append(remaining[:best_cut].strip())
            remaining = remaining[best_cut:].strip()
        else:
            # Sem fronteira de frase — corta na última palavra inteira
            last_space = search_area.rfind(' ')
            if last_space > 0:
                chunks.append(remaining[:last_space].strip())
                remaining = remaining[last_space:].strip()
            else:
                # Palavra única gigante (raro) — corta forçado
                chunks.append(remaining[:max_chars])
                remaining = remaining[max_chars:].strip()

    return chunks


def split_response(text: str, max_chars: int = MAX_CHARS, max_messages: int = MAX_MESSAGES) -> list[str]:
    """
    Quebra a resposta do agente em 1 a max_messages mensagens.

    Estratégia:
      1. Divide por parágrafos (\\n\\n) — fronteira natural de contexto
      2. Agrupa parágrafos curtos na mesma mensagem (até max_chars)
      3. Parágrafos que excedem max_chars são quebrados por frase
      4. Limita a max_messages no total

    Args:
        text: Resposta completa do Claude
        max_chars: Caracteres máximos por mensagem (default: 300)
        max_messages: Número máximo de mensagens (default: 3)

    Returns:
        Lista de 1 a max_messages strings, cada uma <= max_chars
    """
    if not text or not text.strip():
        return [text or ""]

    # Remove espaços extras e normaliza quebras de linha
    text = text.strip()

    # Se já cabe em uma mensagem, retorna direto
    if len(text) <= max_chars:
        return [text]

    # 1. Divide por parágrafos (dupla quebra de linha)
    raw_paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

    # 2. Expande parágrafos longos em sub-chunks
    all_chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            all_chunks.append(para)
        else:
            all_chunks.extend(_split_paragraph(para, max_chars))

    # 3. Agrupa chunks pequenos na mesma mensagem (até max_chars)
    messages: list[str] = []
    current = ""

    for chunk in all_chunks:
        if not current:
            current = chunk
        elif len(current) + len("\n\n") + len(chunk) <= max_chars:
            current += "\n\n" + chunk
        else:
            messages.append(current)
            current = chunk

    if current:
        messages.append(current)

    # 4. Limita a max_messages — se exceder, agrupa o restante na última
    if len(messages) > max_messages:
        overflow = messages[max_messages - 1:]
        messages = messages[:max_messages - 1]
        messages.append("\n\n".join(overflow))

    # Garante que cada mensagem final respeita o limite
    # (a última pode ter estourado por causa do overflow join)
    final: list[str] = []
    for msg in messages:
        if len(msg) <= max_chars:
            final.append(msg)
        else:
            # Re-quebra se a junção do overflow estourou
            sub_parts = _split_paragraph(msg, max_chars)
            remaining_slots = max_messages - len(final)
            if len(sub_parts) <= remaining_slots:
                final.extend(sub_parts)
            else:
                # Pega o que cabe e junta o resto na última
                final.extend(sub_parts[:remaining_slots - 1])
                final.append("\n\n".join(sub_parts[remaining_slots - 1:]))

    return final if final else [text]
