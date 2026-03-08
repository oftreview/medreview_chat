from anthropic import Anthropic
from core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS

client = Anthropic(api_key=ANTHROPIC_API_KEY)

def call_claude(system_prompt: str, messages: list) -> str:
    """
    Chama a Claude API com o system prompt e histórico de mensagens.
    Retorna o texto da resposta.
    """
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages
    )
    return response.content[0].text
