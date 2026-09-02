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


  const bottomRef = useRef<HTMLDivElement>(null);



  useEffect(()=>{

    bottomRef.current?.scrollIntoView({
      behavior:"smooth"
    });

    localStorage.setItem("chat_messages", JSON.stringify(messages));

  },[messages]);



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
        AI Assistant
      </h1>
      <button 
      style={{
        marginBottom: "10px"
      }}
        onClick={()=>{
          setMessages([]);
          localStorage.removeItem(
            "chat_messages"
          );
        }}
        >
        清空对话
      </button>
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