import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from auth import get_connection
from rag.embedding import embed_texts
from rag.loader import load_document_sections
from rag.splitter import split_sections
from rag.vector_store import add_documents, delete_document, list_documents


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-worker")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_sha256(file_path: Path):
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def update_job(job_id: str, *, status=None, stage=None, error=None, chunks=None):
    fields = ["updated_at = ?"]
    values = [utc_now()]
    for name, value in (
        ("status", status),
        ("stage", stage),
        ("error", error),
        ("chunks", chunks),
    ):
        if value is not None:
            fields.append(f"{name} = ?")
            values.append(value)
    values.append(job_id)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE document_jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )


def process_document_job(job_id: str):
    with get_connection() as connection:
        job = connection.execute(
            "SELECT * FROM document_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if not job:
        return

    file_path = Path(job["stored_path"])
    try:
        update_job(job_id, status="processing", stage="解析文档", error="")
        sections = load_document_sections(str(file_path))
        if not sections:
            raise ValueError("文件中没有可提取的文本")

        update_job(job_id, stage="切分内容")
        chunks = split_sections(sections)
        texts = [chunk["text"] for chunk in chunks]
        if not texts:
            raise ValueError("文档切分后没有有效内容")

        update_job(job_id, stage="生成向量")
        embeddings = embed_texts(texts)

        update_job(job_id, stage="写入知识库")
        with get_connection() as connection:
            still_exists = connection.execute(
                "SELECT 1 FROM document_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not still_exists:
            return
        delete_document(job_id)
        add_documents(
            texts,
            embeddings,
            filename=job["filename"],
            file_id=job_id,
            uploaded_at=job["created_at"],
            chunk_metadatas=chunks,
            user_id=job["user_id"],
            knowledge_base_id=job["knowledge_base_id"],
        )
        update_job(
            job_id,
            status="ready",
            stage="处理完成",
            error="",
            chunks=len(chunks),
        )
    except Exception as error:
        delete_document(job_id)
        update_job(
            job_id,
            status="failed",
            stage="处理失败",
            error=str(error)[:500],
            chunks=0,
        )


def schedule_document_job(job_id: str):
    EXECUTOR.submit(process_document_job, job_id)


def recover_document_jobs():
    with get_connection() as connection:
        connection.execute(
            "UPDATE document_jobs SET status = 'pending', stage = '等待恢复', updated_at = ? WHERE status = 'processing'",
            (utc_now(),),
        )
        rows = connection.execute(
            "SELECT id FROM document_jobs WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    for row in rows:
        schedule_document_job(row["id"])
    return len(rows)


def migrate_existing_documents():
    migrated = 0
    with get_connection() as connection:
        for document in list_documents():
            if not document.get("user_id") or not document.get("knowledge_base_id"):
                continue
            existing = connection.execute(
                "SELECT 1 FROM document_jobs WHERE id = ?", (document["id"],)
            ).fetchone()
            if existing:
                continue
            matches = list(UPLOAD_DIR.glob(f"{document['id']}.*"))
            stored_path = str(matches[0]) if matches else ""
            content_hash = file_sha256(matches[0]) if matches else f"legacy:{document['id']}"
            timestamp = document.get("uploaded_at") or utc_now()
            connection.execute(
                "INSERT INTO document_jobs VALUES (?, ?, ?, ?, ?, ?, 'ready', '处理完成', NULL, ?, ?, ?)",
                (
                    document["id"],
                    document["user_id"],
                    document["knowledge_base_id"],
                    document["filename"],
                    stored_path,
                    content_hash,
                    document["chunks"],
                    timestamp,
                    timestamp,
                ),
            )
            migrated += 1
    return migrated
