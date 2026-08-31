from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os


load_dotenv()


app = FastAPI()


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

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role":"system",
                "content":"你是一个专业AI助手，请用中文回答问题"
            },
            {
                "role": "user",
                "content": request.message
            }
        ]
    )


    return {
        "answer": response.choices[0].message.content
    }