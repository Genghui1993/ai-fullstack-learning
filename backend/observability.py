import json
import uuid
from datetime import datetime, timezone

from auth import get_connection


def create_query_log(
    user_id: str,
    knowledge_base_id: str,
    question: str,
    retrieval_ms: float,
    sources,
):
    log_id = str(uuid.uuid4())
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO query_logs
            (id, user_id, knowledge_base_id, question, status, retrieval_ms,
             sources_json, created_at)
            VALUES (?, ?, ?, ?, 'processing', ?, ?, ?)
            """,
            (
                log_id,
                user_id,
                knowledge_base_id,
                question[:1000],
                round(retrieval_ms, 2),
                json.dumps(sources, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return log_id


def finish_query_log(
    log_id: str,
    *,
    status: str,
    model_ms: float,
    total_ms: float,
    usage=None,
    error: str | None = None,
):
    usage = usage or {}
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE query_logs
            SET status = ?, model_ms = ?, total_ms = ?, prompt_tokens = ?,
                completion_tokens = ?, total_tokens = ?, error = ?
            WHERE id = ?
            """,
            (
                status,
                round(model_ms, 2),
                round(total_ms, 2),
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
                int(usage.get("total_tokens", 0) or 0),
                error[:500] if error else None,
                log_id,
            ),
        )


def usage_to_dict(usage):
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }
