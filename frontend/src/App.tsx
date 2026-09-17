import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";
interface Message {
  role: "user" | "ai";
  content: string;
  time: string;
  sources?: Source[];
}

interface Source {
  filename: string;
  chunk_index: number;
  page?: number;
  title?: string;
  score?: number;
  excerpt: string;
}

interface DocumentItem {
  id: string;
  filename: string;
  chunks: number;
  uploaded_at: string;
}

interface User {
  id: string;
  username: string;
}

interface KnowledgeBase {
  id: string;
  name: string;
  created_at?: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";


function App() {

  const [token, setToken] = useState(() => localStorage.getItem("auth_token") ?? "");
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem("auth_user");
    return saved ? JSON.parse(saved) : null;
  });
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [input, setInput] = useState("");

  const [messages, setMessages] = useState<Message[]>(()=>{
    const saved = localStorage.getItem("chat_messages")
    return saved ? JSON.parse(saved) : [];
  });

  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const authorizationHeaders = useCallback(() => ({
    Authorization: `Bearer ${token}`,
  }), [token]);

  const loadDocuments = useCallback(async () => {
    if (!knowledgeBaseId) {
      setDocuments([]);
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/documents?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`, {
        headers: authorizationHeaders(),
      });
      if (!response.ok) throw new Error("加载文档失败");
      const data = await response.json();
      setDocuments(data.documents ?? []);
    } catch (error) {
      console.error(error);
    }
  }, [authorizationHeaders, knowledgeBaseId]);

  const loadKnowledgeBases = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/knowledge-bases`, {
      headers: authorizationHeaders(),
    });
    if (!response.ok) throw new Error("加载知识库失败");
    const data = await response.json();
    const items: KnowledgeBase[] = data.knowledge_bases ?? [];
    setKnowledgeBases(items);
    setKnowledgeBaseId(current => {
      const saved = localStorage.getItem("knowledge_base_id");
      if (items.some(item => item.id === current)) return current;
      if (saved && items.some(item => item.id === saved)) return saved;
      return items[0]?.id ?? "";
    });
  }, [authorizationHeaders]);



  useEffect(()=>{

    bottomRef.current?.scrollIntoView({
      behavior:"smooth"
    });

    localStorage.setItem("chat_messages", JSON.stringify(messages));

  },[messages]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => void loadKnowledgeBases(), 0);
    return () => window.clearTimeout(timer);
  }, [token, loadKnowledgeBases]);

  useEffect(() => {
    if (!token || !knowledgeBaseId) return;
    localStorage.setItem("knowledge_base_id", knowledgeBaseId);
    const timer = window.setTimeout(() => void loadDocuments(), 0);
    return () => window.clearTimeout(timer);
  }, [token, knowledgeBaseId, loadDocuments]);

  async function submitAuth() {
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = await fetch(`${API_BASE_URL}/auth/${authMode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        setAuthError(data?.detail ?? "操作失败，请检查输入");
        return;
      }
      localStorage.setItem("auth_token", data.token);
      localStorage.setItem("auth_user", JSON.stringify(data.user));
      setToken(data.token);
      setUser(data.user);
      setPassword("");
    } catch (error) {
      console.error(error);
      setAuthError("无法连接后端服务");
    } finally {
      setAuthLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    localStorage.removeItem("chat_messages");
    setToken("");
    setUser(null);
    setMessages([]);
    setDocuments([]);
    setKnowledgeBases([]);
    setKnowledgeBaseId("");
  }

  function switchKnowledgeBase(nextId: string) {
    setKnowledgeBaseId(nextId);
    setMessages([]);
    localStorage.removeItem("chat_messages");
    setUploadStatus("");
  }

  async function createKnowledgeBase() {
    const name = window.prompt("请输入新知识库名称（最多40个字符）")?.trim();
    if (!name) return;
    const response = await fetch(`${API_BASE_URL}/knowledge-bases`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authorizationHeaders() },
      body: JSON.stringify({ name }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      setUploadStatus(data?.detail ?? "创建知识库失败");
      return;
    }
    await loadKnowledgeBases();
    switchKnowledgeBase(data.knowledge_base.id);
  }

  async function deleteCurrentKnowledgeBase() {
    const current = knowledgeBases.find(item => item.id === knowledgeBaseId);
    if (!current || !window.confirm(`删除“${current.name}”及其中全部文档？此操作不可恢复。`)) return;
    const response = await fetch(`${API_BASE_URL}/knowledge-bases/${current.id}`, {
      method: "DELETE",
      headers: authorizationHeaders(),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      setUploadStatus(data?.detail ?? "删除知识库失败");
      return;
    }
    setKnowledgeBaseId("");
    setMessages([]);
    localStorage.removeItem("chat_messages");
    await loadKnowledgeBases();
  }

  async function deleteDocument(document: DocumentItem) {
    if (!window.confirm(`确定删除“${document.filename}”吗？`)) return;

    const response = await fetch(`${API_BASE_URL}/documents/${document.id}?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`, {
      method: "DELETE",
      headers: authorizationHeaders(),
    });
    if (!response.ok) {
      setUploadStatus("删除失败，请稍后重试");
      return;
    }
    setUploadStatus(`已删除：${document.filename}`);
    await loadDocuments();
  }



  async function uploadFile(file: File) {
    const name = file.name.toLowerCase();
    if (!name.endsWith(".pdf") && !name.endsWith(".docx")) {
      setUploadStatus("目前只支持 PDF、Word（.docx）");
      return;
    }

    setUploading(true);
    setUploadStatus(`正在上传 ${file.name}...`);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("knowledge_base_id", knowledgeBaseId);

      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: "POST",
        headers: authorizationHeaders(),
        body: formData,
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        const detail =
          data?.detail ||
          "上传失败，请检查文件格式";
        setUploadStatus(typeof detail === "string" ? detail : "上传失败");
        return;
      }

      setUploadStatus(
        `已入库：${data.filename}（${data.chunks} 个片段）`
      );
      await loadDocuments();
    } catch (error) {
      console.error(error);
      setUploadStatus("上传失败，请检查后端服务");
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  async function sendMessage() {

    if (!input.trim() || loading) return;



    const userMessage: Message = {
      role:"user",
      content:input,
      time:new Date().toLocaleTimeString()
    };


    setMessages(prev=>[
      ...prev,
      userMessage
    ]);


    setInput("");

    setLoading(true);



    try {


      const response = await fetch(
        `${API_BASE_URL}/chat/stream`,
        {
          method:"POST",

          headers:{
            "Content-Type":"application/json",
            ...authorizationHeaders(),
          },

          body:JSON.stringify({
            message:userMessage.content,
            knowledge_base_id: knowledgeBaseId,
          })
        }
      );

      if (!response.ok) {
        throw new Error(`请求失败：${response.status}`);
      }



      const reader = response.body?.getReader();


      const decoder = new TextDecoder();


      let aiContent = "";
      let streamBuffer = "";

      // const data = await response.json();

      if(reader){


        setMessages(prev=>[
          ...prev,
          {
            role:"ai",
            content:"",
            time:new Date().toLocaleTimeString()
          }
        ]);



        while(true){


          const {
            done,
            value
          } = await reader.read();



          if(done){
            break;
          }



          streamBuffer += decoder.decode(
            value,
            {
              stream:true
            }
          );

          const lines = streamBuffer.split("\n");
          streamBuffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);

            if (event.type === "token") {
              aiContent += event.content;
            }

            setMessages(prev => {
              const newMessages = [...prev];
              const lastMessage = newMessages[newMessages.length - 1];
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                content: event.type === "error" ? event.message : aiContent,
                sources: event.type === "sources" ? event.sources : lastMessage.sources,
              };
              return newMessages;
            });
          }


        }


      }



    } catch(error){


      console.error(error);



      setMessages(prev=>[

        ...prev,

        {
          role:"ai",
          content:"请求失败，请检查后端服务",
          time:new Date().toLocaleTimeString()
        }

      ]);



    } finally {


      setLoading(false);


    }

  }



  return (

    !token ? (
      <div className="auth-container">
        <h1>个人知识库</h1>
        <p className="subtitle">登录后管理你的私有资料</p>
        <div className="auth-tabs">
          <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>登录</button>
          <button className={authMode === "register" ? "active" : ""} onClick={() => setAuthMode("register")}>注册</button>
        </div>
        <input value={username} onChange={event => setUsername(event.target.value)} placeholder="用户名（至少3个字符）" />
        <input type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="密码（至少8个字符）" onKeyDown={event => { if (event.key === "Enter") void submitAuth(); }} />
        {authError && <p className="auth-error">{authError}</p>}
        <button className="auth-submit" disabled={authLoading} onClick={() => void submitAuth()}>
          {authLoading ? "处理中..." : authMode === "login" ? "登录" : "创建账号"}
        </button>
      </div>
    ) :

    <div className="chat-container">
      <div className="account-bar">
        <span>当前用户：{user?.username}</span>
        <button onClick={logout}>退出登录</button>
      </div>
      <h1>
        个人知识库
      </h1>
      <p className="subtitle">
        上传资料后，直接提问即可基于知识库回答
      </p>

      <section className="knowledge-base-bar">
        <label htmlFor="knowledge-base-select">当前知识库</label>
        <select id="knowledge-base-select" value={knowledgeBaseId} onChange={event => switchKnowledgeBase(event.target.value)}>
          {knowledgeBases.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <button onClick={() => void createKnowledgeBase()}>新建</button>
        <button className="danger-button" disabled={knowledgeBases.length <= 1} onClick={() => void deleteCurrentKnowledgeBase()}>删除空间</button>
      </section>

      <div className="toolbar">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              uploadFile(file);
            }
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading || !knowledgeBaseId}
        >
          {uploading ? "上传中..." : "上传资料"}
        </button>
        <button
          onClick={() => {
            setMessages([]);
            localStorage.removeItem("chat_messages");
          }}
        >
          清空对话
        </button>
      </div>

      {uploadStatus && (
        <p className="upload-status">{uploadStatus}</p>
      )}
      <section className="document-panel">
        <h2>知识库文档</h2>
        {documents.length === 0 ? (
          <p className="empty-text">还没有文档，请先上传资料。</p>
        ) : (
          <ul>
            {documents.map(document => (
              <li key={document.id}>
                <span>{document.filename} · {document.chunks} 个片段</span>
                <button onClick={() => void deleteDocument(document)}>删除</button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="messages">
      {
        messages.map((msg,index)=>(

          <div
            key={index}
            className={`message ${msg.role}`}
          >

            <b>
              {
                msg.role === "user"
                ? "👤 你"
                : "🤖 AI"
              }
            </b>


            <div className="content">

              {
                msg.role === "ai"
                ?
                <ReactMarkdown>
                  {msg.content}
                </ReactMarkdown>
                :
                <p style={{
                  whiteSpace:"pre-wrap"
                }}>
                  {msg.content}
                </p>
              }

            </div>

            {msg.sources && msg.sources.length > 0 && (
              <details className="sources">
                <summary>查看 {msg.sources.length} 条参考来源</summary>
                {msg.sources.map((source, sourceIndex) => (
                  <div className="source-item" key={`${source.filename}-${source.chunk_index}-${sourceIndex}`}>
                    <strong>
                      {source.filename}
                      {source.page ? ` · 第 ${source.page} 页` : ` · 片段 ${source.chunk_index}`}
                      {source.score !== undefined ? ` · 匹配分 ${source.score}` : ""}
                    </strong>
                    {source.title && <span className="source-title">{source.title}</span>}
                    <p>{source.excerpt}</p>
                  </div>
                ))}
              </details>
            )}


            <span className="time">
              {msg.time}
            </span>


          </div>

        ))
      }



        <div ref={bottomRef}></div>


      </div>
      <div className="input-area">
        <input

          value={input}

          onChange={
            (e)=>setInput(e.target.value)
          }


          placeholder="请输入你的问题..."


          onKeyDown={
            (e)=>{

              if(
                e.key==="Enter"
              ){

                sendMessage();

              }

            }
          }

        />



        <button

          onClick={sendMessage}

          disabled={loading}

        >

          {
            loading
            ? "生成中..."
            : "发送"
          }


        </button>



      </div>
    </div>

  );

}


export default App;
