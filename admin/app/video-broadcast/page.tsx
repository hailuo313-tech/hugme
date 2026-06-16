"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { usePendingReviewRing } from "@/hooks/usePendingReviewRing";
import {
  incomingReviewAlertBody,
  incomingReviewCallCountText,
  notifyIncomingReview,
} from "@/lib/incomingReviewAlert";
import { apiFetch, getToken, Operator } from "@/lib/auth";
import { formatBeijingDateTime } from "@/lib/reportTime";

type VideoAsset = {
  id: string;
  title: string;
  file_path: string;
  duration_seconds: number | null;
  play_sequence: number | null;
  status: string;
  preview_url: string;
  created_at?: string;
};

function playSequenceLabel(seq: number | null | undefined) {
  if (seq === 1) return "第 1 次来电视频";
  if (seq === 2) return "第 2 次来电视频";
  if (seq === 3) return "第 3 次来电视频";
  return null;
}

function videoOptionLabel(video: VideoAsset) {
  const seqLabel = playSequenceLabel(video.play_sequence);
  const duration = video.duration_seconds ?? 30;
  if (seqLabel) return `${seqLabel} — ${video.title} (${duration}s)`;
  return `${video.title} (${duration}s)`;
}

function suggestVideoForReview(
  inboundCallNumber: number | null | undefined,
  videos: VideoAsset[],
): string {
  if (!videos.length) return "";
  const callNo = inboundCallNumber ?? 2;
  const preferredSeq = callNo >= 3 ? 3 : 2;
  const bySeq = videos.find((v) => v.play_sequence === preferredSeq);
  if (bySeq) return bySeq.id;
  const manualVideos = videos.filter((v) => v.play_sequence !== 1);
  if (manualVideos.length) return manualVideos[0].id;
  return videos[0].id;
}

type ChatUser = {
  user_id: string;
  conversation_id: string;
  nickname: string | null;
  external_id: string | null;
  chat_id: number | null;
  channel: string | null;
  conversation_state: string | null;
  user_status: string | null;
  last_message_at: string | null;
  telegram_account_id: string | null;
};

type ChatUsersResponse = {
  items: ChatUser[];
  total: number;
  page: number;
  page_size: number;
};

type CallHistoryRecord = {
  job_id: string;
  user_id: string | null;
  nickname: string | null;
  external_id: string | null;
  chat_id: number | null;
  status: string | null;
  trigger_source: string | null;
  call_at: string | null;
  video_title: string | null;
  duration_seconds: number;
  inbound_call_number: number | null;
  telegram_account_id: string | null;
  telegram_account_label: string | null;
  telegram_account_phone: string | null;
  telegram_account_name: string | null;
  telegram_account_username: string | null;
};

type CallHistoryResponse = {
  items: CallHistoryRecord[];
  total: number;
  page: number;
  page_size: number;
};

function formatDuration(seconds: number | null | undefined) {
  const total = Math.max(0, Number(seconds) || 0);
  if (total < 60) return `${total} 秒`;
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return secs > 0 ? `${mins} 分 ${secs} 秒` : `${mins} 分`;
}

function callStatusLabel(status: string | null | undefined) {
  switch (status) {
    case "completed":
      return "成功";
    case "cancelled":
      return "未成功";
    case "failed":
      return "失败";
    case "pending":
      return "待执行";
    case "running":
      return "执行中";
    default:
      return status || "—";
  }
}

function callStatusClassName(status: string | null | undefined) {
  switch (status) {
    case "completed":
      return "text-emerald-300";
    case "cancelled":
      return "text-amber-300";
    case "failed":
      return "text-rose-300";
    default:
      return "text-slate-300";
  }
}

type IncomingReview = {
  id: string;
  chat_id: number;
  account_id: string;
  nickname: string | null;
  external_id: string | null;
  inbound_call_number: number | null;
  completed_inbound_calls?: number | null;
  seconds_remaining: number | null;
  created_at: string | null;
  trigger_source?: string | null;
  matched_keyword?: string | null;
};

function incomingReviewHeadline(review: IncomingReview): string {
  const count = incomingReviewCallCountText(review);
  if (review.trigger_source === "inbound_keyword_review") {
    return `${count} · 文字请求 ${review.matched_keyword || "打视频"}`;
  }
  return count;
}

function triggerSourceLabel(source: string | null) {
  switch (source) {
    case "inbound_keyword_review":
      return "文字打视频";
    case "inbound_keyword":
      return "8866 触发";
    case "inbound_call":
      return "来电自动接听";
    case "inbound_operator_review":
      return "人工接听";
    case "admin_manual":
      return "后台手动";
    default:
      return source || "—";
  }
}

const VIDEO_ACCEPT = "video/mp4,video/webm,video/quicktime,.mp4,.mov,.webm,.m4v";
const RECENT_LIST_PAGE_SIZE = 10;
const RECENT_LIST_REFRESH_MS = 5 * 60 * 1000;

function VideoPreview({ previewUrl }: { previewUrl: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    async function loadPreview() {
      setFailed(false);
      setSrc(null);
      try {
        const token = getToken();
        const response = await fetch(previewUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!response.ok) {
          if (!cancelled) setFailed(true);
          return;
        }
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setSrc(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    loadPreview();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewUrl]);

  if (failed) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-slate-800 text-xs text-slate-500">
        预览不可用
      </div>
    );
  }
  if (!src) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border border-slate-800 bg-black text-xs text-slate-500">
        预览加载中...
      </div>
    );
  }
  return (
    <video
      className="w-full rounded-md border border-slate-800 bg-black"
      controls
      preload="metadata"
      src={src}
    />
  );
}

function formatTime(value: string | null) {
  return formatBeijingDateTime(value);
}

function VideoBroadcastContent({ operator }: { operator: Operator }) {
  const [items, setItems] = useState<VideoAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [durationSeconds, setDurationSeconds] = useState("30");
  const [playSequence, setPlaySequence] = useState("1");

  const [chatUsers, setChatUsers] = useState<ChatUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersTotal, setUsersTotal] = useState(0);
  const [userSearch, setUserSearch] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set());
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [calling, setCalling] = useState(false);

  const [historyRecords, setHistoryRecords] = useState<CallHistoryRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historySearch, setHistorySearch] = useState("");

  const [pendingReviews, setPendingReviews] = useState<IncomingReview[]>([]);
  const [incomingReviewPopup, setIncomingReviewPopup] = useState<IncomingReview | null>(null);
  const knownReviewIdsRef = useRef<Set<string>>(new Set());
  const reviewsBootstrappedRef = useRef(false);
  const [reviewActionId, setReviewActionId] = useState<string | null>(null);
  const [reviewVideoByJob, setReviewVideoByJob] = useState<Record<string, string>>({});

  const activeVideos = useMemo(
    () => items.filter((item) => item.status === "active"),
    [items],
  );

  const pendingReviewIds = useMemo(
    () => pendingReviews.map((review) => review.id),
    [pendingReviews],
  );

  const {
    soundEnabled,
    setSoundEnabled,
    needsUnlock,
    unlockSound,
    testRing,
  } = usePendingReviewRing(pendingReviewIds);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ items: VideoAsset[] }>("/call-broadcast/admin/video-assets");
      const list = data.items || [];
      setItems(list);
      setSelectedVideoId((prev) => {
        if (prev && list.some((v) => v.id === prev && v.status === "active")) return prev;
        const first = list.find((v) => v.status === "active");
        return first?.id || "";
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadChatUsers = useCallback(async (
    page = 1,
    search = userSearch,
    options?: { silent?: boolean },
  ) => {
    if (!options?.silent) setUsersLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(RECENT_LIST_PAGE_SIZE),
      });
      if (search.trim()) params.set("search", search.trim());
      const data = await apiFetch<ChatUsersResponse>(
        `/call-broadcast/admin/chat-users?${params.toString()}`,
      );
      setChatUsers(data.items || []);
      setUsersTotal(data.total || 0);
    } catch (err) {
      if (!options?.silent) {
        setError(err instanceof Error ? err.message : "用户列表加载失败");
      }
    } finally {
      if (!options?.silent) setUsersLoading(false);
    }
  }, [userSearch]);

  const loadCallHistory = useCallback(async (
    page = 1,
    search = historySearch,
    options?: { silent?: boolean },
  ) => {
    if (!options?.silent) setHistoryLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(RECENT_LIST_PAGE_SIZE),
      });
      if (search.trim()) params.set("search", search.trim());
      const data = await apiFetch<CallHistoryResponse>(
        `/call-broadcast/admin/call-history?${params.toString()}`,
      );
      setHistoryRecords(data.items || []);
      setHistoryTotal(data.total || 0);
    } catch (err) {
      if (!options?.silent) {
        setError(err instanceof Error ? err.message : "通话记录加载失败");
      }
    } finally {
      if (!options?.silent) setHistoryLoading(false);
    }
  }, [historySearch]);

  const syncReviewVideoDefaults = useCallback(
    (reviews: IncomingReview[], videos: VideoAsset[]) => {
      if (!videos.length || !reviews.length) return;
      setReviewVideoByJob((prev) => {
        const next = { ...prev };
        for (const item of reviews) {
          if (!next[item.id] || !videos.some((v) => v.id === next[item.id])) {
            next[item.id] = suggestVideoForReview(item.inbound_call_number, videos);
          }
        }
        return next;
      });
    },
    [],
  );

  const loadPendingReviews = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: IncomingReview[]; total: number }>(
        "/call-broadcast/admin/incoming-reviews",
      );
      const list = data.items || [];
      if (!reviewsBootstrappedRef.current) {
        reviewsBootstrappedRef.current = true;
        knownReviewIdsRef.current = new Set(list.map((item) => item.id));
      } else {
        for (const review of list) {
          if (!knownReviewIdsRef.current.has(review.id)) {
            notifyIncomingReview(review);
            setIncomingReviewPopup(review);
          }
        }
        knownReviewIdsRef.current = new Set(list.map((item) => item.id));
      }
      setPendingReviews(list);
      syncReviewVideoDefaults(list, activeVideos);
    } catch {
      // keep polling quietly; main error surface handles hard failures elsewhere
    }
  }, [activeVideos, syncReviewVideoDefaults]);

  useEffect(() => {
    load();
    loadChatUsers(1, "");
    loadCallHistory(1, "");
    loadPendingReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  useEffect(() => {
    syncReviewVideoDefaults(pendingReviews, activeVideos);
  }, [activeVideos, pendingReviews, syncReviewVideoDefaults]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadPendingReviews();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadPendingReviews]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadChatUsers(1, userSearch, { silent: true });
    }, RECENT_LIST_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadChatUsers, userSearch]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadCallHistory(1, historySearch, { silent: true });
    }, RECENT_LIST_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [historySearch, loadCallHistory]);

  async function acceptIncomingReview(jobId: string) {
    setReviewActionId(jobId);
    setError(null);
    try {
      const assetsData = await apiFetch<{ items: VideoAsset[] }>(
        "/call-broadcast/admin/video-assets",
      );
      const freshActive = (assetsData.items || []).filter((item) => item.status === "active");
      setItems(assetsData.items || []);

      const review = pendingReviews.find((item) => item.id === jobId);
      let videoId = reviewVideoByJob[jobId] || selectedVideoId || freshActive[0]?.id || "";
      if (!videoId || !freshActive.some((video) => video.id === videoId)) {
        videoId = suggestVideoForReview(review?.inbound_call_number, freshActive);
        if (videoId) {
          setReviewVideoByJob((prev) => ({ ...prev, [jobId]: videoId }));
        }
      }
      if (!videoId) {
        setError("请先选择要播放的视频");
        return;
      }

      await apiFetch(`/call-broadcast/admin/incoming-reviews/${jobId}/accept`, {
        method: "POST",
        body: JSON.stringify({ video_asset_id: videoId }),
      });
      setToast("已接听并开始播放所选视频");
      await Promise.all([loadPendingReviews(), loadCallHistory(1, historySearch)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "接听失败，来电可能已超时");
      await Promise.all([load(), loadPendingReviews()]);
    } finally {
      setReviewActionId(null);
    }
  }

  async function rejectIncomingReview(jobId: string) {
    if (!window.confirm("确认拒绝该来电？")) return;
    setReviewActionId(jobId);
    setError(null);
    try {
      await apiFetch(`/call-broadcast/admin/incoming-reviews/${jobId}/reject`, {
        method: "POST",
      });
      setToast("已拒绝来电");
      await loadPendingReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "拒绝失败");
      await loadPendingReviews();
    } finally {
      setReviewActionId(null);
    }
  }

  async function uploadVideo(file: File) {
    const cleanTitle = title.trim() || file.name.replace(/\.[^.]+$/, "");
    if (!cleanTitle) {
      setError("请填写视频标题");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const token = getToken();
      const body = new FormData();
      body.append("file", file);
      body.append("title", cleanTitle);
      body.append("play_sequence", playSequence);
      if (durationSeconds.trim()) {
        body.append("duration_seconds", durationSeconds.trim());
      }
      const response = await fetch("/api/v1/call-broadcast/admin/video-assets", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail =
          typeof payload.detail === "string"
            ? payload.detail
            : response.status === 413
              ? "文件过大：单文件最大 100MB，若仍失败请联系运维检查 Nginx 限制"
              : `上传失败 (${response.status})`;
        throw new Error(detail);
      }
      setToast("视频已上传");
      setTitle("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function archiveAsset(assetId: string) {
    if (!window.confirm("确认归档该视频？归档后通话投放将不再使用。")) return;
    try {
      await apiFetch(`/call-broadcast/admin/video-assets/${assetId}`, { method: "DELETE" });
      setToast("已归档");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "归档失败");
    }
  }

  function toggleUser(userId: string) {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  function toggleAllVisible() {
    const visibleIds = chatUsers.map((u) => u.user_id);
    const allSelected = visibleIds.every((id) => selectedUserIds.has(id));
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        visibleIds.forEach((id) => next.delete(id));
      } else {
        visibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  async function startManualCalls() {
    if (!selectedVideoId) {
      setError("请先选择要播放的视频");
      return;
    }
    if (selectedUserIds.size === 0) {
      setError("请至少选择一位用户");
      return;
    }
    const targets = chatUsers
      .filter((u) => selectedUserIds.has(u.user_id))
      .map((u) => ({ user_id: u.user_id, conversation_id: u.conversation_id }));
    if (targets.length === 0) {
      setError("所选用户不在当前列表，请刷新后重试");
      return;
    }
    if (!window.confirm(`确认向 ${targets.length} 位用户发起视频通话？`)) return;

    setCalling(true);
    setError(null);
    try {
      const result = await apiFetch<{
        inserted: number;
        skipped: number;
        errors: { user_id: string; reason: string }[];
      }>("/call-broadcast/admin/manual-calls", {
        method: "POST",
        body: JSON.stringify({
          video_asset_id: selectedVideoId,
          targets,
        }),
      });
      const errList = result.errors || [];
      if (result.inserted > 0) {
        setToast(
          `已排队 ${result.inserted} 个通话任务` +
            (errList.length ? `，${errList.length} 个失败` : ""),
        );
        setError(null);
      } else {
        setToast(null);
        setError(
          errList.length
            ? errList.map((e) => `${e.reason}`).join("；")
            : "未成功排队任何通话任务",
        );
      }
      if (result.inserted > 0 && errList.length) {
        setError(errList.slice(0, 3).map((e) => e.reason).join("；"));
      }
      if (result.inserted > 0) {
        setSelectedUserIds(new Set());
        loadCallHistory(1, historySearch);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发起通话失败");
    } finally {
      setCalling(false);
    }
  }

  return (
    <AdminFrame
      operator={operator}
      active="broadcast"
      title="视频通话投放"
      subtitle="第 1、2 次打来自动播放视频 1/2；第 3 次起进入人工队列，由操作员接听或拒绝并自选视频。"
    >
      <div className="space-y-6">
        {incomingReviewPopup ? (
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 py-10">
            <div className="w-full max-w-lg rounded-lg border border-amber-600 bg-slate-900 p-5 shadow-2xl">
              <div className="text-lg font-semibold text-amber-200">待人工接听</div>
              <p className="mt-2 text-sm text-slate-200">
                {incomingReviewPopup.nickname || incomingReviewPopup.external_id || `chat ${incomingReviewPopup.chat_id}`}
              </p>
              <p className="mt-3 rounded-md border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-sm font-medium text-amber-100">
                {incomingReviewAlertBody(incomingReviewPopup)}
              </p>
              <p className="mt-2 text-xs text-slate-400">
                请确认视频次数后再选择播放视频并接听。
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500"
                  onClick={() => setIncomingReviewPopup(null)}
                >
                  知道了，去处理
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {toast && (
          <div className="rounded-md border border-emerald-800 bg-emerald-950 px-4 py-3 text-sm text-emerald-200">
            {toast}
            <button type="button" className="ml-3 text-emerald-400 underline" onClick={() => setToast(null)}>
              关闭
            </button>
          </div>
        )}
        {error && (
          <div className="rounded-md border border-rose-800 bg-rose-950 px-4 py-3 text-sm text-rose-200">{error}</div>
        )}

        <section
          className={`rounded-lg border p-5 ${
            pendingReviews.length > 0
              ? "border-amber-600 bg-amber-950/40"
              : "border-slate-800 bg-slate-900"
          }`}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 className="text-lg font-semibold text-slate-100">
              待人工处理来电
              {pendingReviews.length > 0 ? (
                <span className="ml-2 rounded-full bg-amber-600 px-2 py-0.5 text-xs text-white">
                  {pendingReviews.length}
                </span>
              ) : null}
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setSoundEnabled()}
                className={`rounded-md border px-3 py-1.5 text-xs ${
                  soundEnabled
                    ? "border-amber-600 bg-amber-950 text-amber-100"
                    : "border-slate-700 bg-slate-950 text-slate-400"
                }`}
              >
                {soundEnabled ? "铃声提醒：开" : "铃声提醒：关"}
              </button>
              <button
                type="button"
                onClick={() => testRing()}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                测试铃声
              </button>
            </div>
          </div>
          {needsUnlock ? (
            <p className="mt-2 text-xs text-amber-300">
              浏览器需先点击页面任意位置后才能播放铃声。
              <button
                type="button"
                className="ml-2 underline"
                onClick={() => void unlockSound()}
              >
                启用声音
              </button>
            </p>
          ) : null}
          <p className="mt-1 text-sm text-slate-400">
            用户第 3 次及以后打来、或聊天中发送「打视频」等文字请求，会进入此队列。有待处理时会像来电铃声一样循环提醒。接听前请先选择要播放的视频。
          </p>
          {activeVideos.length === 0 ? (
            <p className="mt-3 text-sm text-amber-300">请先在下方上传视频，否则无法接听。</p>
          ) : null}
          {pendingReviews.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">当前无待处理来电</p>
          ) : (
            <div className="mt-4 space-y-3">
              {pendingReviews.map((review) => {
                const selectedVideoIdForReview = reviewVideoByJob[review.id] || "";
                const selectedVideo = activeVideos.find((v) => v.id === selectedVideoIdForReview);
                return (
                  <div
                    key={review.id}
                    className="rounded-md border border-amber-800/60 bg-slate-950/80 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-100">
                          {review.nickname || "未命名用户"}
                          <span className="ml-2 text-sm text-amber-300">
                            {incomingReviewHeadline(review)}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          {review.external_id || `chat ${review.chat_id}`}
                          {review.completed_inbound_calls != null ? (
                            <span className="ml-2">
                              历史自动接听 {review.completed_inbound_calls} 次
                            </span>
                          ) : null}
                          {review.seconds_remaining != null ? (
                            <span className="ml-2 text-amber-400">
                              剩余 {review.seconds_remaining}s
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 rounded-md border border-slate-700 bg-slate-900/80 p-3">
                      <div className="text-sm font-medium text-slate-200">选择播放视频</div>
                      <p className="mt-1 text-xs text-slate-500">
                        第 2 次默认推荐视频 2，第 3 次及以上默认推荐视频 3，也可手动切换。
                      </p>
                      <select
                        value={selectedVideoIdForReview}
                        onChange={(e) =>
                          setReviewVideoByJob((prev) => ({
                            ...prev,
                            [review.id]: e.target.value,
                          }))
                        }
                        className="mt-2 w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white"
                      >
                        <option value="">请选择要播放的视频</option>
                        {activeVideos.map((video) => (
                          <option key={video.id} value={video.id}>
                            {videoOptionLabel(video)}
                          </option>
                        ))}
                      </select>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {activeVideos.map((video) => {
                          const active = selectedVideoIdForReview === video.id;
                          return (
                            <button
                              key={video.id}
                              type="button"
                              onClick={() =>
                                setReviewVideoByJob((prev) => ({
                                  ...prev,
                                  [review.id]: video.id,
                                }))
                              }
                              className={`rounded-full border px-3 py-1 text-xs transition ${
                                active
                                  ? "border-violet-500 bg-violet-950 text-violet-100"
                                  : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                              }`}
                            >
                              {playSequenceLabel(video.play_sequence) || video.title}
                            </button>
                          );
                        })}
                      </div>
                      {selectedVideo ? (
                        <p className="mt-2 text-xs text-slate-400">
                          已选：{videoOptionLabel(selectedVideo)}
                        </p>
                      ) : null}
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={
                          reviewActionId === review.id ||
                          !selectedVideoIdForReview ||
                          activeVideos.length === 0
                        }
                        onClick={() => acceptIncomingReview(review.id)}
                        className="rounded-md border border-emerald-700 bg-emerald-950 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-900 disabled:opacity-50"
                      >
                        {reviewActionId === review.id
                          ? "处理中..."
                          : selectedVideo
                            ? `接听并播放：${playSequenceLabel(selectedVideo.play_sequence) || selectedVideo.title}`
                            : "接听（请先选视频）"}
                      </button>
                      <button
                        type="button"
                        disabled={reviewActionId === review.id}
                        onClick={() => rejectIncomingReview(review.id)}
                        className="rounded-md border border-rose-800 bg-rose-950 px-4 py-2 text-sm text-rose-100 hover:bg-rose-900 disabled:opacity-50"
                      >
                        拒绝来电
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-slate-100">视频通话记录</h2>
          <p className="mt-1 text-sm text-slate-400">
            只显示最新 10 条通话任务，成功和不成功都会展示，每 5 分钟自动刷新。
          </p>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="block min-w-[220px] flex-1 text-sm text-slate-300">
              搜索
              <input
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                placeholder="昵称 / Telegram ID / 接听账号"
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              />
            </label>
            <button
              type="button"
              onClick={() => loadCallHistory(1, historySearch)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              搜索
            </button>
            <button
              type="button"
              onClick={() => loadCallHistory(1, historySearch)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              刷新
            </button>
          </div>
          <div className="mt-4 overflow-x-auto rounded-md border border-slate-800">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-3 py-2">用户</th>
                  <th className="px-3 py-2">用户 Telegram</th>
                  <th className="px-3 py-2">接听 TG 账号</th>
                  <th className="px-3 py-2">通话时间</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">第几次</th>
                  <th className="px-3 py-2">触发方式</th>
                  <th className="px-3 py-2">播放视频</th>
                  <th className="px-3 py-2">通话时长</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {historyLoading ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                      加载通话记录...
                    </td>
                  </tr>
                ) : historyRecords.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                      暂无视频通话记录
                    </td>
                  </tr>
                ) : (
                  historyRecords.map((record) => {
                    const completed = record.status === "completed";
                    return (
                      <tr key={record.job_id} className="hover:bg-slate-950/60">
                        <td className="px-3 py-2 text-slate-100">
                          {record.nickname || "未命名"}
                          {record.user_id ? (
                            <div className="text-xs text-slate-500">{record.user_id}</div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          {record.external_id || "—"}
                          {record.chat_id ? (
                            <div className="text-xs text-slate-500">chat {record.chat_id}</div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          {record.telegram_account_label || "—"}
                          {record.telegram_account_phone &&
                          record.telegram_account_phone !== record.telegram_account_label ? (
                            <div className="text-xs text-slate-500">{record.telegram_account_phone}</div>
                          ) : null}
                          {record.telegram_account_id ? (
                            <div className="text-xs text-slate-500">{record.telegram_account_id}</div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-slate-400">{formatTime(record.call_at)}</td>
                        <td className={`px-3 py-2 font-semibold ${callStatusClassName(record.status)}`}>
                          {callStatusLabel(record.status)}
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          {record.inbound_call_number ? `第 ${record.inbound_call_number} 次` : "—"}
                        </td>
                        <td className="px-3 py-2 text-slate-400">
                          {triggerSourceLabel(record.trigger_source)}
                        </td>
                        <td className="px-3 py-2 text-slate-400">{record.video_title || "—"}</td>
                        <td className="px-3 py-2 font-medium text-slate-200">
                          {completed ? formatDuration(record.duration_seconds) : "—"}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
            <span>共 {historyTotal} 条通话记录，当前显示最新 {historyRecords.length} 条</span>
            <span>每 5 分钟自动刷新</span>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-slate-100">手动发起视频通话</h2>
          <p className="mt-1 text-sm text-slate-400">
            只显示最新 10 位 Telegram 私聊用户，每 5 分钟自动刷新，并指定播放哪条已上传视频。需开启{" "}
            <code className="text-sky-300">CALL_BROADCAST_ENABLED=1</code>。
          </p>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="block min-w-[220px] flex-1 text-sm text-slate-300">
              选择视频
              <select
                value={selectedVideoId}
                onChange={(e) => setSelectedVideoId(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              >
                <option value="">请选择视频</option>
                {activeVideos.map((video) => (
                  <option key={video.id} value={video.id}>
                    {video.title} ({video.duration_seconds ?? 30}s)
                  </option>
                ))}
              </select>
            </label>
            <label className="block min-w-[220px] flex-1 text-sm text-slate-300">
              搜索用户
              <input
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="昵称 / Telegram ID"
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              />
            </label>
            <button
              type="button"
              onClick={() => loadChatUsers(1, userSearch)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              搜索
            </button>
            <button
              type="button"
              disabled={calling || selectedUserIds.size === 0 || !selectedVideoId}
              onClick={startManualCalls}
              className="rounded-md border border-violet-700 bg-violet-950 px-4 py-2 text-sm font-medium text-violet-100 hover:bg-violet-900 disabled:opacity-50"
            >
              {calling ? "发起中..." : `向所选用户发起通话 (${selectedUserIds.size})`}
            </button>
          </div>

          <div className="mt-4 overflow-x-auto rounded-md border border-slate-800">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={
                        chatUsers.length > 0 &&
                        chatUsers.every((u) => selectedUserIds.has(u.user_id))
                      }
                      onChange={toggleAllVisible}
                    />
                  </th>
                  <th className="px-3 py-2">用户</th>
                  <th className="px-3 py-2">Telegram</th>
                  <th className="px-3 py-2">最近消息</th>
                  <th className="px-3 py-2">会话状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {usersLoading ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                      加载用户列表...
                    </td>
                  </tr>
                ) : chatUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                      暂无聊天用户
                    </td>
                  </tr>
                ) : (
                  chatUsers.map((user) => (
                    <tr key={user.user_id} className="hover:bg-slate-950/60">
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selectedUserIds.has(user.user_id)}
                          onChange={() => toggleUser(user.user_id)}
                        />
                      </td>
                      <td className="px-3 py-2 text-slate-100">
                        {user.nickname || "未命名"}
                        <div className="text-xs text-slate-500">{user.user_id}</div>
                      </td>
                      <td className="px-3 py-2 text-slate-300">
                        {user.external_id || "—"}
                        {user.chat_id ? (
                          <div className="text-xs text-slate-500">chat {user.chat_id}</div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-slate-400">{formatTime(user.last_message_at)}</td>
                      <td className="px-3 py-2 text-slate-400">{user.conversation_state || "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
            <span>
              共 {usersTotal} 位用户，当前显示最新 {chatUsers.length} 位，已选 {selectedUserIds.size} 位
            </span>
            <span>每 5 分钟自动刷新</span>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-slate-100">上传视频</h2>
          <p className="mt-1 text-sm text-slate-400">
            支持 mp4 / mov / webm / m4v，最大 100MB。视频 1/2 用于第 1、2 次自动播放；视频 3 供第 3 次及以上人工接听时选择。
          </p>
          <div className="mt-3 rounded-md border border-sky-900/60 bg-sky-950/40 px-4 py-3 text-sm text-sky-100">
            <p className="font-medium text-sky-200">素材规范（推荐上传前即满足）</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sky-100/90">
              <li>竖屏 9:16，分辨率不超过 720×1280</li>
              <li>帧率 30 fps，H.264 + AAC</li>
              <li>码率约 2–3 Mbps，时长 15–60 秒</li>
              <li>上传后服务器会自动再标准化一次；已是 720p/30fps 的素材会跳过转码</li>
            </ul>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <label className="block text-sm text-slate-300">
              第几次来电视频
              <select
                value={playSequence}
                onChange={(e) => setPlaySequence(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              >
                <option value="1">视频 1 — 第 1 次打来（自动播放）</option>
                <option value="2">视频 2 — 第 2 次打来（自动播放）</option>
                <option value="3">视频 3 — 第 3 次及以上（人工接听）</option>
              </select>
            </label>
            <label className="block text-sm text-slate-300">
              标题
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如 第一次欢迎视频"
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              />
            </label>
            <label className="block text-sm text-slate-300">
              播放时长（秒）
              <input
                value={durationSeconds}
                onChange={(e) => setDurationSeconds(e.target.value)}
                type="number"
                min={5}
                max={600}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              />
            </label>
            <div className="flex items-end">
              <label className="flex w-full cursor-pointer items-center justify-center rounded-md border border-violet-700 bg-violet-950 px-4 py-2 text-sm font-medium text-violet-100 hover:bg-violet-900">
                {uploading ? "上传中..." : "选择视频并上传"}
                <input
                  type="file"
                  accept={VIDEO_ACCEPT}
                  className="hidden"
                  disabled={uploading}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.currentTarget.value = "";
                    if (file) uploadVideo(file);
                  }}
                />
              </label>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 px-5 py-4">
            <h2 className="text-lg font-semibold text-slate-100">已上传视频</h2>
            <p className="mt-1 text-sm text-slate-400">
              标注了「第 N 次来电视频」的素材用于用户打来时自动播放；手动外呼可任选 active 素材。
            </p>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-sm text-slate-400">加载中...</div>
          ) : items.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-slate-500">暂无视频，请先上传。</div>
          ) : (
            <div className="divide-y divide-slate-800">
              {items.map((item) => (
                <div key={item.id} className="grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_320px_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="font-medium text-slate-100">{item.title}</div>
                    <div className="mt-1 truncate text-xs text-slate-500">{item.file_path}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      {playSequenceLabel(item.play_sequence) ? (
                        <span className="rounded-full bg-violet-950 px-2 py-1 text-violet-200">
                          {playSequenceLabel(item.play_sequence)}
                        </span>
                      ) : null}
                      <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-300">
                        {item.duration_seconds ?? 30}s
                      </span>
                      <span className="rounded-full bg-slate-800 px-2 py-1 text-emerald-300">{item.status}</span>
                    </div>
                  </div>
                  <VideoPreview previewUrl={item.preview_url} />
                  <button
                    type="button"
                    onClick={() => archiveAsset(item.id)}
                    className="rounded-md border border-rose-800 px-3 py-2 text-sm text-rose-200 hover:bg-rose-950"
                  >
                    归档
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </AdminFrame>
  );
}

export default function VideoBroadcastPage() {
  return <AuthGate>{(operator) => <VideoBroadcastContent operator={operator} />}</AuthGate>;
}
