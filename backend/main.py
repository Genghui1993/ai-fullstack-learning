from rag.loader import load_document_sections
from rag.splitter import split_sections
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
from fastapi.responses import StreamingResponse
from auth import (
    ensure_default_knowledge_base,
    get_connection,
    get_current_user,
    router as auth_router,
)


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise RuntimeError(
        "缺少 DEEPSEEK_API_KEY，请复制 backend/.env.example 为 backend/.env 后填写"
    )


app = FastAPI()
app.include_router(auth_router)

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
    get_owned_knowledge_base(request.knowledge_base_id, user["id"])
    context, sources = retrieve_context(
        request.message, user["id"], request.knowledge_base_id
    )
    prompt = build_prompt(request.message, context)



    response = client.chat.completions.create(

        model="deepseek-chat",

        messages=[
            {
                "role":"user",
                "content":prompt
            }
        ]

    )


    return {
         "answer": response.choices[0].message.content,
         "sources": sources,
    }

@app.post("/chat/stream")
def chat_stream(request: ChatRequest, user=Depends(get_current_user)):
    get_owned_knowledge_base(request.knowledge_base_id, user["id"])
    context, sources = retrieve_context(
        request.message, user["id"], request.knowledge_base_id
    )
    prompt = build_prompt(request.message, context)

    # 5. 调用 DeepSeek，并开启流式输出
    def generate():
        yield json.dumps(
            {"type": "sources", "sources": sources}, ensure_ascii=False
        ) + "\n"

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )

            for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield json.dumps(
                        {"type": "token", "content": content}, ensure_ascii=False
                    ) + "\n"
        except Exception:
            yield json.dumps(
                {"type": "error", "message": "模型服务暂时不可用，请稍后重试"},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson"
    )


@app.get("/knowledge-bases")
def get_knowledge_bases(user=Depends(get_current_user)):
    default = ensure_default_knowledge_base(user["id"])
    assign_unscoped_documents(user["id"], default["id"])
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

    documents = list_documents(user["id"], knowledge_base_id)
    for document in documents:
        delete_document(document["id"])
        for file_path in UPLOAD_DIR.glob(f"{document['id']}.*"):
            file_path.unlink(missing_ok=True)

    with get_connection() as connection:
        connection.execute(
            "DELETE FROM knowledge_bases WHERE id = ? AND user_id = ?",
            (knowledge_base_id, user["id"]),
        )
    return {"message": "知识库已删除"}


@app.get("/documents")
def get_documents(
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    return {
        "documents": list_documents(user["id"], knowledge_base_id)
    }


@app.delete("/documents/{file_id}")
def remove_document(
    file_id: str,
    knowledge_base_id: str,
    user=Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, user["id"])
    documents = {
        item["id"]: item
        for item in list_documents(user["id"], knowledge_base_id)
    }
    if file_id not in documents:
        raise HTTPException(status_code=404, detail="文档不存在")

    delete_document(file_id)
    for file_path in UPLOAD_DIR.glob(f"{file_id}.*"):
        file_path.unlink(missing_ok=True)

    return {"message": "文档已删除"}


@app.post("/upload")
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

    try:
        sections = load_document_sections(str(file_path))
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败，请确认是有效的 PDF 或 Word（.docx）：{e}"
        )

    if not sections:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="文件中没有可提取的文本"
        )

    chunks = split_sections(sections)
    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(texts)

    add_documents(
        texts,
        embeddings,
        filename=file.filename,
        file_id=file_id,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        chunk_metadatas=chunks,
        user_id=user["id"],
        knowledge_base_id=knowledge_base_id,
    )

    return {
        "message": "上传并入库成功",
        "id": file_id,
        "filename": file.filename,
        "chunks": len(chunks)
    }
