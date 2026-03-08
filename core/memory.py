"""
Memória de conversa multi-sessão (por número de telefone ou session_id).
No futuro: substituir por Supabase com tenant_id.
"""

class ConversationMemory:
    def __init__(self):
        # sessions: dict { session_id -> list of messages }
        self.sessions = {}
        self.statuses = {}

    def add(self, session_id: str, role: str, content: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": role, "content": content})

    def get(self, session_id: str) -> list:
        return self.sessions.get(session_id, [])

    def reset(self, session_id: str = None):
        if session_id:
            self.sessions.pop(session_id, None)
            self.statuses.pop(session_id, None)
        else:
            self.sessions = {}
            self.statuses = {}

    def set_status(self, session_id: str, status: str):
        self.statuses[session_id] = status

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
