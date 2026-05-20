"use client";

import type { WsConnState, WsTaskAlert } from "@/hooks/useOperatorTaskWs";

interface Props {
  connState: WsConnState;
  lastAlert: WsTaskAlert | null;
  onDismissAlert: () => void;
  onReconnect: () => void;
}

export default function OperatorWsStatus({
  connState,
  lastAlert,
  onDismissAlert,
  onReconnect,
}: Props) {
  const connLabel =
    connState === "connected"
      ? "任务流已连接"
      : connState === "connecting"
        ? "任务流连接中…"
        : connState === "reconnecting"
          ? "任务流重连中…"
          : "任务流已断开";

  const connClass =
    connState === "connected"
      ? "bg-emerald-900/40 text-emerald-300 border-emerald-800"
      : connState === "disconnected"
        ? "bg-rose-900/40 text-rose-200 border-rose-800"
        : "bg-amber-900/40 text-amber-200 border-amber-800";

  return (
    <div className="flex flex-col gap-2 min-w-0">
      <div className={`flex items-center gap-2 text-xs px-2 py-1 rounded-full border ${connClass}`}>
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            connState === "connected" ? "bg-emerald-400" : "bg-amber-400 animate-pulse"
          }`}
        />
        <span>{connLabel}</span>
        {connState === "disconnected" && (
          <button
            type="button"
            onClick={onReconnect}
            className="underline hover:text-white"
          >
            重连
          </button>
        )}
      </div>
      {lastAlert && (
        <div className="flex items-center justify-between gap-2 text-xs bg-violet-900/40 border border-violet-700 text-violet-100 px-3 py-2 rounded-md max-w-md">
          <span>
            新任务推送 · 优先级 {lastAlert.priority}
          </span>
          <button type="button" onClick={onDismissAlert} className="text-violet-300 hover:text-white">
            知道了
          </button>
        </div>
      )}
    </div>
  );
}
