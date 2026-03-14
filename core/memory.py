"""
Memória de conversa multi-sessão (por user_id / número de telefone).
Usa cache in-memory para velocidade + Supabase (tabela conversations) para persistência.
Se o Supabase não estiver configurado, opera apenas em memória.

Inclui TTL para evitar memory leak em produção: sessões inativas por mais de
SESSION_TTL_SECONDS são removidas do cache (o histórico permanece no Supabase
e será recarregado sob demanda na próxima mensagem).

Tabela usada: conversations (user_id, role, content, channel, created_at)
"""

import time
import threading
from core import database
from core.security import hash_user_id

# ── Configuração de TTL ──────────────────────────────────────────────────────

SESSION_TTL_SECONDS = 2 * 60 * 60      # 2 horas de inatividade
CLEANUP_INTERVAL_SECONDS = 10 * 60      # Executa limpeza a cada 10 minutos


class ConversationMemory:
    def __init__(self):
        # Cache in-memory: { session_id -> list of {"role": ..., "content": ...} }
        self.sessions: dict = {}
        self.statuses: dict = {}
        # Controla quais sessões já foram carregadas do Supabase
        self._loaded_from_db: set = set()
        # Timestamp do último acesso por sessão (para TTL)
        self._last_access: dict = {}
        # Lock para acesso thread-safe ao _last_access durante cleanup
        self._lock = threading.Lock()

        # Inicia thread daemon de limpeza periódica
        self._start_cleanup_loop()

    # ── Cleanup periódico ────────────────────────────────────────────────────

    def _start_cleanup_loop(self):
        """Inicia thread daemon que limpa sessões expiradas periodicamente."""
        def _loop():
            while True:
                time.sleep(CLEANUP_INTERVAL_SECONDS)
                self._cleanup_expired()

        t = threading.Thread(target=_loop, daemon=True, name="memory-cleanup")
        t.start()

    def _cleanup_expired(self):
        """Remove sessões que não receberam acesso há mais de SESSION_TTL_SECONDS."""
        now = time.time()
        cutoff = now - SESSION_TTL_SECONDS
        expired = []

        with self._lock:
            for sid, last_ts in list(self._last_access.items()):
                if last_ts < cutoff:
                    # Não remove sessões escalated — o supervisor pode precisar
                    if self.statuses.get(sid) == "escalated":
                        continue
                    expired.append(sid)

            for sid in expired:
                self.sessions.pop(sid, None)
                self._loaded_from_db.discard(sid)
                self._last_access.pop(sid, None)
                # NÃO remove statuses — mantém para evitar reprocessamento

        if expired:
            print(
                f"[MEMORY] Cleanup: {len(expired)} sessões expiradas removidas do cache. "
                f"{len(self.sessions)} sessões ativas restantes.",
                flush=True,
            )

    def _touch(self, session_id: str):
        """Atualiza timestamp de último acesso."""
        with self._lock:
            self._last_access[session_id] = time.time()

    # ── Interface pública ────────────────────────────────────────────────────

    def _ensure_loaded(self, session_id: str):
        """
        Carrega as últimas 20 mensagens do Supabase na primeira vez que a sessão
        é acessada. Garante que conversas anteriores sejam restauradas após
        reiniciar o servidor.
        """
        if session_id in self._loaded_from_db:
            return

        self._loaded_from_db.add(session_id)

        if session_id not in self.sessions:
            # Tenta carregar da tabela conversations (endpoint /chat e webhooks)
            history = database.load_conversation_history(session_id, limit=20)
            # Fallback: tenta a tabela messages legada (webhooks WhatsApp antigos)
            if not history:
                history = database.load_messages(session_id)
            if history:
                self.sessions[session_id] = history
                uid_hash = hash_user_id(session_id)
                print(f"[MEMORY] Restauradas {len(history)} mensagens de uid={uid_hash}", flush=True)

    def add(self, session_id: str, role: str, content: str, channel: str = None):
        """Adiciona mensagem ao cache e persiste no Supabase (tabela conversations)."""
        self._touch(session_id)

        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": role, "content": content})

        # Persiste na tabela conversations (unificada, suporta todos os canais)
        database.save_conversation_message(session_id, role, content, channel)

    def get(self, session_id: str) -> list:
        """Retorna histórico da sessão, carregando do Supabase se necessário."""
        self._touch(session_id)
        self._ensure_loaded(session_id)
        return self.sessions.get(session_id, [])

    def reset(self, session_id: str = None):
        """Limpa memória in-memory (não apaga do Supabase — histórico fica preservado)."""
        if session_id:
            self.sessions.pop(session_id, None)
            self.statuses.pop(session_id, None)
            self._loaded_from_db.discard(session_id)
            with self._lock:
                self._last_access.pop(session_id, None)
        else:
            self.sessions = {}
            self.statuses = {}
            self._loaded_from_db = set()
            with self._lock:
                self._last_access = {}

    def set_status(self, session_id: str, status: str):
        """Atualiza status da sessão em memória e no Supabase."""
        self._touch(session_id)
        self.statuses[session_id] = status
        database.update_lead_status(session_id, status)

    def get_status(self, session_id: str) -> str:
        return self.statuses.get(session_id, "active")

    def list_sessions(self) -> list:
        return list(self.sessions.keys())

    def summary(self, session_id: str) -> str:
        lines = []
        for msg in self.get(session_id):
            prefix = "Lead" if msg["role"] == "user" else "Agente"
            lines.append(f"{prefix}: {msg['content'][:80]}...")
        return "\n".join(lines)

    def active_session_count(self) -> int:
        """Retorna o número de sessões atualmente no cache."""
        return len(self.sessions)
