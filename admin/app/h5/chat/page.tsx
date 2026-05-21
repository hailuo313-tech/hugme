"use client";

import { useEffect, useState, useRef } from "react";

interface TypingStatus {
  user_id: string;
  is_typing: boolean;
  timestamp: string;
}

export default function H5ChatPage() {
  const [userId] = useState("user_demo_001"); // 演示用户 ID
  const [conversationId] = useState("conv_demo_001"); // 演示会话 ID
  const [isConnected, setIsConnected] = useState(false);
  const [typingStatus, setTypingStatus] = useState<TypingStatus | null>(null);
  const [messages, setMessages] = useState<Array<{ id: string; text: string; sender: string }>>([
    { id: "1", text: "你好！", sender: "other" },
    { id: "2", text: "你好，有什么可以帮助你的吗？", sender: "me" },
  ]);
  const [inputText, setInputText] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // WebSocket 连接
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/h5/chat?user_id=${userId}&conversation_id=${conversationId}`;
    
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      console.log("H5 WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        
        switch (msg.type) {
          case "connection.ready":
            console.log("H5 WebSocket ready:", msg);
            break;
          
          case "typing.status":
            setTypingStatus({
              user_id: msg.user_id,
              is_typing: msg.is_typing,
              timestamp: msg.timestamp,
            });
            break;
          
          case "pong":
            console.log("Pong received");
            break;
          
          default:
            console.log("Unknown message type:", msg.type);
        }
      } catch (error) {
        console.error("Failed to parse WebSocket message:", error);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log("H5 WebSocket disconnected");
    };

    ws.onerror = (error) => {
      console.error("H5 WebSocket error:", error);
    };

    // 定期发送 ping 保持连接
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [userId, conversationId]);

  // 发送正在输入状态
  const sendTypingStart = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "typing.start" }));
    }
  };

  const sendTypingStop = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "typing.stop" }));
    }
  };

  // 处理输入变化
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputText(e.target.value);
    
    // 发送正在输入开始
    sendTypingStart();
    
    // 清除之前的定时器
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
    
    // 1秒后发送停止输入
    typingTimeoutRef.current = setTimeout(() => {
      sendTypingStop();
    }, 1000);
  };

  // 发送消息
  const handleSendMessage = () => {
    if (!inputText.trim()) return;
    
    const newMessage = {
      id: Date.now().toString(),
      text: inputText,
      sender: "me" as const,
    };
    
    setMessages([...messages, newMessage]);
    setInputText("");
    sendTypingStop();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-violet-900 via-purple-900 to-indigo-900 flex flex-col">
      {/* 顶部状态栏 */}
      <div className="bg-black/30 backdrop-blur-sm border-b border-white/10 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-white text-sm">
            {isConnected ? "已连接" : "未连接"}
          </span>
        </div>
        <div className="text-white/60 text-xs">
          H5 聊天演示
        </div>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.sender === "me" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 ${
                message.sender === "me"
                  ? "bg-violet-600 text-white"
                  : "bg-white/10 text-white backdrop-blur-sm"
              }`}
            >
              {message.text}
            </div>
          </div>
        ))}
        
        {/* 正在输入动效 */}
        {typingStatus?.is_typing && (
          <div className="flex justify-start">
            <div className="bg-white/10 backdrop-blur-sm rounded-2xl px-4 py-3">
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="bg-black/30 backdrop-blur-sm border-t border-white/10 p-4">
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={inputText}
            onChange={handleInputChange}
            placeholder="输入消息..."
            className="flex-1 bg-white/10 border border-white/20 rounded-full px-4 py-2 text-white placeholder-white/50 focus:outline-none focus:border-violet-500"
          />
          <button
            onClick={handleSendMessage}
            disabled={!inputText.trim()}
            className="bg-violet-600 hover:bg-violet-500 disabled:bg-violet-800 disabled:cursor-not-allowed text-white rounded-full px-6 py-2 transition-colors"
          >
            发送
          </button>
        </div>
      </div>

      {/* 连接状态提示 */}
      {!isConnected && (
        <div className="fixed top-20 left-1/2 transform -translate-x-1/2 bg-red-500/90 text-white px-4 py-2 rounded-lg shadow-lg">
          WebSocket 未连接，请刷新页面重试
        </div>
      )}
    </div>
  );
}