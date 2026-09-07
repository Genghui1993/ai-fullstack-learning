from rag.loader import load_pdf
from rag.splitter import split_text
from rag.vector_store import add_documents
from fastapi import UploadFile, File
import shutil
import uuid
from rag.embedding import embed_texts
from rag.vector_store import search
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
from fastapi.responses import StreamingResponse


load_dotenv()


app = FastAPI()

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
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


class ChatRequest(BaseModel):
    message: str



@app.get("/")
def root():
    return {
        "message": "AI backend running"
    }



@app.post("/chat")
def chat(request: ChatRequest):


    # 1. 用户问题转向量

    question_vector = embed_texts(
        [
            request.message
        ]
    )[0]



    # 2. 去知识库搜索

    result = search(
        question_vector
    )



    # 3. 获取相关资料
    docs = result["documents"][0] if result.get("documents") else []
    context = "\n".join(docs) if docs else "（知识库为空，暂无资料）"



    # 4. 拼接给AI的提示词

    prompt = f"""
        你是一个个人知识库助手。

        请根据下面资料回答问题。

        资料：
        {context}


        用户问题：
        {request.message}


        如果资料没有答案，请告诉用户不知道。
        """



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
         "answer": response.choices[0].message.content
    }

@app.post("/chat/stream")
def chat_stream(request: ChatRequest):

    # 1. 用户问题转向量
    question_vector = embed_texts(
        [request.message]
    )[0]

    # 2. 去知识库搜索
    result = search(
        question_vector
    )

    # 3. 获取相关资料
    docs = result["documents"][0] if result.get("documents") else []
    context = "\n".join(docs) if docs else "（知识库为空，暂无资料）"

    # 4. 构造 Prompt
    prompt = f"""
        你是一个个人知识库助手。

        请严格根据下面的知识库资料回答用户问题。

        知识库资料：
        {context}

        用户问题：
        {request.message}

        如果知识库资料中没有答案，请明确告诉用户“知识库中没有找到相关信息”，不要自己编造答案。
        """

    # 5. 调用 DeepSeek，并开启流式输出
    def generate():

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            stream=True
        )

        for chunk in response:

            content = chunk.choices[0].delta.content

            if content:
                yield content

    return StreamingResponse(
        generate(),
        media_type="text/plain"
    )
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {
            "message": "目前只支持 PDF 文件",
            "filename": file.filename,
            "chunks": 0
        }

    file_id = str(uuid.uuid4())

    file_path = f"uploads/{file_id}.pdf"


    with open(file_path, "wb") as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )


    # 1.读取PDF

    text = load_pdf(
        file_path
    )


    # 2.切chunk

    chunks = split_text(
        text
    )


    # 3.生成向量

    embeddings = embed_texts(
        chunks
    )


    # 4.存入Chroma

    add_documents(
        chunks,
        embeddings,
        filename=file.filename
    )


    return {
        "message":"上传并入库成功",
        "filename":file.filename,
        "chunks":len(chunks)
    }