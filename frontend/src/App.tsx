import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

type Source = {
  filename: string;
  chunk_index: number;
  page?: number;
  title?: string;
  score?: number;
  excerpt: string;
};

type Message = {
  role: "user" | "ai";
  content: string;
  time: string;
  sources?: Source[];
};

type DocumentItem = {
  id: string;
  filename: string;
  chunks: number;
  status: "pending" | "processing" | "ready" | "failed";
  stage: string;
  error?: string;
};

type KnowledgeBase = { id: string; name: string };
type User = { id: string; username: string };

type Observability = {
  summary: {
    requests: number;
    successes: number;
    failures: number;
    avg_retrieval_ms: number;
    avg_model_ms: number;
    avg_total_ms: number;
    total_tokens: number;
  };
  recent: Array<{
    id: string;
    question: string;
    status: "processing" | "success" | "error" | "cancelled";
    retrieval_ms: number;
    model_ms: number | null;
    total_tokens: number;
    source_count: number;
    top_score: number | null;
    error?: string;
  }>;
};

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.PROD ? "/api" : "http://localhost:8000");
const EXAMPLE_QUESTIONS = [
  "这份资料的核心内容是什么？",
  "请列出其中最重要的规则",
  "有哪些需要特别注意的例外？",
];

function readJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function chatStore() {
  return readJson<Record<string, Message[]>>("chat_messages_by_kb", {});
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("auth_token") ?? "");
  const [user, setUser] = useState<User | null>(() => readJson<User | null>("auth_user", null));
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [showData, setShowData] = useState(false);
  const [observability, setObservability] = useState<Observability | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const headers = useCallback(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const activateKnowledgeBase = useCallback((id: string) => {
    setKnowledgeBaseId(id);
    setMessages(chatStore()[id] ?? []);
    setNotice("");
    localStorage.setItem("knowledge_base_id", id);
  }, []);

  const loadKnowledgeBases = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/knowledge-bases`, { headers: headers() });
    if (!response.ok) throw new Error("加载知识库失败");
    const items: KnowledgeBase[] = (await response.json()).knowledge_bases ?? [];
    setKnowledgeBases(items);
    const saved = localStorage.getItem("knowledge_base_id");
    const nextId = items.some((item) => item.id === saved) ? saved! : items[0]?.id ?? "";
    const legacyMessages = readJson<Message[]>("chat_messages", []);
    if (nextId && legacyMessages.length && !chatStore()[nextId]?.length) {
      localStorage.setItem("chat_messages_by_kb", JSON.stringify({ ...chatStore(), [nextId]: legacyMessages }));
      localStorage.removeItem("chat_messages");
    }
    activateKnowledgeBase(nextId);
  }, [activateKnowledgeBase, headers]);

  const loadDocuments = useCallback(async () => {
    if (!knowledgeBaseId) return setDocuments([]);
    const response = await fetch(
      `${API_BASE_URL}/documents?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      { headers: headers() },
    );
    if (response.ok) setDocuments((await response.json()).documents ?? []);
  }, [headers, knowledgeBaseId]);

  const loadObservability = useCallback(async () => {
    if (!knowledgeBaseId) return setObservability(null);
    const response = await fetch(
      `${API_BASE_URL}/observability/summary?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      { headers: headers() },
    );
    if (response.ok) setObservability(await response.json());
  }, [headers, knowledgeBaseId]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => void loadKnowledgeBases().catch(console.error), 0);
    return () => window.clearTimeout(timer);
  }, [loadKnowledgeBases, token]);

  useEffect(() => {
    if (!token || !knowledgeBaseId) return;
    const timer = window.setTimeout(() => {
      void loadDocuments();
      void loadObservability();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [knowledgeBaseId, loadDocuments, loadObservability, token]);

  useEffect(() => {
    if (!documents.some((item) => item.status === "pending" || item.status === "processing")) return;
    const timer = window.setInterval(() => void loadDocuments(), 1500);
    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  useEffect(() => {
    if (!knowledgeBaseId) return;
    const stored = chatStore();
    stored[knowledgeBaseId] = messages;
    localStorage.setItem("chat_messages_by_kb", JSON.stringify(stored));
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [knowledgeBaseId, messages]);

  async function submitAuth() {
    if (!username.trim() || !password) return setAuthError("请填写用户名和密码");
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = await fetch(`${API_BASE_URL}/auth/${authMode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) return setAuthError(data?.detail ?? "操作失败，请检查输入");
      localStorage.setItem("auth_token", data.token);
      localStorage.setItem("auth_user", JSON.stringify(data.user));
      setToken(data.token);
      setUser(data.user);
      setPassword("");
    } catch {
      setAuthError("暂时无法连接服务，请稍后重试");
    } finally {
      setAuthLoading(false);
    }
  }

  function logout() {
    ["auth_token", "auth_user", "knowledge_base_id"].forEach((key) => localStorage.removeItem(key));
    setToken("");
    setUser(null);
    setKnowledgeBases([]);
    setKnowledgeBaseId("");
    setMessages([]);
  }

  async function createKnowledgeBase() {
    const name = window.prompt("请输入知识库名称（最多 40 个字符）")?.trim();
    if (!name) return;
    const response = await fetch(`${API_BASE_URL}/knowledge-bases`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ name }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) return setNotice(data?.detail ?? "创建失败");
    await loadKnowledgeBases();
    activateKnowledgeBase(data.knowledge_base.id);
  }

  async function deleteCurrentKnowledgeBase() {
    const current = knowledgeBases.find((item) => item.id === knowledgeBaseId);
    if (!current || !window.confirm(`删除“${current.name}”及其中全部资料？此操作不可恢复。`)) return;
    const response = await fetch(`${API_BASE_URL}/knowledge-bases/${current.id}`, {
      method: "DELETE",
      headers: headers(),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) return setNotice(data?.detail ?? "删除失败");
    const stored = chatStore();
    delete stored[current.id];
    localStorage.setItem("chat_messages_by_kb", JSON.stringify(stored));
    await loadKnowledgeBases();
  }

  async function uploadFile(file: File) {
    if (!/\.(pdf|docx)$/i.test(file.name)) return setNotice("目前仅支持 PDF 和 Word（.docx）");
    setUploading(true);
    setNotice(`正在上传 ${file.name}…`);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("knowledge_base_id", knowledgeBaseId);
      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: "POST",
        headers: headers(),
        body: formData,
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) return setNotice(data?.detail ?? "上传失败");
      setNotice("上传成功，正在后台解析和建立索引");
      await loadDocuments();
    } catch {
      setNotice("上传失败，请检查网络后重试");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function deleteDocument(document: DocumentItem) {
    if (!window.confirm(`确定删除“${document.filename}”吗？`)) return;
    const response = await fetch(
      `${API_BASE_URL}/documents/${document.id}?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      { method: "DELETE", headers: headers() },
    );
    if (!response.ok) return setNotice("删除失败，请稍后重试");
    setNotice(`已删除 ${document.filename}`);
    await loadDocuments();
  }

  async function retryDocument(document: DocumentItem) {
    const response = await fetch(
      `${API_BASE_URL}/documents/${document.id}/retry?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      { method: "POST", headers: headers() },
    );
    const data = await response.json().catch(() => null);
    if (!response.ok) return setNotice(data?.detail ?? "重新处理失败");
    setNotice("已重新提交处理");
    await loadDocuments();
  }

  async function sendMessage() {
    const question = input.trim();
    if (!question || loading || !knowledgeBaseId) return;
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setMessages((current) => [...current, { role: "user", content: question, time }]);
    setInput("");
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ message: question, knowledge_base_id: knowledgeBaseId }),
      });
      if (!response.ok || !response.body) throw new Error();
      setMessages((current) => [...current, { role: "ai", content: "", time }]);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = "";
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "token") answer += event.content;
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              content: event.type === "error" ? event.message : answer,
              sources: event.type === "sources" ? event.sources : last.sources,
            };
            return next;
          });
        }
      }
    } catch {
      setMessages((current) => [
        ...current,
        { role: "ai", content: "请求失败，请检查网络后重试。", time },
      ]);
    } finally {
      setLoading(false);
      await loadObservability();
    }
  }

  if (!token) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="brand-mark">知</div>
          <p className="eyebrow">KNOWLEDGE COPILOT</p>
          <h1>让资料真正回答问题</h1>
          <p className="auth-description">上传企业制度、产品手册或个人资料，获得带来源、可追溯的 AI 回答。</p>
          <div className="auth-tabs" role="tablist">
            <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>登录</button>
            <button className={authMode === "register" ? "active" : ""} onClick={() => setAuthMode("register")}>创建账号</button>
          </div>
          <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="至少 3 个字符" autoComplete="username" /></label>
          <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 个字符" autoComplete={authMode === "login" ? "current-password" : "new-password"} onKeyDown={(event) => event.key === "Enter" && void submitAuth()} /></label>
          {authError && <p className="form-error" role="alert">{authError}</p>}
          <button className="primary-button auth-submit" disabled={authLoading} onClick={() => void submitAuth()}>
            {authLoading ? "请稍候…" : authMode === "login" ? "进入知识库" : "创建并进入"}
          </button>
          <p className="privacy-note">你的文档和检索结果按账号隔离保存</p>
        </section>
      </main>
    );
  }

  const readyCount = documents.filter((item) => item.status === "ready").length;
  const currentName = knowledgeBases.find((item) => item.id === knowledgeBaseId)?.name ?? "知识库";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark small">知</span><div><strong>知问</strong><small>知识库助手</small></div></div>
        <div className="account"><span className="online-dot" />{user?.username}<button className="text-button" onClick={logout}>退出</button></div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="section-label"><span>知识空间</span><button className="icon-button" title="新建知识库" onClick={() => void createKnowledgeBase()}>＋</button></div>
          <select className="kb-select" aria-label="当前知识库" value={knowledgeBaseId} onChange={(event) => activateKnowledgeBase(event.target.value)}>
            {knowledgeBases.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <div className="sidebar-actions">
            <button onClick={() => setShowData((value) => !value)}>{showData ? "返回文档" : "运行数据"}</button>
            <button className="danger-link" disabled={knowledgeBases.length <= 1} onClick={() => void deleteCurrentKnowledgeBase()}>删除空间</button>
          </div>

          {showData && observability ? (
            <section className="data-panel">
              <div className="metric-grid">
                <div><strong>{observability.summary.requests}</strong><span>总问答</span></div>
                <div><strong>{observability.summary.requests ? Math.round(observability.summary.successes / observability.summary.requests * 100) : 0}%</strong><span>成功率</span></div>
                <div><strong>{Math.round(observability.summary.avg_total_ms)}</strong><span>平均毫秒</span></div>
                <div><strong>{observability.summary.total_tokens}</strong><span>Token</span></div>
              </div>
              <button className="refresh-button" onClick={() => void loadObservability()}>刷新数据</button>
              <div className="recent-list">
                {observability.recent.slice(0, 8).map((item) => (
                  <div key={item.id}><span>{item.question}</span><small className={item.status}>{item.status === "success" ? "成功" : item.status === "processing" ? "处理中" : "失败"}</small></div>
                ))}
                {!observability.recent.length && <p className="muted">暂无问答数据</p>}
              </div>
            </section>
          ) : (
            <>
              <div className="document-heading"><span>资料 · {readyCount}/{documents.length}</span><button className="upload-button" disabled={uploading} onClick={() => fileInputRef.current?.click()}>{uploading ? "上传中" : "上传"}</button></div>
              <input ref={fileInputRef} className="visually-hidden" type="file" accept=".pdf,.docx" onChange={(event) => event.target.files?.[0] && void uploadFile(event.target.files[0])} />
              {notice && <p className="notice">{notice}</p>}
              <div className="document-list">
                {documents.map((document) => (
                  <article className="document-card" key={document.id}>
                    <div className="file-icon">{document.filename.toLowerCase().endsWith(".pdf") ? "PDF" : "DOC"}</div>
                    <div className="document-copy"><strong title={document.filename}>{document.filename}</strong><small className={document.status}>{document.status === "ready" ? `${document.chunks} 个片段 · 可问答` : document.stage}</small></div>
                    <div className="document-menu">
                      {document.status === "failed" && <button onClick={() => void retryDocument(document)}>重试</button>}
                      <button onClick={() => void deleteDocument(document)}>删除</button>
                    </div>
                  </article>
                ))}
                {!documents.length && <div className="sidebar-empty"><span>＋</span><p>还没有资料</p><small>上传 PDF 或 Word 开始</small></div>}
              </div>
            </>
          )}
        </aside>

        <section className="chat-area">
          <header className="chat-header">
            <div><p className="eyebrow">CURRENT SPACE</p><h1>{currentName}</h1></div>
            <button className="secondary-button" disabled={!messages.length} onClick={() => setMessages([])}>清空对话</button>
          </header>

          <div className="messages" aria-live="polite">
            {!messages.length && (
              <div className="chat-empty">
                <div className="empty-orb">AI</div>
                <h2>{readyCount ? "资料已就绪，可以开始提问" : "先上传资料，再开始提问"}</h2>
                <p>{readyCount ? `我会从 ${readyCount} 份资料中检索，并标注回答来源。` : "支持 PDF 和 Word，上传后会自动解析并建立索引。"}</p>
                {readyCount > 0 && <div className="suggestions">{EXAMPLE_QUESTIONS.map((question) => <button key={question} onClick={() => setInput(question)}>{question}<span>→</span></button>)}</div>}
              </div>
            )}
            {messages.map((message, index) => (
              <article className={`message ${message.role}`} key={`${message.time}-${index}`}>
                <div className="avatar">{message.role === "user" ? "你" : "知"}</div>
                <div className="message-body">
                  <div className="message-meta"><strong>{message.role === "user" ? "你" : "知识助手"}</strong><time>{message.time}</time></div>
                  <div className="message-content">{message.role === "ai" ? <ReactMarkdown>{message.content || "正在检索和组织答案…"}</ReactMarkdown> : <p>{message.content}</p>}</div>
                  {!!message.sources?.length && <details className="sources"><summary>参考来源 · {message.sources.length} 条</summary>{message.sources.map((source, sourceIndex) => <div className="source-item" key={`${source.filename}-${source.chunk_index}-${sourceIndex}`}><strong>{source.filename}</strong><span>{source.page ? `第 ${source.page} 页` : `片段 ${source.chunk_index}`}{source.score !== undefined ? ` · 匹配 ${source.score}` : ""}</span>{source.title && <em>{source.title}</em>}<p>{source.excerpt}</p></div>)}</details>}
                </div>
              </article>
            ))}
            <div ref={bottomRef} />
          </div>

          <footer className="composer">
            <textarea aria-label="输入问题" value={input} onChange={(event) => setInput(event.target.value)} placeholder={readyCount ? "向知识库提问…" : "上传资料后即可提问"} rows={1} disabled={!readyCount} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); } }} />
            <button className="send-button" aria-label="发送问题" disabled={!input.trim() || loading || !readyCount} onClick={() => void sendMessage()}>{loading ? <span className="spinner" /> : "↑"}</button>
            <small>Enter 发送 · Shift + Enter 换行 · 回答仅基于当前知识库</small>
          </footer>
        </section>
      </div>
    </main>
  );
}

export default App;
