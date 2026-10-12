"use client";

import { useEffect, useState } from "react";
import { API_BASE, LOGIN_PATH, clearAuth, getToken } from "@/lib/auth";

const MEDIA_PLACEHOLDERS = new Set([
  "[photo]",
  "[image]",
  "[video]",
  "[audio]",
  "[voice]",
  "[media]",
]);

export function looksLikeChatMedia(
  content: string | null | undefined,
  contentType: string | null | undefined,
): boolean {
  const type = String(contentType || "").toLowerCase();
  if (["image", "photo", "video", "audio", "voice"].includes(type)) return true;
  const text = String(content || "").trim().toLowerCase();
  if (MEDIA_PLACEHOLDERS.has(text)) return true;
  return text.startsWith("[photo]") || text.startsWith("[image]") || text.startsWith("[video]");
}

export function looksLikeUserPhoto(
  content: string | null | undefined,
  contentType: string | null | undefined,
): boolean {
  return looksLikeChatMedia(content, contentType);
}

function resolveMediaPath(messageId: string): string {
  return `${API_BASE}/admin/messages/${messageId}/media`;
}

function kindFromType(contentType: string | null | undefined, blobType?: string | null): "image" | "video" | "audio" {
  const type = String(blobType || contentType || "").toLowerCase();
  if (type.startsWith("video/") || type === "video") return "video";
  if (type.startsWith("audio/") || type === "audio" || type === "voice") return "audio";
  return "image";
}

export default function InboundUserMedia({
  messageId,
  content,
  contentType,
}: {
  messageId: string;
  content?: string | null;
  contentType?: string | null;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [kind, setKind] = useState<"image" | "video" | "audio">(kindFromType(contentType));
  const [status, setStatus] = useState<"loading" | "ready" | "missing" | "unavailable" | "error">("loading");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let objectUrl = "";
    let cancelled = false;
    const controller = new AbortController();
    setSrc(null);
    setStatus("loading");

    async function load() {
      const token = getToken();
      if (!token) {
        setStatus("error");
        return;
      }
      try {
        const response = await fetch(resolveMediaPath(messageId), {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (cancelled) return;
        if (response.status === 401) {
          clearAuth();
          window.location.href = LOGIN_PATH;
          return;
        }
        if (response.status === 404) {
          setStatus("missing");
          return;
        }
        if (response.status === 410) {
          setStatus("unavailable");
          return;
        }
        if (!response.ok) {
          setStatus("error");
          return;
        }
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setKind(kindFromType(contentType, blob.type));
        setSrc(objectUrl);
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [contentType, messageId, retry]);

  const caption = String(content || "").trim();
  const showCaption = Boolean(caption) && !MEDIA_PLACEHOLDERS.has(caption.toLowerCase()) && !caption.startsWith("[photo]");

  return (
    <div className="space-y-2">
      {status === "loading" && (
        <div className="rounded-md border border-slate-800 bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-500">
          媒体加载中…
        </div>
      )}
      {status === "ready" && src && kind === "video" && (
        <video src={src} controls onError={() => setStatus("error")} className="max-h-96 max-w-full rounded-md border border-slate-700" />
      )}
      {status === "ready" && src && kind === "audio" && (
        <audio src={src} controls onError={() => setStatus("error")} className="w-full max-w-sm" />
      )}
      {status === "ready" && src && kind === "image" && (
        <a href={src} target="_blank" rel="noreferrer">
          <img
            src={src}
            alt="聊天图片"
            onError={() => setStatus("error")}
            className="max-h-96 max-w-full rounded-md border border-slate-700 object-contain"
          />
        </a>
      )}
      {status === "missing" && (
        <div className="rounded-md border border-amber-900/70 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
          暂未找到媒体文件，尚不能确认是否可以恢复。
        </div>
      )}
      {status === "unavailable" && (
        <div className="rounded-md border border-slate-700 bg-slate-950/30 px-3 py-2 text-xs text-slate-400">
          此记录没有可读取的媒体文件，可能是历史占位记录或不支持的附件。
        </div>
      )}
      {status === "error" && (
        <div className="rounded-md border border-rose-900/70 bg-rose-950/30 px-3 py-2 text-xs text-rose-200">
          媒体请求或播放失败，请重试；若持续失败，请联系管理员。
        </div>
      )}
      {(status === "error" || status === "missing") && (
        <button type="button" onClick={() => setRetry(value => value + 1)} className="text-xs text-cyan-300">重新加载</button>
      )}
      {showCaption && (
        <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-100">{caption}</div>
      )}
    </div>
  );
}
