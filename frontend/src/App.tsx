import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";
interface Message {
  role: "user" | "ai";
  content: string;
  time: string;
}


function App() {

  const [input, setInput] = useState("");

  const [messages, setMessages] = useState<Message[]>(()=>{
    const saved = localStorage.getItem("chat_messages")
    return saved ? JSON.parse(saved) : [];
  });

  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);



  useEffect(()=>{

    bottomRef.current?.scrollIntoView({
      behavior:"smooth"
    });

    localStorage.setItem("chat_messages", JSON.stringify(messages));

  },[messages]);



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

      const response = await fetch("http://localhost:8000/upload", {
        method: "POST",
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
        "http://localhost:8000/chat/stream",
        {
          method:"POST",

          headers:{
            "Content-Type":"application/json"
          },

          body:JSON.stringify({
            message:userMessage.content
          })
        }
      );



      const reader = response.body?.getReader();


      const decoder = new TextDecoder();


      let aiContent = "";

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



          const chunk = decoder.decode(
            value,
            {
              stream:true
            }
          );



          aiContent += chunk;



          setMessages(prev=>{


            const newMessages = [
              ...prev
            ];

            const lastMessage = newMessages[
              newMessages.length - 1
            ];

            newMessages[
              newMessages.length - 1
            ] = {

              ...lastMessage,

              content:aiContent

            };



            return newMessages;


          });


        }


      }



    } catch(error){


      console.error(error);



      setMessages(prev=>[

        ...prev,

        {
          role:"ai",
          content:"请求失败，请检查后端服务"
        }

      ]);



    } finally {


      setLoading(false);


    }

  }



  return (

    <div className="chat-container">
      <h1>
        个人知识库
      </h1>
      <p className="subtitle">
        上传资料后，直接提问即可基于知识库回答
      </p>

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
          disabled={uploading}
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