# 个人知识库助手

一个可上传 PDF、Word 文档并基于资料回答问题的 RAG 应用。项目包含文档管理、向量检索、流式回答和回答来源展示。

## 技术栈

- 前端：React、TypeScript、Vite、React Markdown
- 后端：FastAPI、DeepSeek API
- RAG：BAAI/bge-small-zh、ChromaDB
- 文档解析：pypdf、python-docx

## 功能

- 上传 PDF、DOCX 并写入知识库
- 查看和删除知识库文档
- 注册、登录，并按用户隔离文档与检索结果
- 每个用户可创建、切换和删除多个相互隔离的知识库空间
- 文档上传后在后台解析和向量化，展示处理阶段、失败原因并支持重试
- 通过内容指纹阻止同一知识库重复上传相同文件
- 基于知识库进行流式问答
- 按页面与段落结构切分 PDF，按标题结构切分 Word
- 展示回答所参考的文件、页码、标题、匹配分和原文摘要
- 按知识库查看成功率、检索/模型耗时、Token 与来源命中记录
- 浏览器本地保存聊天记录

## 本地启动

### 1. 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 DEEPSEEK_API_KEY
uvicorn main:app --reload --port 8000
```

首次启动会下载中文 Embedding 模型，所需时间取决于网络环境。

### 2. 启动前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

浏览器访问 `http://localhost:5173`。

## 环境变量

| 位置 | 变量 | 说明 |
| --- | --- | --- |
| `backend/.env` | `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `backend/.env` | `AUTH_SECRET` | 生产环境的登录令牌签名密钥；本地可自动生成 |
| `frontend/.env.local` | `VITE_API_BASE_URL` | 后端地址，默认 `http://localhost:8000` |

## 数据目录

- 原始上传文件保存在 `backend/uploads/`
- ChromaDB 数据保存在 `backend/chroma/`
- 以上目录以及 `.env` 已被 Git 忽略，不应提交密钥或用户资料

## 检查命令

```bash
cd frontend
npm run lint
npm run build
```

后端接口文档：启动服务后访问 `http://localhost:8000/docs`。

## 重建已有文档索引

解析、切片或 Embedding 策略升级后，可用原上传文件重建全部索引：

```bash
cd backend
source .venv/bin/activate
python reindex_documents.py
```
