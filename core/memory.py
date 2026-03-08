"""
Memória de conversa em memória RAM (sandbox).
No futuro: substituir por Supabase com tenant_id.
"""

class ConversationMemory:
    def __init__(self):
        self.history = []

    def add(self, role: str, content: str):
        """Adiciona uma mensagem ao histórico. role = 'user' ou 'assistant'"""
        self.history.append({"role": role, "content": content})

    def get(self) -> list:
        """Retorna o histórico completo para enviar à Claude API."""
        return self.history

    def reset(self):
        """Limpa o histórico — simula início de nova conversa."""
        self.history = []

    def summary(self) -> str:
        """Resumo simples da conversa para debug."""
        lines = []
        for msg in self.history:
            prefix = "Lead" if msg["role"] == "user" else "Criatons"
            lines.append(f"{prefix}: {msg['content'][:80]}...")
        return "\n".join(lines)
