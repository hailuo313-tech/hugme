"use client";

import { type ChangeEvent, useEffect, useRef, useState } from "react";

interface TypingStatus {
  user_id: string;
  is_typing: boolean;
  timestamp: string;
}

interface ChatMessage {
  id: string;
  text: string;
  sender: "me" | "other";
}

interface OrderResponse {
  order_id: string;
  checkout_url: string;
  status: string;
}

const VIP_ORDER_PATH = "/api/v1/orders";
const VIP_PRODUCT_ID = "vip";
const VIP_AMOUNT_CENTS = 499;
const VIP_CURRENCY = "USD";

const vipCopy = {
  title: "Upgrade to VIP",
  subtitle: "Unlock deeper replies and priority care for this chat.",
  body: [
    "Get a warmer, more complete conversation experience.",
    "Your payment is processed securely by Stripe.",
    "You can close this window and continue chatting anytime.",
  ],
  benefits: [
    "Priority response experience",
    "More complete character replies",
    "VIP profile badge after payment",
  ],
  primaryCta: "Continue to secure payment",
  secondaryCta: "Maybe later",
  trustNote: "Secure checkout powered by Stripe.",
  ageGateNote: "VIP purchase is available only after age verification.",
  blockedMinorMessage: "VIP purchase is not available for this account.",
  errorMessage: "Payment could not be started. Please try again later.",
};

function resolveUserId(): string {
  if (typeof window === "undefined") return "user_demo_001";
  const params = new URLSearchParams(window.location.search);
  return params.get("user_id") || "user_demo_001";
}

function resolveConversationId(): string {
  if (typeof window === "undefined") return "conv_demo_001";
  const params = new URLSearchParams(window.location.search);
  return params.get("conversation_id") || "conv_demo_001";
}

export default function H5ChatPage() {
  const [userId, setUserId] = useState("user_demo_001");
  const [conversationId, setConversationId] = useState("conv_demo_001");
  const [isConnected, setIsConnected] = useState(false);
  const [typingStatus, setTypingStatus] = useState<TypingStatus | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: "1", text: "Hey, I am here.", sender: "other" },
    { id: "2", text: "Tell me what you need today.", sender: "me" },
  ]);
  const [inputText, setInputText] = useState("");
  const [vipModalOpen, setVipModalOpen] = useState(false);
  const [vipCheckoutLoading, setVipCheckoutLoading] = useState(false);
  const [vipCheckoutError, setVipCheckoutError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const typingTimeoutRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setUserId(resolveUserId());
    setConversationId(resolveConversationId());
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/h5/chat?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(conversationId)}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as { type?: string; user_id?: string; is_typing?: boolean; timestamp?: string };

        if (msg.type === "typing.status") {
          setTypingStatus({
            user_id: msg.user_id || "",
            is_typing: Boolean(msg.is_typing),
            timestamp: msg.timestamp || new Date().toISOString(),
          });
        }
      } catch (error) {
        console.error("Failed to parse H5 WebSocket message:", error);
      }
    };

    ws.onclose = () => setIsConnected(false);
    ws.onerror = (error) => console.error("H5 WebSocket error:", error);

    const pingInterval = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => {
      window.clearInterval(pingInterval);
      ws.close();
    };
  }, [userId, conversationId]);

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

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    setInputText(event.target.value);
    sendTypingStart();

    if (typingTimeoutRef.current) {
      window.clearTimeout(typingTimeoutRef.current);
    }

    typingTimeoutRef.current = window.setTimeout(() => {
      sendTypingStop();
    }, 1000);
  };

  const handleSendMessage = () => {
    if (!inputText.trim()) return;

    setMessages((current) => [
      ...current,
      {
        id: Date.now().toString(),
        text: inputText.trim(),
        sender: "me",
      },
    ]);
    setInputText("");
    sendTypingStop();
  };

  const openVipModal = () => {
    setVipCheckoutError(null);
    setVipModalOpen(true);
  };

  const closeVipModal = () => {
    if (vipCheckoutLoading) return;
    setVipModalOpen(false);
    setVipCheckoutError(null);
  };

  const startVipCheckout = async () => {
    setVipCheckoutError(null);
    setVipCheckoutLoading(true);

    try {
      const response = await fetch(VIP_ORDER_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          product_id: VIP_PRODUCT_ID,
          amount: VIP_AMOUNT_CENTS,
          currency: VIP_CURRENCY,
        }),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        const detail = payload.detail || vipCopy.errorMessage;
        const blockedDetail = response.status === 403 ? vipCopy.blockedMinorMessage : detail;
        setVipCheckoutError(blockedDetail);
        return;
      }

      const order = (await response.json()) as OrderResponse;
      if (!order.checkout_url) {
        setVipCheckoutError(vipCopy.errorMessage);
        return;
      }

      window.location.assign(order.checkout_url);
    } catch (error) {
      console.error("Failed to start VIP checkout:", error);
      setVipCheckoutError(vipCopy.errorMessage);
    } finally {
      setVipCheckoutLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-white flex flex-col">
      <div className="bg-zinc-950/95 border-b border-zinc-800 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${isConnected ? "bg-emerald-400" : "bg-red-400"}`} />
          <span className="text-sm text-zinc-300">{isConnected ? "Connected" : "Reconnecting"}</span>
        </div>
        <button
          type="button"
          onClick={openVipModal}
          className="rounded-full bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-amber-300"
        >
          VIP
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div key={message.id} className={`flex ${message.sender === "me" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-6 ${
                message.sender === "me"
                  ? "bg-cyan-600 text-white"
                  : "bg-zinc-800 text-zinc-100"
              }`}
            >
              {message.text}
            </div>
          </div>
        ))}

        {typingStatus?.is_typing && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-zinc-800 px-4 py-3">
              <div className="flex items-center gap-1">
                <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-300" style={{ animationDelay: "0ms" }} />
                <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-300" style={{ animationDelay: "150ms" }} />
                <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-300" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-zinc-800 bg-zinc-950 p-4">
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={inputText}
            onChange={handleInputChange}
            onKeyDown={(event) => {
              if (event.key === "Enter") handleSendMessage();
            }}
            placeholder="Type a message"
            className="min-w-0 flex-1 rounded-full border border-zinc-700 bg-zinc-900 px-4 py-2 text-white placeholder-zinc-500 outline-none focus:border-cyan-400"
          />
          <button
            type="button"
            onClick={handleSendMessage}
            disabled={!inputText.trim()}
            className="rounded-full bg-cyan-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-zinc-700"
          >
            Send
          </button>
        </div>
      </div>

      {vipModalOpen && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/70 p-0 sm:items-center sm:p-6">
          <div className="w-full rounded-t-[8px] border border-zinc-800 bg-zinc-950 p-5 shadow-2xl sm:mx-auto sm:max-w-md sm:rounded-[8px]">
            <div className="mb-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-300">
                {vipCopy.trustNote}
              </p>
              <h1 className="mt-2 text-2xl font-semibold text-white">{vipCopy.title}</h1>
              <p className="mt-2 text-sm leading-6 text-zinc-300">{vipCopy.subtitle}</p>
            </div>

            <div className="mb-5 rounded-[8px] border border-amber-300/30 bg-amber-300/10 p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-amber-100">VIP access</span>
                <span className="text-2xl font-semibold text-amber-200">$4.99</span>
              </div>
              <ul className="mt-3 space-y-2 text-sm leading-5 text-zinc-200">
                {vipCopy.benefits.map((benefit) => (
                  <li key={benefit} className="flex gap-2">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300" />
                    <span>{benefit}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="mb-4 space-y-2 text-sm leading-6 text-zinc-300">
              {vipCopy.body.map((line) => (
                <p key={line}>{line}</p>
              ))}
              <p className="text-xs text-zinc-500">{vipCopy.ageGateNote}</p>
            </div>

            {vipCheckoutError && (
              <div className="mb-4 rounded-[8px] border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-100">
                {vipCheckoutError}
              </div>
            )}

            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={startVipCheckout}
                disabled={vipCheckoutLoading}
                className="min-h-11 flex-1 rounded-[8px] bg-amber-400 px-4 py-3 text-sm font-semibold text-zinc-950 transition hover:bg-amber-300 disabled:cursor-wait disabled:bg-zinc-700 disabled:text-zinc-300"
              >
                {vipCheckoutLoading ? "Opening checkout..." : vipCopy.primaryCta}
              </button>
              <button
                type="button"
                onClick={closeVipModal}
                disabled={vipCheckoutLoading}
                className="min-h-11 rounded-[8px] border border-zinc-700 px-4 py-3 text-sm font-semibold text-zinc-200 transition hover:bg-zinc-900 disabled:cursor-wait disabled:text-zinc-500"
              >
                {vipCopy.secondaryCta}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
