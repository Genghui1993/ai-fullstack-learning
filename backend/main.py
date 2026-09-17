from rag.vector_store import (
    add_documents,
    assign_unscoped_documents,
    delete_document,
    list_documents,
)
from fastapi import UploadFile, File, Form, HTTPException
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone
import json
from rag.embedding import embed_texts
from rag.vector_store import search
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import time
from fastapi.responses import StreamingResponse
from auth import (
    ensure_default_knowledge_base,
    get_connection,
    get_current_user,
    router as auth_router,
)
from document_processor import (
    file_sha256,
    migrate_existing_documents,
    recover_document_jobs,
    schedule_document_job,
    utc_now,
)
from observability import create_query_log, finish_query_log, usage_to_dict


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise RuntimeError(
        "缺少 DEEPSEEK_API_KEY，请复制 backend/.env.example 为 backend/.env 后填写"
    )


app = FastAPI()
app.include_router(auth_router)


@app.on_event("startup")
def initialize_document_jobs():
    migrate_existing_documents()
    recover_document_jobs()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)


class ChatRequest(BaseModel):
    message: str
    knowledge_base_id: str


class KnowledgeBaseRequest(BaseModel):
    name: str


def get_owned_knowledge_base(knowledge_base_id: str, user_id: str):
    with get_connection() as connection:
        knowledge_base = connection.execute(
            "SELECT * FROM knowledge_bases WHERE id = ? AND user_id = ?",
            (knowledge_base_id, user_id),
        ).fetchone()
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return dict(knowledge_base)


def build_prompt(message: str, context: str):
    return f"""
        你是一个个人知识库助手。

        请严格根据知识库资料回答，不得使用资料外的信息补全答案。
        当一般规则与特殊场景规则同时出现时，优先采用与用户场景匹配的特殊规则。
        表格中行与列必须同时匹配，不要混用其他城市、角色或产品档位的数据。
        如果资料不足以回答，请明确告诉用户“知识库中没有找到相关信息”。

        知识库资料：
        {context}

        用户问题：
        {message}
    """


def retrieve_context(message: str, user_id: str, knowledge_base_id: str):
    question_vector = embed_texts([message])[0]
    result = search(
        question_vector,
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
    )
    docs = result.get("documents", [[]])[0] or []
    metadatas = result.get("metadatas", [[]])[0] or []
    distances = result.get("distances", [[]])[0] or []

    sources = []
    context_parts = []
    for index, doc in enumerate(docs):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None
        score = round(1 / (1 + distance), 3) if distance is not None else None
        source = {
            "filename": metadata.get("filename", "未知文件"),
            "chunk_index": metadata.get("chunk_index", index) + 1,
            "page": metadata.get("page"),
            "title": metadata.get("title", ""),
            "score": score,
            "excerpt": doc[:180],
        }
        sources.append(source)
        location = f"第{source['page']}页" if source["page"] else f"片段{source['chunk_index']}"
        context_parts.append(
            f"[来源{index + 1}: {source['filename']} / {location}]\n{doc}"
        )

    context = "\n\n".join(context_parts) if context_parts else "（知识库为空，暂无资料）"
    return context, sources



@app.get("/")
def root():
    return {
        "message": "AI backend running"
    }



@app.post("/chat")
def chat(request: ChatRequest, user=Depends(get_current_user)):
    started_at = time.perf_counter()
    get_owned_knowledge_base(request.knowledge_base_id, user["id"])
    context, sources = retrieve_context(
        request.message, user["id"], request.knowledge_base_id
    )
    retrieval_ms = (time.perf_counter() - started_at) * 1000
    log_id = create_query_log(
        user["id"],
        request.knowledge_base_id,
        request.message,
        retrieval_ms,
        sources,
    )
    prompt = build_prompt(request.message, context)
    model_started_at = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
        )
        finish_query_log(
            log_id,
            status="success",
            model_ms=(time.perf_counter() - model_started_at) * 1000,
            total_ms=(time.perf_counter() - started_at) * 1000,
            usage=usage_to_dict(response.usage),
        )
        return {
            "answer": response.choices[0].message.content,
            "sources": sources,
            "trace_id": log_id,
        }
    except Exception as error:
        finish_query_log(
            log_id,
            status="error",
            model_ms=(time.perf_counter() - model_started_at) * 1000,
            total_ms=(time.perf_counter() - started_at) * 1000,
            error=str(error),
        )
        raise HTTPException(status_code=502, detail="模型服务暂时不可用")

@app.post("/chat/stream")
def chat_stream(request: ChatRequest, user=Depends(get_current_user)):
    started_at = time.perf_counter()
    get_owned_knowledge_base(request.knowledge_base_id, user["id"])
    context, sources = retrieve_context(
        request.message, user["id"], request.knowledge_base_id
    )
    retrieval_ms = (time.perf_counter() - started_at) * 1000
    log_id = create_query_log(
        user["id"],
        request.knowledge_base_id,
        request.message,
        retrieval_ms,
        sources,
    )
    prompt = build_prompt(request.message, context)

    # 5. 调用 DeepSeek，并开启流式输出
    def generate():
        yield json.dumps(
            {"type": "sources", "sources": sources, "trace_id": log_id}, ensure_ascii=False
        ) + "\n"

        model_started_at = time.perf_counter()
        status = "processing"
        error_message = None
        usage = {}
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
            )

            for chunk in response:
                if getattr(chunk, "usage", None):
                    usage = usage_to_dict(chunk.usage)
                content = None
                if getattr(chunk, "choices", None):
                    content = chunk.choices[0].delta.content
                if content:
                    yield json.dumps(
                        {"type": "token", "content": content}, ensure_ascii=False
                    ) + "\n"
            status = "success"
        except GeneratorExit:
            status = "cancelled"
            raise
        except Exception as error:
            status = "error"
            error_message = str(error)
            yield json.dumps(
                {"type": "error", "message": "模型服务暂时不可用，请稍后重试"},
                ensure_ascii=False,
            ) + "\n"
        finally:
            finish_query_log(
                log_id,
                status=status,
                model_ms=(time.perf_counter() - model_started_at) * 1000,
                total_ms=(time.perf_counter() - started_at) * 1000,
                usage=usage,
                error=error_message,
            )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson"
    )


@app.get("/knowledge-bases")
def get_knowledge_bases(user=Depends(get_current_user)):
    default = ensure_default_knowledge_base(user["id"])
    assign_unscoped_documents(user["id"], default["id"])
    migrate_existing_documents()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM knowledge_bases WHERE user_id = ? ORDER BY created_at",
            (user["id"],),
        ).fetchall()
    return {"knowledge_bases": [dict(row) for row in rows]}


@app.post("/knowledge-bases")
def create_knowledge_base(
    request: KnowledgeBaseRequest,
    user=Depends(get_current_user),
):
    name = request.name.strip()
    if not name or len(name) > 40:
        raise HTTPException(status_code=400, detail="知识库名称应为1至40个字符")
    knowledge_base_id = str(uuid.uuid4())
    try:
        with get_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM knowledge_bases WHERE user_id = ?",
                (user["id"],),
            ).fetchone()[0]
            if count >= 20:
                raise HTTPException(status_code=400, detail="最多创建20个知识库")
            connection.execute(
                "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?)",
                (
                    knowledge_base_id,
                    user["id"],
                    name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception as error:
        if "UNIQUE constraint failed" in str(error):
            raise HTTPException(status_code=409, detail="知识库名称已存在")
        raise
    return {
        "knowledge_base": {
            "id": knowledge_base_id,
            "user_id": user["id"],
            "name": name,
        }
    }


@app.delete("/knowledge-bases/{knowledge_base_id}")
def remove_knowledge_base(
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    with get_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_bases WHERE user_id = ?",
            (user["id"],),
        ).fetchone()[0]
        if count <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个知识库")

    with get_connection() as connection:
        jobs = connection.execute(
            "SELECT id, stored_path FROM document_jobs WHERE user_id = ? AND knowledge_base_id = ?",
            (user["id"], knowledge_base_id),
        ).fetchall()
        connection.execute(
            "DELETE FROM document_jobs WHERE user_id = ? AND knowledge_base_id = ?",
            (user["id"], knowledge_base_id),
        )
    for job in jobs:
        delete_document(job["id"])
        if job["stored_path"]:
            Path(job["stored_path"]).unlink(missing_ok=True)
        for file_path in UPLOAD_DIR.glob(f"{job['id']}.*"):
            file_path.unlink(missing_ok=True)

    with get_connection() as connection:
        connection.execute(
            "DELETE FROM query_logs WHERE user_id = ? AND knowledge_base_id = ?",
            (user["id"], knowledge_base_id),
        )
        connection.execute(
            "DELETE FROM knowledge_bases WHERE id = ? AND user_id = ?",
            (knowledge_base_id, user["id"]),
        )
    return {"message": "知识库已删除"}


@app.get("/observability/summary")
def get_observability_summary(
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    with get_connection() as connection:
        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS requests,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN status IN ('error', 'cancelled') THEN 1 ELSE 0 END) AS failures,
                AVG(CASE WHEN status = 'success' THEN retrieval_ms END) AS avg_retrieval_ms,
                AVG(CASE WHEN status = 'success' THEN model_ms END) AS avg_model_ms,
                AVG(CASE WHEN status = 'success' THEN total_ms END) AS avg_total_ms,
                SUM(total_tokens) AS total_tokens
            FROM query_logs
            WHERE user_id = ? AND knowledge_base_id = ?
            """,
            (user["id"], knowledge_base_id),
        ).fetchone()
        recent = connection.execute(
            """
            SELECT id, question, status, retrieval_ms, model_ms, total_ms,
                   prompt_tokens, completion_tokens, total_tokens,
                   sources_json, error, created_at
            FROM query_logs
            WHERE user_id = ? AND knowledge_base_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (user["id"], knowledge_base_id),
        ).fetchall()

    summary_data = dict(summary)
    for key in ("requests", "successes", "failures", "total_tokens"):
        summary_data[key] = summary_data.get(key) or 0
    for key in ("avg_retrieval_ms", "avg_model_ms", "avg_total_ms"):
        summary_data[key] = round(summary_data.get(key) or 0, 2)

    recent_data = []
    for row in recent:
        item = dict(row)
        sources = json.loads(item.pop("sources_json") or "[]")
        item["source_count"] = len(sources)
        item["top_score"] = sources[0].get("score") if sources else None
        recent_data.append(item)
    return {"summary": summary_data, "recent": recent_data}


@app.get("/documents")
def get_documents(
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, filename, status, stage, error, chunks, created_at, updated_at
            FROM document_jobs
            WHERE user_id = ? AND knowledge_base_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"], knowledge_base_id),
        ).fetchall()
    return {"documents": [dict(row) for row in rows]}


@app.delete("/documents/{file_id}")
def remove_document(
    file_id: str,
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    with get_connection() as connection:
        document = connection.execute(
            "SELECT * FROM document_jobs WHERE id = ? AND user_id = ? AND knowledge_base_id = ?",
            (file_id, user["id"], knowledge_base_id),
        ).fetchone()
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    with get_connection() as connection:
        connection.execute("DELETE FROM document_jobs WHERE id = ?", (file_id,))
    delete_document(file_id)
    if document["stored_path"]:
        Path(document["stored_path"]).unlink(missing_ok=True)
    for file_path in UPLOAD_DIR.glob(f"{file_id}.*"):
        file_path.unlink(missing_ok=True)

    return {"message": "文档已删除"}


@app.post("/upload", status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(...),
    user=Depends(get_current_user),
):

    get_owned_knowledge_base(knowledge_base_id, user["id"])

    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")

    suffix = Path(file.filename).suffix.lower()

    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(
            status_code=400,
            detail="目前只支持 PDF、Word（.docx）文件"
        )

    file_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{file_id}{suffix}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer
        )

    content_hash = file_sha256(file_path)
    with get_connection() as connection:
        duplicate = connection.execute(
            """
            SELECT id, filename, status FROM document_jobs
            WHERE user_id = ? AND knowledge_base_id = ? AND content_hash = ?
              AND status IN ('pending', 'processing', 'ready')
            LIMIT 1
            """,
            (user["id"], knowledge_base_id, content_hash),
        ).fetchone()
        if duplicate:
            file_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail=f"相同内容的文档“{duplicate['filename']}”已存在",
            )

        timestamp = utc_now()
        connection.execute(
            """
            INSERT INTO document_jobs
            (id, user_id, knowledge_base_id, filename, stored_path, content_hash,
             status, stage, error, chunks, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', '等待处理', NULL, 0, ?, ?)
            """,
            (
                file_id,
                user["id"],
                knowledge_base_id,
                file.filename,
                str(file_path),
                content_hash,
                timestamp,
                timestamp,
            ),
        )

    schedule_document_job(file_id)

    return {
        "message": "文件已接收，正在后台处理",
        "id": file_id,
        "filename": file.filename,
        "status": "pending",
        "stage": "等待处理",
    }


@app.post("/documents/{file_id}/retry", status_code=202)
def retry_document(
    file_id: str,
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    with get_connection() as connection:
        document = connection.execute(
            "SELECT * FROM document_jobs WHERE id = ? AND user_id = ? AND knowledge_base_id = ?",
            (file_id, user["id"], knowledge_base_id),
        ).fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        if document["status"] != "failed":
            raise HTTPException(status_code=400, detail="只有处理失败的文档可以重试")
        if not document["stored_path"] or not Path(document["stored_path"]).exists():
            raise HTTPException(status_code=400, detail="原始文件已丢失，请重新上传")
        connection.execute(
            "UPDATE document_jobs SET status = 'pending', stage = '等待重试', error = NULL, updated_at = ? WHERE id = ?",
            (utc_now(), file_id),
        )
    schedule_document_job(file_id)
    return {"message": "已重新提交处理", "id": file_id}
