"""
Módulo de persistência com Supabase.
Se as variáveis SUPABASE_URL / SUPABASE_KEY não estiverem configuradas,
o módulo opera em modo desabilitado (sem erros) e o app continua funcionando.

FASE 1 — Erros visíveis + tabela unificada (conversations)
- Todas as funções retornam status (True/False ou dados/None) para que o caller saiba se deu certo.
- Erros são logados com tag [DB ERROR] para aparecer no dashboard de logs.
- Tabela `messages` está deprecada — tudo usa `conversations`.
"""
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client = None
_connection_error = None


def _get_client():
    """Inicializa o cliente Supabase (lazy, singleton)."""
    global _client, _connection_error
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        _connection_error = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return None

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _connection_error = None
        print("[DB] Supabase conectado.", flush=True)
    except Exception as e:
        _connection_error = str(e)
        print(f"[DB ERROR] Falha ao conectar Supabase: {e}", flush=True)
        _client = None

    return _client


def get_connection_status() -> dict:
    """Retorna status da conexão para health checks."""
    return {
        "enabled": is_enabled(),
        "connected": _client is not None,
        "error": _connection_error,
    }


# ── Leads ─────────────────────────────────────────────────────────────────────

def upsert_lead(phone: str, name: str = None, source: str = "form", status: str = "active") -> bool:
    """Cria ou atualiza um lead pelo telefone. Retorna True se salvou com sucesso."""
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] upsert_lead falhou — DB não conectado", flush=True)
        return False

    try:
        db.table("leads").upsert(
            {"phone": phone, "name": name, "source": source, "status": status},
            on_conflict="phone"
        ).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] upsert_lead phone={phone[:6]}***: {e}", flush=True)
        return False


def update_lead_status(phone: str, status: str) -> bool:
    """Atualiza o status de um lead (active | escalated | closed). Retorna True se salvou."""
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] update_lead_status falhou — DB não conectado", flush=True)
        return False

    try:
        db.table("leads").update({"status": status}).eq("phone", phone).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] update_lead_status phone={phone[:6]}***: {e}", flush=True)
        return False


# ── Conversations (tabela unificada) ──────────────────────────────────────────
# Todas as mensagens (API, sandbox, WhatsApp) são salvas aqui.
# Campos: id, user_id, session_id, role, content, channel, message_type, created_at

def save_message(user_id: str, role: str, content: str,
                 channel: str = None, session_id: str = None,
                 message_type: str = "conversation") -> bool:
    """
    Salva uma mensagem na tabela conversations.
    Retorna True se salvou com sucesso, False se falhou.

    Params:
        user_id: identificador do lead (telefone ou sandbox ID)
        role: "user" ou "assistant"
        content: texto da mensagem
        channel: "whatsapp" | "sandbox" | "api" | "botmaker"
        session_id: UUID da sessão (agrupa mensagens de uma mesma conversa)
        message_type: "conversation" | "incoming_raw" | "system"
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] save_message falhou — DB não conectado (user={user_id[:8]}...)", flush=True)
        return False

    try:
        row = {
            "user_id": user_id,
            "role": role,
            "content": content,
            "channel": channel,
            "message_type": message_type,
        }
        if session_id:
            row["session_id"] = session_id

        db.table("conversations").insert(row).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_message user={user_id[:8]}... role={role}: {e}", flush=True)
        return False


def save_raw_incoming(user_id: str, content: str, channel: str = None,
                      session_id: str = None) -> bool:
    """
    Salva mensagem bruta do lead ANTES do debounce.
    Garante que nenhuma mensagem seja perdida mesmo se o servidor cair
    durante o período de debounce.
    """
    return save_message(
        user_id=user_id,
        role="user",
        content=content,
        channel=channel,
        session_id=session_id,
        message_type="incoming_raw",
    )


def load_conversation_history(user_id: str, limit: int = 20,
                              session_id: str = None) -> list:
    """
    Carrega as últimas `limit` mensagens de um user_id.
    Filtra apenas message_type='conversation' (ignora incoming_raw).
    Retorna lista cronológica: [{"role": "...", "content": "..."}].
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] load_conversation_history falhou — DB não conectado", flush=True)
        return []

    try:
        query = (
            db.table("conversations")
            .select("role, content")
            .eq("user_id", user_id)
            .eq("message_type", "conversation")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if session_id:
            query = query.eq("session_id", session_id)

        result = query.execute()
        return list(reversed(result.data or []))
    except Exception as e:
        print(f"[DB ERROR] load_conversation_history user={user_id[:8]}...: {e}", flush=True)
        return []


# ── Sessões ───────────────────────────────────────────────────────────────────

def generate_session_id() -> str:
    """Gera um UUID v4 para identificar uma sessão de conversa."""
    return str(uuid.uuid4())


def create_session(user_id: str, channel: str = None) -> str:
    """
    Cria uma nova sessão no banco e retorna o session_id (UUID).
    Se o DB não estiver disponível, retorna o UUID mesmo assim (funciona em memória).
    """
    session_id = generate_session_id()
    db = _get_client()
    if db is None:
        print(f"[DB WARN] create_session — DB não conectado, sessão {session_id[:8]} criada só em memória", flush=True)
        return session_id

    try:
        db.table("sessions").insert({
            "id": session_id,
            "user_id": user_id,
            "channel": channel,
            "status": "active",
        }).execute()
        print(f"[DB] Sessão criada: {session_id[:8]}... user={user_id[:8]}...", flush=True)
    except Exception as e:
        # Tabela sessions pode não existir ainda — não bloqueia
        print(f"[DB WARN] create_session falhou (tabela pode não existir): {e}", flush=True)

    return session_id


def update_session_status(session_id: str, status: str) -> bool:
    """Atualiza status de uma sessão (active | escalated | closed)."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("sessions").update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()
        return True
    except Exception as e:
        print(f"[DB WARN] update_session_status: {e}", flush=True)
        return False


# ── Lead Metadata (qualification_data + funnel_stage) ─────────────────────────

def save_lead_metadata(user_id: str, metadata: dict) -> bool:
    """
    Salva/atualiza metadados do lead (funnel_stage, especialidade, prova, etc).
    Faz upsert na tabela lead_metadata por user_id.
    """
    db = _get_client()
    if db is None:
        return False

    try:
        row = {"user_id": user_id}
        # Mapeia campos conhecidos
        field_map = {
            "stage": "funnel_stage",
            "especialidade": "especialidade",
            "prova": "prova_alvo",
            "ano_prova": "ano_prova",
            "ja_estuda": "ja_estuda",
            "plataforma_atual": "plataforma_atual",
        }
        for meta_key, db_key in field_map.items():
            if meta_key in metadata and metadata[meta_key] is not None:
                row[db_key] = metadata[meta_key]

        db.table("lead_metadata").upsert(row, on_conflict="user_id").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] save_lead_metadata user={user_id[:8]}...: {e}", flush=True)
        return False


def get_lead_metadata(user_id: str) -> dict:
    """Carrega metadados do lead do banco."""
    db = _get_client()
    if db is None:
        return {}

    try:
        result = (
            db.table("lead_metadata")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {}
    except Exception as e:
        print(f"[DB WARN] get_lead_metadata: {e}", flush=True)
        return {}


# ── Escalações ────────────────────────────────────────────────────────────────

def save_escalation(user_id: str, motivo: str, brief: dict,
                    session_id: str = None) -> bool:
    """
    Registra uma escalação na tabela escalations.
    O brief contém o resumo da conversa + dados do lead para o vendedor.
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] save_escalation — DB não conectado", flush=True)
        return False

    try:
        import json as _json
        db.table("escalations").insert({
            "user_id": user_id,
            "session_id": session_id,
            "motivo": motivo,
            "brief": _json.dumps(brief, ensure_ascii=False),
            "status": "pending",
        }).execute()
        print(f"[DB] Escalação registrada: user={user_id[:8]}... motivo={motivo}", flush=True)
        return True
    except Exception as e:
        print(f"[DB ERROR] save_escalation: {e}", flush=True)
        return False


def resolve_escalation_record(user_id: str, resolution: str = None) -> bool:
    """Marca a escalação mais recente como resolvida."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("escalations").update({
            "status": "resolved",
            "resolution": resolution,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).eq("status", "pending").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] resolve_escalation_record: {e}", flush=True)
        return False


def list_escalations(status: str = None, limit: int = 50) -> list:
    """Lista escalações. Se status fornecido, filtra por status."""
    db = _get_client()
    if db is None:
        return []

    try:
        query = (
            db.table("escalations")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"[DB WARN] list_escalations: {e}", flush=True)
        return []


# ── Corrections (Fase 4 — aprendizado contínuo) ──────────────────────────────

def save_correction(correction: dict) -> bool:
    """
    Salva ou atualiza uma correção no Supabase (upsert por correction_id).
    O JSON local continua como cache — Supabase é a fonte de verdade.
    """
    db = _get_client()
    if db is None:
        return False

    try:
        row = {
            "correction_id": correction["id"],
            "categoria": correction.get("categoria", "outro"),
            "severidade": correction.get("severidade", "alta"),
            "gatilho": correction.get("gatilho", ""),
            "resposta_errada": correction.get("resposta_errada", ""),
            "resposta_correta": correction.get("resposta_correta", ""),
            "regra": correction.get("regra", ""),
            "status": correction.get("status", "ativa"),
            "reincidencia": correction.get("reincidencia", False),
            "reincidencia_count": correction.get("reincidencia_count", 0),
        }
        # Link para conversa original (se disponível)
        if correction.get("conversation_user_id"):
            row["conversation_user_id"] = correction["conversation_user_id"]
        if correction.get("conversation_message_id"):
            row["conversation_message_id"] = correction["conversation_message_id"]

        db.table("corrections").upsert(row, on_conflict="correction_id").execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_correction {correction.get('id')}: {e}", flush=True)
        return False


def load_corrections(status: str = None, include_archived: bool = False) -> list:
    """
    Carrega correções do Supabase.
    Por padrão exclui arquivadas (status='arquivada').
    """
    db = _get_client()
    if db is None:
        return []

    try:
        query = (
            db.table("corrections")
            .select("*")
            .order("created_at", desc=True)
        )
        if status:
            query = query.eq("status", status)
        elif not include_archived:
            query = query.neq("status", "arquivada")

        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"[DB WARN] load_corrections: {e}", flush=True)
        return []


def increment_reincidence(correction_id: str) -> bool:
    """Incrementa contador de reincidência de uma correção."""
    db = _get_client()
    if db is None:
        return False

    try:
        # Busca valor atual
        result = (
            db.table("corrections")
            .select("reincidencia_count")
            .eq("correction_id", correction_id)
            .limit(1)
            .execute()
        )
        current = 0
        if result.data:
            current = result.data[0].get("reincidencia_count", 0) or 0

        db.table("corrections").update({
            "reincidencia": True,
            "reincidencia_count": current + 1,
            "last_reincidence_at": datetime.now(timezone.utc).isoformat(),
        }).eq("correction_id", correction_id).execute()
        print(f"[DB] Reincidência incrementada: {correction_id} → {current + 1}", flush=True)
        return True
    except Exception as e:
        print(f"[DB WARN] increment_reincidence: {e}", flush=True)
        return False


def auto_archive_corrections(days: int = 30) -> int:
    """
    Arquiva correções sem reincidência nos últimos N dias.
    Retorna quantidade de correções arquivadas.
    """
    db = _get_client()
    if db is None:
        return 0

    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Busca correções ativas sem reincidência recente
        result = (
            db.table("corrections")
            .select("correction_id, last_reincidence_at, created_at")
            .eq("status", "ativa")
            .execute()
        )

        to_archive = []
        for row in (result.data or []):
            last_event = row.get("last_reincidence_at") or row.get("created_at")
            if last_event and last_event < cutoff:
                to_archive.append(row["correction_id"])

        if not to_archive:
            return 0

        for cid in to_archive:
            db.table("corrections").update({
                "status": "arquivada",
            }).eq("correction_id", cid).execute()

        print(f"[DB] Auto-archive: {len(to_archive)} correções arquivadas (>{days} dias sem reincidência)", flush=True)
        return len(to_archive)
    except Exception as e:
        print(f"[DB WARN] auto_archive_corrections: {e}", flush=True)
        return 0


def correction_analytics(days: int = 7) -> dict:
    """
    Retorna análise de erros dos últimos N dias:
    - Total de correções ativas
    - Reincidências por categoria
    - Categorias mais frequentes
    - Correções críticas reincidentes
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Todas as ativas
        active = (
            db.table("corrections")
            .select("*")
            .eq("status", "ativa")
            .execute()
        )
        corrections = active.data or []

        # Reincidências recentes (últimos N dias)
        recent_reincidences = [
            c for c in corrections
            if c.get("last_reincidence_at") and c["last_reincidence_at"] > cutoff
        ]

        # Agrupar por categoria
        by_category = {}
        for c in corrections:
            cat = c.get("categoria", "outro")
            by_category[cat] = by_category.get(cat, 0) + 1

        # Críticas reincidentes
        critical_reincident = [
            {
                "id": c["correction_id"],
                "categoria": c.get("categoria"),
                "reincidencia_count": c.get("reincidencia_count", 0),
                "regra": c.get("regra", "")[:100],
            }
            for c in corrections
            if c.get("severidade") == "critica" and c.get("reincidencia")
        ]

        return {
            "period_days": days,
            "total_active": len(corrections),
            "reincidences_last_period": len(recent_reincidences),
            "by_category": by_category,
            "critical_reincident": critical_reincident,
        }
    except Exception as e:
        print(f"[DB WARN] correction_analytics: {e}", flush=True)
        return {"error": str(e)}


# ── Analytics (Fase 5 — analytics avançado) ───────────────────────────────────

def analytics_funnel() -> dict:
    """
    Retorna o funil de conversão: quantos leads em cada stage + taxa de avanço.
    Fonte: tabela lead_metadata.
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        result = db.table("lead_metadata").select("funnel_stage").execute()
        rows = result.data or []

        # Contagem por stage
        stage_count = {}
        for r in rows:
            stage = r.get("funnel_stage", "desconhecido")
            stage_count[stage] = stage_count.get(stage, 0) + 1

        total = len(rows)

        # Ordem do funil para calcular taxa de avanço
        funnel_order = [
            "abertura", "qualificacao", "diagnostico", "apresentacao",
            "objecao", "negociacao", "fechamento", "pos_venda",
        ]

        funnel = []
        for stage in funnel_order:
            count = stage_count.pop(stage, 0)
            pct = round(count / total * 100, 1) if total > 0 else 0
            funnel.append({"stage": stage, "count": count, "pct": pct})

        # Stages fora do funil principal (desqualificado, escalado, desconhecido)
        others = {k: v for k, v in stage_count.items()}

        # Taxa de conversão: fechamento / total
        fechamento = next((f["count"] for f in funnel if f["stage"] == "fechamento"), 0)
        pos_venda = next((f["count"] for f in funnel if f["stage"] == "pos_venda"), 0)
        conversion_rate = round((fechamento + pos_venda) / total * 100, 1) if total > 0 else 0

        return {
            "total_leads": total,
            "funnel": funnel,
            "others": others,
            "conversion_rate_pct": conversion_rate,
        }
    except Exception as e:
        print(f"[DB WARN] analytics_funnel: {e}", flush=True)
        return {"error": str(e)}


def analytics_time_per_stage() -> dict:
    """
    Calcula tempo médio que leads ficam em cada stage.
    Baseado em updated_at - created_at da lead_metadata
    (aproximação — idealmente precisaria de log de transição de stage).
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        result = (
            db.table("lead_metadata")
            .select("funnel_stage, created_at, updated_at")
            .execute()
        )
        rows = result.data or []

        from datetime import datetime as dt
        stage_durations = {}

        for r in rows:
            stage = r.get("funnel_stage", "desconhecido")
            created = r.get("created_at")
            updated = r.get("updated_at")
            if not created or not updated:
                continue

            try:
                t_created = dt.fromisoformat(created.replace("Z", "+00:00"))
                t_updated = dt.fromisoformat(updated.replace("Z", "+00:00"))
                duration_min = (t_updated - t_created).total_seconds() / 60

                if stage not in stage_durations:
                    stage_durations[stage] = []
                stage_durations[stage].append(duration_min)
            except (ValueError, TypeError):
                continue

        # Calcula médias
        averages = {}
        for stage, durations in stage_durations.items():
            avg = sum(durations) / len(durations) if durations else 0
            averages[stage] = {
                "avg_minutes": round(avg, 1),
                "count": len(durations),
            }

        return {"time_per_stage": averages}
    except Exception as e:
        print(f"[DB WARN] analytics_time_per_stage: {e}", flush=True)
        return {"error": str(e)}


def analytics_keywords(limit: int = 30) -> dict:
    """
    Extrai palavras-chave mais frequentes das mensagens dos leads.
    Filtra stopwords em português e retorna top N.
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        result = (
            db.table("conversations")
            .select("content")
            .eq("role", "user")
            .eq("message_type", "conversation")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        messages = result.data or []

        # Stopwords básicas pt-BR
        stopwords = {
            "a", "e", "o", "de", "da", "do", "em", "um", "uma", "que", "é",
            "pra", "pro", "com", "não", "nao", "sim", "se", "por", "para",
            "no", "na", "os", "as", "mais", "mas", "eu", "me", "meu", "minha",
            "vc", "voce", "você", "isso", "esse", "essa", "tem", "ter", "foi",
            "já", "ja", "tá", "ta", "tô", "to", "muito", "bem", "aqui", "lá",
            "la", "como", "quando", "qual", "quais", "onde", "oi", "olá", "ola",
            "bom", "boa", "dia", "tudo", "obrigado", "obrigada", "ok",
            "ah", "ai", "aí", "né", "ne", "eh", "hm", "hmm",
        }

        word_count = {}
        for msg in messages:
            content = (msg.get("content") or "").lower()
            # Remove pontuação e divide
            import re
            words = re.findall(r"[a-záàãâéêíóôõúç]+", content)
            for w in words:
                if len(w) >= 3 and w not in stopwords:
                    word_count[w] = word_count.get(w, 0) + 1

        # Top N
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)[:limit]

        return {
            "total_messages_analyzed": len(messages),
            "keywords": [{"word": w, "count": c} for w, c in sorted_words],
        }
    except Exception as e:
        print(f"[DB WARN] analytics_keywords: {e}", flush=True)
        return {"error": str(e)}


def analytics_conversation_quality(user_id: str = None) -> dict:
    """
    Score de qualidade das conversas baseado em:
    - Engajamento (msgs do lead vs total)
    - Perguntas respondidas (lead fez pergunta → agente respondeu)
    - Progresso no funil (avançou de stage?)
    - Duração da conversa (muito curta = ruim)

    Se user_id fornecido, analisa só esse lead. Senão, média geral.
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        # Busca conversas
        query = (
            db.table("conversations")
            .select("user_id, role, content, message_type")
            .eq("message_type", "conversation")
            .order("created_at", desc=True)
            .limit(1000)
        )
        if user_id:
            query = query.eq("user_id", user_id)

        result = query.execute()
        msgs = result.data or []

        # Agrupa por user_id
        by_user = {}
        for m in msgs:
            uid = m["user_id"]
            if uid not in by_user:
                by_user[uid] = {"user": 0, "assistant": 0, "total": 0}
            by_user[uid][m["role"]] = by_user[uid].get(m["role"], 0) + 1
            by_user[uid]["total"] += 1

        # Batch: carregar todos os metadados de uma vez (evita N+1 queries)
        all_uids = list(by_user.keys())
        metadata_map = {}
        if all_uids:
            try:
                meta_result = (
                    db.table("lead_metadata")
                    .select("user_id, funnel_stage")
                    .in_("user_id", all_uids)
                    .execute()
                )
                for row in (meta_result.data or []):
                    metadata_map[row["user_id"]] = row.get("funnel_stage", "desconhecido")
            except Exception:
                pass  # Fallback: stage fica "desconhecido"

        scores = []
        for uid, counts in by_user.items():
            total = counts["total"]
            user_msgs = counts.get("user", 0)
            assistant_msgs = counts.get("assistant", 0)

            # Score de engajamento (0-25): proporção de msgs do lead
            engagement = min(25, round(user_msgs / max(total, 1) * 50))

            # Score de profundidade (0-25): conversas mais longas = melhor
            depth = min(25, round(total / 2))

            # Score de equilíbrio (0-25): lead e agente devem ter qtd similar
            if total > 0:
                ratio = min(user_msgs, assistant_msgs) / max(user_msgs, assistant_msgs, 1)
                balance = round(ratio * 25)
            else:
                balance = 0

            # Score de progresso (0-25): baseado no stage atual
            stage_scores = {
                "abertura": 5, "qualificacao": 10, "diagnostico": 15,
                "apresentacao": 18, "objecao": 15, "negociacao": 20,
                "fechamento": 25, "pos_venda": 25,
                "desqualificado": 10, "escalado": 12,
            }
            stage = metadata_map.get(uid, "desconhecido")
            progress = stage_scores.get(stage, 5)

            total_score = engagement + depth + balance + progress

            scores.append({
                "user_id": uid[:8] + "...",
                "score": min(100, total_score),
                "breakdown": {
                    "engagement": engagement,
                    "depth": depth,
                    "balance": balance,
                    "progress": progress,
                },
                "total_messages": total,
                "funnel_stage": stage,
            })

        # Ordena por score desc
        scores.sort(key=lambda x: x["score"], reverse=True)

        avg_score = round(sum(s["score"] for s in scores) / len(scores), 1) if scores else 0

        return {
            "total_conversations": len(scores),
            "avg_quality_score": avg_score,
            "conversations": scores[:50],  # Top 50
        }
    except Exception as e:
        print(f"[DB WARN] analytics_conversation_quality: {e}", flush=True)
        return {"error": str(e)}


# ── Legado (deprecado — usar save_message) ────────────────────────────────────

def save_message_legacy(phone: str, role: str, content: str) -> bool:
    """DEPRECADO: Salva na tabela messages (legada). Use save_message()."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("messages").insert(
            {"phone": phone, "role": role, "content": content}
        ).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_message_legacy phone={phone[:6]}***: {e}", flush=True)
        return False


def load_messages_legacy(phone: str) -> list:
    """DEPRECADO: Carrega da tabela messages (legada). Use load_conversation_history()."""
    db = _get_client()
    if db is None:
        return []

    try:
        result = (
            db.table("messages")
            .select("role, content")
            .eq("phone", phone)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"[DB ERROR] load_messages_legacy phone={phone[:6]}***: {e}", flush=True)
        return []


# ── Health Check ──────────────────────────────────────────────────────────────

def health_check() -> dict:
    """
    Testa conexão real com o Supabase: leitura + escrita + delete.
    Retorna dict com status detalhado.
    """
    result = {
        "enabled": is_enabled(),
        "connected": False,
        "read": False,
        "write": False,
        "delete": False,
        "error": None,
        "latency_ms": None,
    }

    if not is_enabled():
        result["error"] = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return result

    db = _get_client()
    if db is None:
        result["error"] = _connection_error or "Cliente não inicializado"
        return result

    import time
    start = time.time()

    # Teste de escrita
    test_id = f"_healthcheck_{uuid.uuid4().hex[:8]}"
    try:
        db.table("conversations").insert({
            "user_id": test_id,
            "role": "system",
            "content": "health_check_probe",
            "message_type": "system",
            "channel": "healthcheck",
        }).execute()
        result["write"] = True
    except Exception as e:
        result["error"] = f"Write failed: {e}"
        result["latency_ms"] = round((time.time() - start) * 1000)
        return result

    # Teste de leitura
    try:
        read_result = (
            db.table("conversations")
            .select("user_id")
            .eq("user_id", test_id)
            .limit(1)
            .execute()
        )
        result["read"] = len(read_result.data or []) > 0
    except Exception as e:
        result["error"] = f"Read failed: {e}"

    # Cleanup — remove o registro de teste
    try:
        db.table("conversations").delete().eq("user_id", test_id).execute()
        result["delete"] = True
    except Exception as e:
        result["error"] = f"Delete failed: {e}"

    result["connected"] = result["read"] and result["write"]
    result["latency_ms"] = round((time.time() - start) * 1000)

    return result


def is_enabled() -> bool:
    """Retorna True se o Supabase está configurado."""
    return bool(SUPABASE_URL and SUPABASE_KEY)
