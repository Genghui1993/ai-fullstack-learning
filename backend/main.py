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

    context = "\n".join(
        result["documents"][0]
    )



    # 4. 拼接给AI的提示词

    prompt = f"""
        你是一个企业知识库助手。

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

    def generate():

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "user",
                    "content": request.message
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