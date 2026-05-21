"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  WS_RECONNECT_RECOVERY_SLA_MS,
  nextReconnectDelayMs,
} from "@/lib/wsReconnect";

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
  onTaskSnapshot?: (tasks: Array<{ task_id: string; priority?: string }>) => void;
  onTaskRemoved?: (taskId: string) => void;
}

export function useOperatorTaskWs({
  operatorId,
  enabled = true,
  onTaskUpsert,
  onTaskSnapshot,
  onTaskRemoved,
}: UseOperatorTaskWsOptions) {
  const [connState, setConnState] = useState<WsConnState>("connecting");
  const [lastAlert, setLastAlert] = useState<WsTaskAlert | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const reconnectAttemptRef = useRef(0);
  const onTaskUpsertRef = useRef(onTaskUpsert);
  const onTaskSnapshotRef = useRef(onTaskSnapshot);
  const onTaskRemovedRef = useRef(onTaskRemoved);

  useEffect(() => {
    onTaskUpsertRef.current = onTaskUpsert;
    onTaskSnapshotRef.current = onTaskSnapshot;
    onTaskRemovedRef.current = onTaskRemoved;
  }, [onTaskRemoved, onTaskSnapshot, onTaskUpsert]);

  const clearRetry = useCallback(() => {
    if (retryRef.current) {
      clearTimeout(retryRef.current);
      retryRef.current = null;
    }
  }, []);

  const connect = useCallback((manual = false) => {
    if (!enabled || typeof window === "undefined") return;
    clearRetry();
    if (manual) {
      reconnectAttemptRef.current = 0;
    }
    const oldSocket = wsRef.current;
    if (
      oldSocket &&
      oldSocket.readyState !== WebSocket.CLOSED &&
      oldSocket.readyState !== WebSocket.CLOSING
    ) {
      oldSocket.onclose = null;
      oldSocket.onerror = null;
      oldSocket.close();
    }

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/operators/tasks?operator_id=${encodeURIComponent(operatorId)}`;
    setConnState(manual || reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting");

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      reconnectAttemptRef.current = 0;
      clearRetry();
      setConnState("connected");
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as {
          type?: string;
          tasks?: Array<{ task_id?: string; priority?: string }>;
          task?: { task_id?: string; priority?: string };
          task_id?: string;
        };
        if (msg.type === "task.snapshot" && Array.isArray(msg.tasks)) {
          onTaskSnapshotRef.current?.(
            msg.tasks
              .filter((task) => Boolean(task.task_id))
              .map((task) => ({
                task_id: String(task.task_id),
                priority: task.priority || "P3",
              })),
          );
        }
        if (msg.type === "task.upsert" && msg.task?.task_id) {
          const pri = msg.task.priority || "P3";
          setLastAlert({ taskId: msg.task.task_id, priority: pri, at: Date.now() });
          onTaskUpsertRef.current?.({ task_id: msg.task.task_id, priority: pri });
        }
        if (msg.type === "task.removed" && msg.task_id) {
          onTaskRemovedRef.current?.(String(msg.task_id));
        }
      } catch {
        /* ignore malformed */
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      if (wsRef.current !== ws) return;
      setConnState("reconnecting");
      const delayMs = nextReconnectDelayMs(reconnectAttemptRef.current);
      reconnectAttemptRef.current += 1;
      retryRef.current = setTimeout(() => connect(), delayMs);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [clearRetry, enabled, operatorId]);

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
      clearRetry();
      clearInterval(pingIv);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.close();
      }
    };
  }, [clearRetry, connect]);

  const dismissAlert = useCallback(() => setLastAlert(null), []);
  const reconnect = useCallback(() => connect(true), [connect]);

  return {
    connState,
    lastAlert,
    dismissAlert,
    reconnect,
    reconnectRecoverySlaMs: WS_RECONNECT_RECOVERY_SLA_MS,
  };
}
