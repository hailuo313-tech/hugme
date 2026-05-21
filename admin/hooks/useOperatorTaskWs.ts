"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type WsConnState = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface WsTaskAlert {
  taskId: string;
  priority: string;
  at: number;
}

export interface WsUserUpgrade {
  userId: string;
  previousLevel: string;
  newLevel: string;
  reason: string;
  upgradedAt: string;
}

// P4-06: S/A 级用户提醒事件
export interface WsUserAlert {
  userId: string;
  level: string;
  nickname: string | null;
  externalId: string | null;
  messageId: string;
  reason: string;
  alertedAt: string;
}

interface UseOperatorTaskWsOptions {
  operatorId: string;
  enabled?: boolean;
  onTaskUpsert?: (task: { task_id: string; priority?: string }) => void;
  onUserUpgraded?: (upgrade: WsUserUpgrade) => void; // P4-04: 用户升级回调
  onUserAlert?: (alert: WsUserAlert) => void; // P4-06: S/A 级用户提醒回调
}

export function useOperatorTaskWs({
  operatorId,
  enabled = true,
  onTaskUpsert,
  onUserUpgraded,
  onUserAlert,
}: UseOperatorTaskWsOptions) {
  const [connState, setConnState] = useState<WsConnState>("connecting");
  const [lastAlert, setLastAlert] = useState<WsTaskAlert | null>(null);
  const [lastUpgrade, setLastUpgrade] = useState<WsUserUpgrade | null>(null); // P4-04
  const [lastAlertModal, setLastAlertModal] = useState<WsUserAlert | null>(null); // P4-06
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
          user_id?: string;
          previous_level?: string;
          new_level?: string;
          reason?: string;
          upgraded_at?: string;
          message_id?: string;
          nickname?: string | null;
          external_id?: string | null;
          level?: string;
          alerted_at?: string;
        };
        
        if (msg.type === "task.upsert" && msg.task?.task_id) {
          const pri = msg.task.priority || "P3";
          setLastAlert({ taskId: msg.task.task_id, priority: pri, at: Date.now() });
          onTaskUpsert?.({ task_id: msg.task.task_id, priority: pri });
        }
        
        // P4-04: 处理用户升级事件
        if (msg.type === "user.upgraded" && msg.user_id && msg.new_level) {
          const upgrade: WsUserUpgrade = {
            userId: msg.user_id,
            previousLevel: msg.previous_level || "unknown",
            newLevel: msg.new_level,
            reason: msg.reason || "unknown",
            upgradedAt: msg.upgraded_at || new Date().toISOString(),
          };
          setLastUpgrade(upgrade);
          onUserUpgraded?.(upgrade);
        }
        
        // P4-06: 处理 S/A 级用户提醒事件
        if (msg.type === "user.alert" && msg.user_id && msg.level && msg.message_id) {
          const alert: WsUserAlert = {
            userId: msg.user_id,
            level: msg.level,
            nickname: msg.nickname || null,
            externalId: msg.external_id || null,
            messageId: msg.message_id,
            reason: msg.reason || "user alert",
            alertedAt: msg.alerted_at || new Date().toISOString(),
          };
          setLastAlertModal(alert);
          onUserAlert?.(alert);
          
          // 保存 WebSocket 实例到 window，用于后续发送 ACK
          (window as any).operatorWs = ws;
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
  }, [enabled, operatorId, onTaskUpsert, onUserUpgraded]);

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
  const dismissUpgrade = useCallback(() => setLastUpgrade(null), []); // P4-04
  const dismissAlertModal = useCallback(() => setLastAlertModal(null), []); // P4-06

  return { connState, lastAlert, dismissAlert, reconnect: connect, lastUpgrade, dismissUpgrade, lastAlertModal, dismissAlertModal };
}
