"""
Memória de conversa multi-sessão (por número de telefone ou session_id).
Usa cache in-memory para velocidade + Supabase para persistência.
Se o Supabase não estiver configurado, opera apenas em memória.
"""
from core import database


class ConversationMemory:
    def __init__(self):
        # Cache in-memory: { session_id -> list of messages }
        self.sessions = {}
        self.statuses = {}
        # Controla quais sessões já foram carregadas do Supabase
        self._loaded_from_db = set()

    def _ensure_loaded(self, session_id: str):
        """
        Carrega histórico do Supabase na primeira vez que a sessão é acessada.
        Garante que conversas anteriores sejam restauradas após reiniciar o servidor.
        """
        if session_id in self._loaded_from_db:
            return

        self._loaded_from_db.add(session_id)

        if session_id not in self.sessions:
            history = database.load_messages(session_id)
            if history:
                self.sessions[session_id] = history
                print(f"[MEMORY] Restauradas {len(history)} mensagens de {session_id}", flush=True)

    def add(self, session_id: str, role: str, content: str):
        """Adiciona mensagem ao cache e persiste no Supabase."""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": role, "content": content})

        # Persiste no banco (falha silenciosamente se Supabase não configurado)
        database.save_message(session_id, role, content)

    def get(self, session_id: str) -> list:
        """Retorna histórico da sessão, carregando do Supabase se necessário."""
        self._ensure_loaded(session_id)
        return self.sessions.get(session_id, [])

    def reset(self, session_id: str = None):
        """Limpa memória in-memory (não apaga do Supabase — histórico fica preservado)."""
        if session_id:
            self.sessions.pop(session_id, None)
            self.statuses.pop(session_id, None)
            self._loaded_from_db.discard(session_id)
        else:
            self.sessions = {}
            self.statuses = {}
            self._loaded_from_db = set()

    def set_status(self, session_id: str, status: str):
        """Atualiza status da sessão em memória e no Supabase."""
        self.statuses[session_id] = status
        database.update_lead_status(session_id, status)

    def get_status(self, session_id: str) -> str:
        return self.statuses.get(session_id, "active")

    def list_sessions(self) -> list:
        return list(self.sessions.keys())

    def summary(self, session_id: str) -> str:
        lines = []
        for msg in self.get(session_id):
            prefix = "Lead" if msg["role"] == "user" else "Criatons"
            lines.append(f"{prefix}: {msg['content'][:80]}...")
        return "\n".join(lines)
