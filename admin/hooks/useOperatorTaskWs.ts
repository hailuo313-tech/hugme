"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type WsConnState = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface WsTaskAlert {
  taskId: string;
  priority: string;
  at: number;
}

interface UseOperatorTaskWsOptions {
  operatorId: string;
  enabled?: boolean;
  onTaskUpsert?: (task: { task_id: string; priority?: string }) => void;
}

export function useOperatorTaskWs({
  operatorId,
  enabled = true,
  onTaskUpsert,
}: UseOperatorTaskWsOptions) {
  const [connState, setConnState] = useState<WsConnState>("connecting");
  const [lastAlert, setLastAlert] = useState<WsTaskAlert | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!enabled || typeof window === "undefined") return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/operators/tasks?operator_id=${encodeURIComponent(operatorId)}`;
    setConnState((s) => (s === "disconnected" ? "reconnecting" : "connecting"));

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnState("connected");
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as {
          type?: string;
          task?: { task_id?: string; priority?: string };
        };
        if (msg.type === "task.upsert" && msg.task?.task_id) {
          const pri = msg.task.priority || "P3";
          setLastAlert({ taskId: msg.task.task_id, priority: pri, at: Date.now() });
          onTaskUpsert?.({ task_id: msg.task.task_id, priority: pri });
        }
      } catch {
        /* ignore malformed */
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnState("disconnected");
      retryRef.current = setTimeout(() => connect(), 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled, operatorId, onTaskUpsert]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    const pingIv = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
    return () => {
      mountedRef.current = false;
      if (retryRef.current) clearTimeout(retryRef.current);
      clearInterval(pingIv);
      wsRef.current?.close();
    };
  }, [connect]);

  const dismissAlert = useCallback(() => setLastAlert(null), []);

  return { connState, lastAlert, dismissAlert, reconnect: connect };
}
