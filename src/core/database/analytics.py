"""
Advanced analytics.
Provides funnel analysis, time tracking, keywords extraction, and conversation quality scoring.
"""
import re
from datetime import datetime as dt
from .client import _get_client
from .leads import get_lead_metadata


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
