"""
Memória de conversa multi-sessão (por user_id / número de telefone).
Usa cache in-memory para velocidade + Supabase (tabela conversations) para persistência.
Se o Supabase não estiver configurado, opera apenas em memória.

FASE 1 — Session IDs UUID + erros visíveis
- Cada conversa recebe um session_id UUID (separado do phone).
- Erros de DB são propagados via logs [DB ERROR] (visíveis no dashboard).
- Tabela unificada: conversations (messages legada é fallback read-only).

Tabela usada: conversations (user_id, session_id, role, content, channel, message_type, created_at)
"""

import time
import threading
from src.core import database
from src.core.security import hash_user_id

# ── Configuração de TTL ──────────────────────────────────────────────────────

SESSION_TTL_SECONDS = 2 * 60 * 60      # 2 horas de inatividade
CLEANUP_INTERVAL_SECONDS = 10 * 60      # Executa limpeza a cada 10 minutos


class ConversationMemory:
    def __init__(self):
        # Cache in-memory: { user_id -> list of {"role": ..., "content": ...} }
        self.sessions: dict = {}
        self.statuses: dict = {}
        # Mapeia user_id -> session_id UUID (para agrupar conversas)
        self._session_ids: dict = {}
        # Controla quais sessões já foram carregadas do Supabase
        self._loaded_from_db: set = set()
        # Timestamp do último acesso por sessão (para TTL)
        self._last_access: dict = {}
        # Lock para acesso thread-safe ao _last_access durante cleanup
        self._lock = threading.Lock()
        # Contadores de falhas de DB (para monitoramento)
        self._db_failures: int = 0
        self._db_successes: int = 0

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
                self._session_ids.pop(sid, None)
                # NÃO remove statuses — mantém para evitar reprocessamento

        if expired:
            print(
                f"[MEMORY] Cleanup: {len(expired)} sessões expiradas removidas do cache. "
                f"{len(self.sessions)} sessões ativas restantes.",
                flush=True,
            )

    def _touch(self, user_id: str):
        """Atualiza timestamp de último acesso."""
        with self._lock:
            self._last_access[user_id] = time.time()

    # ── Session ID management ──────────────────────────────────────────────

    def get_session_id(self, user_id: str, channel: str = None) -> str:
        """
        Retorna o session_id UUID da conversa atual para este user_id.
        Se não existir, cria um novo (e registra no DB se disponível).
        """
        if user_id not in self._session_ids:
            session_id = database.create_session(user_id, channel)
            self._session_ids[user_id] = session_id
            uid_hash = hash_user_id(user_id)
            print(f"[MEMORY] Nova sessão criada: {session_id[:8]}... uid={uid_hash}", flush=True)
        return self._session_ids[user_id]

    # ── Interface pública ──────────────────────────────────────────────────

    def _ensure_loaded(self, user_id: str):
        """
        Carrega as últimas 20 mensagens do Supabase na primeira vez que a sessão
        é acessada. Garante que conversas anteriores sejam restauradas após
        reiniciar o servidor.
        """
        if user_id in self._loaded_from_db:
            return

        self._loaded_from_db.add(user_id)

        if user_id not in self.sessions:
            # Tenta carregar da tabela conversations (unificada)
            history = database.load_conversation_history(user_id, limit=20)
            # Fallback: tenta a tabela messages legada
            if not history:
                history = database.load_messages_legacy(user_id)
            if history:
                self.sessions[user_id] = history
                uid_hash = hash_user_id(user_id)
                print(f"[MEMORY] Restauradas {len(history)} mensagens de uid={uid_hash}", flush=True)

    def add(self, user_id: str, role: str, content: str, channel: str = None):
        """
        Adiciona mensagem ao cache e persiste no Supabase.
        Retorna True se persistiu no DB, False se falhou (mas sempre salva em memória).
        """
        self._touch(user_id)

        if user_id not in self.sessions:
            self.sessions[user_id] = []
        self.sessions[user_id].append({"role": role, "content": content})

        # Persiste na tabela conversations (unificada)
        session_id = self.get_session_id(user_id, channel)
        saved = database.save_message(
            user_id=user_id,
            role=role,
            content=content,
            channel=channel,
            session_id=session_id,
            message_type="conversation",
        )

        if saved:
            self._db_successes += 1
        else:
            self._db_failures += 1
            uid_hash = hash_user_id(user_id)
            print(f"[MEMORY WARN] Mensagem NÃO persistida no DB para uid={uid_hash} (salva só em memória)", flush=True)

        return saved

    def get(self, user_id: str) -> list:
        """Retorna histórico da sessão, carregando do Supabase se necessário."""
        self._touch(user_id)
        self._ensure_loaded(user_id)
        return self.sessions.get(user_id, [])

    def reset(self, user_id: str = None):
        """Limpa memória in-memory (não apaga do Supabase — histórico fica preservado)."""
        if user_id:
            self.sessions.pop(user_id, None)
            self.statuses.pop(user_id, None)
            self._loaded_from_db.discard(user_id)
            self._session_ids.pop(user_id, None)
            with self._lock:
                self._last_access.pop(user_id, None)
        else:
            self.sessions = {}
            self.statuses = {}
            self._loaded_from_db = set()
            self._session_ids = {}
            with self._lock:
                self._last_access = {}

    def set_status(self, user_id: str, status: str):
        """Atualiza status da sessão em memória e no Supabase."""
        self._touch(user_id)
        self.statuses[user_id] = status
        database.update_lead_status(user_id, status)

        # Também atualiza status da sessão UUID se existir
        if user_id in self._session_ids:
            database.update_session_status(self._session_ids[user_id], status)

    def get_status(self, user_id: str) -> str:
        return self.statuses.get(user_id, "active")

    def list_sessions(self) -> list:
        return list(self.sessions.keys())

    def summary(self, user_id: str) -> str:
        lines = []
        for msg in self.get(user_id):
            prefix = "Lead" if msg["role"] == "user" else "Agente"
            lines.append(f"{prefix}: {msg['content'][:80]}...")
        return "\n".join(lines)

    def active_session_count(self) -> int:
        """Retorna o número de sessões atualmente no cache."""
        return len(self.sessions)

    def db_stats(self) -> dict:
        """Retorna estatísticas de persistência no DB."""
        return {
            "db_successes": self._db_successes,
            "db_failures": self._db_failures,
            "db_success_rate": (
                round(self._db_successes / (self._db_successes + self._db_failures) * 100, 1)
                if (self._db_successes + self._db_failures) > 0 else 0
            ),
            "active_sessions": len(self.sessions),
            "session_ids_mapped": len(self._session_ids),
        }
