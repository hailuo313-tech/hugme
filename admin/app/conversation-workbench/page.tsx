"use client";

import { useCallback, useEffect, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import InboundUserMedia, { looksLikeChatMedia } from "@/components/InboundUserMedia";
import { apiFetch } from "@/lib/auth";

type ConversationRow = {
  conversation_id: string;
  nickname?: string | null;
  external_id?: string | null;
  country_code?: string | null;
  is_t1_country?: boolean | null;
  country_source?: string | null;
  stated_country_code?: string | null;
  telegram_phone_country?: string | null;
  language?: string | null;
  last_message_at?: string | null;
  latest_message_at?: string | null;
  post_inbound_video_expert_release_eligible?: boolean | null;
  post_inbound_video_expert_waived_at?: string | null;
  operator_replied?: boolean | null;
  unread_user_count?: number | null;
  user_level?: string | null;
};

type ListResponse = { items: ConversationRow[]; total: number };
type MessageRow = {
  id: string;
  sender_type?: string | null;
  content?: string | null;
  operator_translation_zh?: string | null;
  content_type?: string | null;
  is_operator_message?: boolean | null;
  created_at?: string | null;
};
type DetailResponse = { conversation: ConversationRow; messages: MessageRow[] };
type CountryCorrectionPreview = {
  conversation_id: string;
  current_country_code?: string | null;
  current_country_source?: string | null;
  stated_country_code?: string | null;
  telegram_phone_country?: string | null;
  country_mismatch?: boolean;
  proposed_country_code?: string | null;
  is_t1?: boolean;
  destination_url?: string | null;
  suggested_link_message?: string | null;
  t1_countries?: string[];
  route_countries?: string[];
  previous_country_code?: string | null;
  released_to_ai?: boolean;
};
type CountryUpdateMeta = { isT1?: boolean; releasedToAi?: boolean };
type OpsAiReply = { rank: number; text: string; translation_zh?: string | null; reason?: string | null };
type OpsAiAssistResponse = {
  summary: { user_state: string; key_facts: string[]; risk_flags: string[]; recommended_strategy: string };
  suggested_replies: OpsAiReply[];
};
type Counts = { handoff: number; review: number; premium: number; interest: number };
type WorkbenchTab = "handoff" | "review" | "premium" | "interest";
const EMPTY_COUNTS: Counts = { handoff: 0, review: 0, premium: 0, interest: 0 };
const QUEUE_LIST_VISIBLE_COUNT = 20;
const COUNTRY_ZH_NAMES = new Intl.DisplayNames(["zh-CN"], { type: "region" });

function countryZhName(code: string): string {
  try {
    return COUNTRY_ZH_NAMES.of(code) || "";
  } catch {
    return "";
  }
}

function formatCountryCode(code?: string | null): string {
  const normalized = String(code || "").trim().toUpperCase();
  if (!normalized || normalized === "-") return "";
  const zh = normalized.length === 2 ? countryZhName(normalized) : "";
  return zh && zh !== normalized ? `-${normalized}-${zh}` : `-${normalized}-`;
}

function queueActivityTime(user: ConversationRow): number {
  const raw = user.latest_message_at || user.last_message_at || "";
  const ts = Date.parse(raw);
  return Number.isFinite(ts) ? ts : 0;
}

function sortUsersByLatestActivity(users: ConversationRow[]): ConversationRow[] {
  return [...users].sort((left, right) => queueActivityTime(right) - queueActivityTime(left));
}

export default function ConversationWorkbenchPage() {
  const [counts, setCounts] = useState<Counts>(EMPTY_COUNTS);
  const [selected, setSelected] = useState<WorkbenchTab>("handoff");
  const [lists, setLists] = useState<Record<WorkbenchTab, ConversationRow[]>>({
    handoff: [],
    review: [],
    premium: [],
    interest: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [assist, setAssist] = useState<OpsAiAssistResponse | null>(null);
  const [assistLoading, setAssistLoading] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftNotice, setDraftNotice] = useState<string | null>(null);
  const [sendLoading, setSendLoading] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [mediaFile, setMediaFile] = useState<File | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);

  const loadConversation = useCallback(async (conversationId: string) => {
    setDetailLoading(true);
    setDetailError(null);
    setAssist(null);
    setSendError(null);
    setDraftNotice(null);
    if (mediaPreview) URL.revokeObjectURL(mediaPreview);
    setMediaFile(null);
    setMediaPreview(null);
    setDraft(window.localStorage.getItem(`conversation-draft:${conversationId}`) || "");
    try {
      setDetail(await apiFetch<DetailResponse>(
        `/admin/conversations/${conversationId}?message_limit=300&lite=true`,
      ));
    } catch (loadError) {
      setDetailError(loadError instanceof Error ? loadError.message : "聊天记录加载失败");
    } finally {
      setDetailLoading(false);
    }
  }, [mediaPreview]);

  function selectMedia(file: File | null) {
    if (mediaPreview) URL.revokeObjectURL(mediaPreview);
    setSendError(null);
    if (!file) {
      setMediaFile(null);
      setMediaPreview(null);
      return;
    }
    const isImage = file.type.startsWith("image/");
    const isVideo = file.type.startsWith("video/");
    const isAudio = file.type.startsWith("audio/");
    if (!isImage && !isVideo && !isAudio) {
      setSendError("只支持图片、视频和音频文件。");
      return;
    }
    const maxBytes = isImage ? 20 * 1024 * 1024 : isVideo ? 100 * 1024 * 1024 : 50 * 1024 * 1024;
    if (file.size > maxBytes) {
      setSendError(isImage ? "图片不能超过20MB。" : isVideo ? "视频不能超过100MB。" : "音频不能超过50MB。");
      return;
    }
    setMediaFile(file);
    setMediaPreview(URL.createObjectURL(file));
  }

  async function generateAssist() {
    if (!detail || assistLoading) return;
    setAssistLoading(true);
    setSendError(null);
    try {
      setAssist(await apiFetch<OpsAiAssistResponse>(
        `/ops-ai/conversations/${detail.conversation.conversation_id}/assist`,
        {
          method: "POST",
          body: JSON.stringify({
            language: detail.conversation.language || "zh-CN",
            tone: "warm",
            max_context_messages: 30,
          }),
        },
      ));
    } catch (assistError) {
      setSendError(assistError instanceof Error ? assistError.message : "AI建议生成失败");
    } finally {
      setAssistLoading(false);
    }
  }

  function saveDraft() {
    if (!detail) return;
    window.localStorage.setItem(`conversation-draft:${detail.conversation.conversation_id}`, draft);
    setDraftNotice("草稿已保存");
  }

  async function confirmSendDraft() {
    if (sendLoading) return;
    if (!detail) {
      setSendError("请先从左侧选择一名用户。");
      return;
    }
    if (!draft.trim() && !mediaFile) {
      setSendError("请输入要发送的内容，或选择图片、视频、音频。");
      return;
    }
    const conversationId = detail.conversation.conversation_id;
    const outboundText = draft.trim();
    const outboundFile = mediaFile;
    const contentType = outboundFile
      ? (outboundFile.type.startsWith("video/") ? "video" : outboundFile.type.startsWith("audio/") ? "audio" : "image")
      : "text";
    const localId = "local-" + Date.now();
    const nowIso = new Date().toISOString();
    setSendLoading(true);
    setSendError(null);
    setDraftNotice(null);
    setDraft("");
    selectMedia(null);
    setDetail((current) => {
      if (!current || current.conversation.conversation_id !== conversationId) return current;
      return {
        ...current,
        messages: [
          {
            id: localId,
            sender_type: "operator",
            content: outboundText || (outboundFile ? "[" + contentType + "]" : ""),
            content_type: contentType,
            is_operator_message: true,
            created_at: nowIso,
          },
          ...current.messages,
        ],
      };
    });
    setLists((prev) => {
      const next = { ...prev };
      (["handoff", "review", "premium", "interest"] as WorkbenchTab[]).forEach((tab) => {
        next[tab] = next[tab].map((user) => (
          user.conversation_id === conversationId
            ? {
                ...user,
                operator_replied: true,
                unread_user_count: 0,
                last_message_at: nowIso,
                latest_message_at: nowIso,
              }
            : user
        ));
      });
      return next;
    });
    try {
      let sent: { message_id?: string } | null = null;
      if (outboundFile) {
        const form = new FormData();
        form.append("file", outboundFile);
        form.append("caption", outboundText);
        sent = await apiFetch<{ message_id?: string }>(`/admin/conversations/${conversationId}/operator-media`, { method: "POST", body: form });
      } else {
        sent = await apiFetch<{ message_id?: string }>(`/admin/conversations/${conversationId}/operator-reply`, {
          method: "POST",
          body: JSON.stringify({ content: outboundText }),
        });
      }
      setDetail((current) => {
        if (!current || current.conversation.conversation_id !== conversationId) return current;
        return {
          ...current,
          messages: current.messages.map((message) => (
            message.id === localId && sent?.message_id
              ? { ...message, id: sent.message_id }
              : message
          )),
        };
      });
      window.localStorage.removeItem(`conversation-draft:${conversationId}`);
      setDraftNotice("已发送给用户");
    } catch (sendFailure) {
      setDraft(outboundText);
      if (outboundFile) selectMedia(outboundFile);
      setDetail((current) => {
        if (!current || current.conversation.conversation_id !== conversationId) return current;
        return {
          ...current,
          messages: current.messages.filter((message) => message.id !== localId),
        };
      });
      setSendError(sendFailure instanceof Error ? sendFailure.message : "发送失败");
    } finally {
      setSendLoading(false);
    }
  }

  const loadCounts = useCallback(async () => {
    try {
      const data = await apiFetch<{
        handoff: ListResponse;
        review: ListResponse;
        premium: ListResponse;
        interest: ListResponse;
      }>("/admin/workbench/queues");
      setLists({
        handoff: sortUsersByLatestActivity(data.handoff.items),
        review: sortUsersByLatestActivity(data.review.items),
        premium: sortUsersByLatestActivity(data.premium.items),
        interest: sortUsersByLatestActivity(data.interest.items),
      });
      setCounts({
        handoff: data.handoff.total,
        review: data.review.total,
        premium: data.premium.total,
        interest: data.interest.total,
      });
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "数据加载失败");
    }
  }, []);

  useEffect(() => {
    void loadCounts();
    const timer = window.setInterval(() => void loadCounts(), 30_000);
    return () => window.clearInterval(timer);
  }, [loadCounts]);

  return (
    <>
      <style jsx global>{`
        html, body {
          scrollbar-width: none;
          -ms-overflow-style: none;
        }
        html::-webkit-scrollbar, body::-webkit-scrollbar {
          display: none;
          width: 0;
          height: 0;
        }
      `}</style>
      <AuthGate>
        {(operator) => (
          <AdminFrame operator={operator} active="conversations" title="会话处理台" subtitle="">
          {error ? <div className="mb-4 text-sm text-rose-300">{error}</div> : null}
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <WorkbenchCard title="待人工接管" value={counts.handoff} hint="S/A 挂起、超时、待坐席处理" tone="amber" active={selected === "handoff"} onClick={() => setSelected("handoff")} />
            <WorkbenchCard title="待放行审核" value={counts.review} hint="达到视频审核条件、等待运营放行" tone="violet" active={selected === "review"} onClick={() => setSelected("review")} />
            <WorkbenchCard title="S/A 精聊用户" value={counts.premium} hint="高价值用户优先处理" tone="sky" active={selected === "premium"} onClick={() => setSelected("premium")} />
            <WorkbenchCard title="意向用户" value={counts.interest} hint="AI识别到图片、视频、VIP或通话意向" tone="emerald" active={selected === "interest"} onClick={() => setSelected("interest")} />
          </div>
          <div className="mt-3 grid items-start gap-3 lg:grid-cols-[300px_minmax(0,1fr)]">
            <UserPanel tab={selected} users={lists[selected]} total={counts[selected]} activeId={detail?.conversation.conversation_id || null} onSelect={loadConversation} />
            <div className="min-w-0 space-y-3">
              <ChatPanel
                detail={detail}
                loading={detailLoading}
                error={detailError}
                onReload={loadConversation}
                onJoinedPremium={(conversationId) => {
                  setLists((prev) => {
                    const wasHandoff = prev.handoff.some((user) => user.conversation_id === conversationId);
                    const wasReview = prev.review.some((user) => user.conversation_id === conversationId);
                    const wasPremium = prev.premium.some((user) => user.conversation_id === conversationId);
                    const moved = [...prev.handoff, ...prev.review, ...prev.premium, ...prev.interest].find(
                      (user) => user.conversation_id === conversationId,
                    ) || {
                      conversation_id: conversationId,
                      nickname: detail?.conversation.nickname,
                      external_id: detail?.conversation.external_id,
                      country_code: detail?.conversation.country_code,
                      last_message_at: new Date().toISOString(),
                      latest_message_at: new Date().toISOString(),
                    };
                    const next = {
                      handoff: prev.handoff.filter((user) => user.conversation_id !== conversationId),
                      review: prev.review.filter((user) => user.conversation_id !== conversationId),
                      premium: sortUsersByLatestActivity([
                        moved,
                        ...prev.premium.filter((user) => user.conversation_id !== conversationId),
                      ]),
                      interest: prev.interest.filter((user) => user.conversation_id !== conversationId),
                    };
                    setCounts((counts) => ({
                      handoff: Math.max(0, counts.handoff - (wasHandoff ? 1 : 0)),
                      review: Math.max(0, counts.review - (wasReview ? 1 : 0)),
                      premium: wasPremium ? counts.premium : counts.premium + 1,
                      interest: Math.max(0, counts.interest - (prev.interest.some((user) => user.conversation_id === conversationId) ? 1 : 0)),
                    }));
                    return next;
                  });
                  setSelected("premium");
                }}
                onRemovedFromQueue={(conversationId) => {
                  setLists((prev) => {
                    const next = { ...prev };
                    (["handoff", "review", "premium", "interest"] as WorkbenchTab[]).forEach((tab) => {
                      next[tab] = next[tab].filter((user) => user.conversation_id !== conversationId);
                    });
                    return next;
                  });
                  setCounts((prev) => ({
                    ...prev,
                    handoff: Math.max(0, prev.handoff - 1),
                  }));
                }}
                onCountryUpdated={(conversationId, countryCode, meta) => {
                  if (meta?.releasedToAi || meta?.isT1 === false) {
                    setLists((prev) => {
                      const next = { ...prev };
                      (["handoff", "review", "premium", "interest"] as WorkbenchTab[]).forEach((tab) => {
                        next[tab] = next[tab].filter((user) => user.conversation_id !== conversationId);
                      });
                      return next;
                    });
                    setCounts((prev) => ({
                      ...prev,
                      handoff: Math.max(0, prev.handoff - 1),
                    }));
                    return;
                  }
                  setLists((prev) => {
                    const next = { ...prev };
                    (["handoff", "review", "premium", "interest"] as WorkbenchTab[]).forEach((tab) => {
                      next[tab] = next[tab].map((user) => (
                        user.conversation_id === conversationId
                          ? { ...user, country_code: countryCode, is_t1_country: true }
                          : user
                      ));
                    });
                    return next;
                  });
                }}
              />
              <ComposePanel
                hasSelectedUser={Boolean(detail)}
                assist={assist}
                assistLoading={assistLoading}
                draft={draft}
                draftNotice={draftNotice}
                sendLoading={sendLoading}
                sendError={sendError}
                mediaFile={mediaFile}
                mediaPreview={mediaPreview}
                onDraftChange={(value) => { setDraft(value); setDraftNotice(null); }}
                onSelectMedia={selectMedia}
                onGenerateAssist={() => void generateAssist()}
                onSaveDraft={saveDraft}
                onConfirmSend={() => void confirmSendDraft()}
              />
            </div>
          </div>
          </AdminFrame>
        )}
      </AuthGate>
    </>
  );
}

function WorkbenchCard({ title, value, hint, tone, active, onClick }: {
  title: string;
  value: number;
  hint: string;
  tone: "amber" | "violet" | "sky" | "emerald";
  active: boolean;
  onClick: () => void;
}) {
  const valueTone = { amber: "text-amber-300", violet: "text-violet-300", sky: "text-sky-300", emerald: "text-emerald-300" }[tone];
  return (
    <button type="button" onClick={onClick} className={`rounded-lg border bg-slate-900 px-4 py-2 text-left transition hover:border-sky-700 hover:bg-slate-800/70 ${active ? "border-sky-600 ring-1 ring-sky-700" : "border-slate-800"}`}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-sm text-slate-300">{title}</div>
        <div className={`text-2xl font-semibold leading-none ${valueTone}`}>{value}</div>
      </div>
      <div className="mt-1 text-[11px] leading-tight text-slate-500">{hint}</div>
      <div className="mt-0.5 text-[11px] leading-tight text-sky-300">点击查看当前用户</div>
    </button>
  );
}

function UserPanel({ tab, users, total, activeId, onSelect }: { tab: WorkbenchTab; users: ConversationRow[]; total: number; activeId: string | null; onSelect: (conversationId: string) => void }) {
  const title = { handoff: "待人工接管用户", review: "待放行审核用户", premium: "S/A 精聊用户", interest: "意向用户" }[tab];
  const sortedUsers = sortUsersByLatestActivity(users);
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-3 lg:sticky lg:top-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <span className="text-xs text-slate-400">{total} 人</span>
      </div>
      {sortedUsers.length ? (
        <div
          className="flex flex-col gap-1 overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          style={{
            maxHeight: `calc(${QUEUE_LIST_VISIBLE_COUNT} * 2rem + ${QUEUE_LIST_VISIBLE_COUNT - 1} * 0.25rem)`,
          }}
        >
          {sortedUsers.map((user) => {
            const label = user.nickname || user.external_id || user.conversation_id;
            const unreadCount = Math.max(0, Number(user.unread_user_count || 0));
            const statusClass = activeId === user.conversation_id
              ? "border-amber-400 bg-sky-900/70"
              : user.operator_replied
                ? "border-pink-500 bg-pink-950/25"
                : "border-sky-700 bg-sky-950/40";
            return (
              <button type="button" key={user.conversation_id} onClick={() => onSelect(user.conversation_id)} className={`flex h-8 w-full shrink-0 items-center justify-between gap-2 rounded border px-3 text-left text-xs text-sky-200 hover:bg-sky-900/50 ${statusClass}`}>
                <span className="min-w-0 truncate">{label}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {unreadCount > 0 ? <span className="rounded-full bg-red-600 px-1.5 py-0.5 text-[11px] font-bold leading-none text-white">({unreadCount})</span> : null}
                  {user.country_code ? <span className="text-[11px] text-slate-400">{formatCountryCode(user.country_code)}</span> : null}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="py-14 text-center text-sm text-slate-500">当前没有用户</div>
      )}
    </section>
  );
}

function ChatPanel({ detail, loading, error, onReload, onRemovedFromQueue, onJoinedPremium, onCountryUpdated }: {
  detail: DetailResponse | null;
  loading: boolean;
  error: string | null;
  onReload: (conversationId: string) => Promise<void>;
  onRemovedFromQueue: (conversationId: string) => void;
  onJoinedPremium: (conversationId: string) => void;
  onCountryUpdated: (conversationId: string, countryCode: string | null, meta?: CountryUpdateMeta) => void;
}) {
  const [showOriginal, setShowOriginal] = useState(false);
  const [translationSaving, setTranslationSaving] = useState(false);
  const [translationNotice, setTranslationNotice] = useState<string | null>(null);
  const [translationError, setTranslationError] = useState<string | null>(null);

  useEffect(() => {
    setShowOriginal(false);
    setTranslationNotice(null);
    setTranslationError(null);
  }, [detail?.conversation.conversation_id]);

  async function saveVisibleChineseTranslations() {
    const conversationId = detail?.conversation.conversation_id;
    if (!conversationId || translationSaving) return;

    const translationNodes = Array.from(
      document.querySelectorAll<HTMLElement>(
        `[data-chat-conversation-id="${conversationId}"] [data-chat-message-content][data-chat-message-id]`,
      ),
    );
    const translations = translationNodes.flatMap((node) => {
      const id = String(node.dataset.chatMessageId || "").trim();
      const text = String(node.innerText || node.textContent || "").trim();
      const original = String(node.dataset.originalText || "").trim();
      if (!id || id.startsWith("local-") || !text || text === original) return [];
      return [{ id, text }];
    });

    if (!translations.length) {
      setTranslationError(null);
      setTranslationNotice("没有检测到需要保存的中文翻译。请先完成页面翻译，再点击保存。");
      return;
    }

    setTranslationSaving(true);
    setTranslationError(null);
    setTranslationNotice(null);
    try {
      const result = await apiFetch<{ saved_count?: number }>(
        `/admin/conversations/${conversationId}/message-translations`,
        { method: "POST", body: JSON.stringify({ translations }) },
      );
      const savedCount = Number(result.saved_count || 0);
      setShowOriginal(false);
      setTranslationNotice(`已保存 ${savedCount} 条中文翻译，下次打开会直接显示中文。`);
      await onReload(conversationId);
    } catch (saveError) {
      setTranslationError(saveError instanceof Error ? saveError.message : "中文翻译保存失败");
    } finally {
      setTranslationSaving(false);
    }
  }

  if (!detail && !loading && !error) {
    return (
      <section className="flex min-h-[30rem] items-center justify-center rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-500">
        请从左侧选择一名用户查看全部聊天信息
      </section>
    );
  }
  const messages = detail ? [...detail.messages].reverse() : [];
  const visibleMessages = messages;
  const userLabel = detail?.conversation.nickname || detail?.conversation.external_id || "用户";
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5" data-chat-conversation-id={detail?.conversation.conversation_id || ""}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">{userLabel} 的全部聊天信息</h2>
          {detail?.conversation.external_id ? <div className="mt-1 text-xs text-slate-500">{detail.conversation.external_id}</div> : null}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {detail ? (
            <>
              <button
                type="button"
                onClick={() => setShowOriginal((current) => !current)}
                className="rounded-md border border-slate-600 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                {showOriginal ? "查看中文" : "查看原文"}
              </button>
              <button
                type="button"
                onClick={() => void saveVisibleChineseTranslations()}
                disabled={translationSaving || showOriginal}
                className="rounded-md border border-cyan-700 bg-cyan-950/40 px-2.5 py-1 text-xs text-cyan-100 hover:bg-cyan-900/60 disabled:cursor-not-allowed disabled:opacity-50"
                title={showOriginal ? "请先切换到中文显示后再保存" : "保存浏览器翻译后当前显示的中文"}
              >
                {translationSaving ? "保存中..." : "保存本页中文翻译"}
              </button>
            </>
          ) : null}
          {detail ? (
            <CountryCorrectionBar
              conversationId={detail.conversation.conversation_id}
              countryCode={detail.conversation.country_code}
              countrySource={detail.conversation.country_source}
              userLabel={userLabel}
              alreadyPremium={["S", "A"].includes(String(detail.conversation.user_level || "").toUpperCase())}
              onReload={onReload}
              onRemovedFromQueue={onRemovedFromQueue}
              onJoinedPremium={onJoinedPremium}
              onCountryUpdated={onCountryUpdated}
            />
          ) : null}
          <span className="text-sm text-slate-400">{messages.length} 条</span>
        </div>
      </div>
      {translationNotice ? <div className="mb-4 rounded-md border border-emerald-800 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-200">{translationNotice}</div> : null}
      {translationError ? <div className="mb-4 rounded-md border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">{translationError}</div> : null}
      {loading ? <div className="py-12 text-center text-sm text-slate-500">聊天记录加载中...</div> : null}
      {error ? <div className="rounded-md border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-200">{error}</div> : null}
      {!loading && !error && visibleMessages.length ? (
        <div className="max-h-[58vh] space-y-3 overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {visibleMessages.map((message) => {
            const isUser = message.sender_type === "user";
            const sender = message.is_operator_message || message.sender_type === "operator" ? "运营" : isUser ? "用户" : "AI";
            const originalContent = message.content || `[${message.content_type || "消息"}]`;
            const displayedContent = showOriginal ? originalContent : (message.operator_translation_zh || originalContent);
            return (
              <div key={message.id} className={`flex ${isUser ? "justify-start" : "justify-end"}`}>
                <div className={`max-w-[82%] rounded-xl px-4 py-3 ${isUser ? "bg-slate-800 text-slate-100" : "bg-sky-950/60 text-sky-100"}`}>
                  <div className="mb-1 text-xs text-slate-500">{sender} · {formatChatTime(message.created_at)}</div>
                  {looksLikeChatMedia(message.content, message.content_type) ? (
                    message.id.startsWith("local-") ? (
                      <div className="text-xs text-slate-400">媒体发送中…</div>
                    ) : (
                      <InboundUserMedia
                        messageId={message.id}
                        content={message.content}
                        contentType={message.content_type}
                      />
                    )
                  ) : (
                    <div
                      className="whitespace-pre-wrap break-words text-sm leading-6"
                      data-chat-message-content="true"
                      data-chat-message-id={message.id}
                      data-original-text={originalContent}
                    >
                      {displayedContent}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      {!loading && !error && detail && !messages.length ? <div className="py-12 text-center text-sm text-slate-500">暂无聊天记录</div> : null}
    </section>
  );
}

function CountryCorrectionBar({ conversationId, countryCode, countrySource, userLabel, alreadyPremium, onReload, onRemovedFromQueue, onJoinedPremium, onCountryUpdated }: {
  conversationId: string;
  countryCode?: string | null;
  countrySource?: string | null;
  userLabel: string;
  alreadyPremium: boolean;
  onReload: (conversationId: string) => Promise<void>;
  onRemovedFromQueue: (conversationId: string) => void;
  onJoinedPremium: (conversationId: string) => void;
  onCountryUpdated: (conversationId: string, countryCode: string | null, meta?: CountryUpdateMeta) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftCode, setDraftCode] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<CountryCorrectionPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resending, setResending] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [joiningPremium, setJoiningPremium] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadPreview(nextCode?: string) {
    setLoading(true);
    setError(null);
    try {
      const query = nextCode && nextCode.length === 2 ? ("?country_code=" + encodeURIComponent(nextCode)) : "";
      setPreview(await apiFetch<CountryCorrectionPreview>(
        "/admin/conversations/" + conversationId + "/country-correction" + query,
      ));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "国家预览加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function openEditor() {
    setOpen(true);
    setNotice(null);
    setError(null);
    setNote("");
    setDraftCode((countryCode || "").toUpperCase());
    await loadPreview(countryCode || undefined);
  }

  async function saveCountry() {
    const code = draftCode.trim().toUpperCase();
    if (code.length !== 2) {
      setError("请输入两位国家代码，例如 US");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await apiFetch<CountryCorrectionPreview>("/admin/conversations/" + conversationId + "/country", {
        method: "PUT",
        body: JSON.stringify({ country_code: code, note: note.trim() || undefined }),
      });
      setPreview(updated);
      onCountryUpdated(conversationId, updated.proposed_country_code || code, {
        isT1: Boolean(updated.is_t1),
        releasedToAi: Boolean(updated.released_to_ai),
      });
      setNotice(
        updated.released_to_ai || updated.is_t1 === false
          ? "国家已更新为非 T1，已交回 AI，并从待人工列表移除。"
          : "国家已更新，会话仍由人工继续。"
      );
      await onReload(conversationId);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "国家更新失败");
    } finally {
      setSaving(false);
    }
  }

  async function joinPremiumChat() {
    if (joiningPremium || alreadyPremium) return;
    if (!window.confirm(`确认加入 S/A精聊？\n\n${userLabel}\n\n加入后：\n- 该用户会进入左侧「S/A 精聊用户」列表\n- 不会删除会话和聊天记录\n- 不会再出现在待人工列表里`)) return;
    setJoiningPremium(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch("/admin/conversations/" + conversationId + "/join-premium-chat", { method: "POST" });
      onJoinedPremium(conversationId);
      setNotice("已加入精聊，该用户已移到「S/A 精聊用户」列表。");
      await onReload(conversationId);
    } catch (joinError) {
      setError(joinError instanceof Error ? joinError.message : "加入精聊失败");
    } finally {
      setJoiningPremium(false);
    }
  }

  async function releaseToAi() {
    if (releasing) return;
    if (!window.confirm("确认放回 AI？放回后该用户会离开左侧列表，后续消息由系统自动回复。")) return;
    setReleasing(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch("/admin/conversations/" + conversationId + "/release-human", { method: "POST" });
      onRemovedFromQueue(conversationId);
      setNotice("已放回 AI，该用户已从左侧列表移除。");
      await onReload(conversationId);
    } catch (releaseError) {
      setError(releaseError instanceof Error ? releaseError.message : "放回 AI 失败");
    } finally {
      setReleasing(false);
    }
  }

  async function resendLink() {
    setResending(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch("/admin/conversations/" + conversationId + "/country-link", { method: "POST" });
      setNotice("已按当前国家补发下载链接。");
      await onReload(conversationId);
    } catch (resendError) {
      setError(resendError instanceof Error ? resendError.message : "补发链接失败");
    } finally {
      setResending(false);
    }
  }

  const options = Array.from(new Set([
    ...(preview?.t1_countries || []),
    ...(preview?.route_countries || []),
  ])).sort();
  const shownCode = preview?.proposed_country_code || countryCode || "-";
  const sourceLabel = countrySource === "operator_correction" ? "人工更正" : (countrySource || "未标注来源");

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        {!alreadyPremium ? (
          <button type="button" onClick={() => void joinPremiumChat()} disabled={joiningPremium} className="rounded-md border border-violet-700 bg-violet-950/40 px-2.5 py-1 text-xs text-violet-100 hover:bg-violet-900/60 disabled:cursor-not-allowed disabled:opacity-50">
            {joiningPremium ? "加入中..." : "加入精聊"}
          </button>
        ) : null}
        <button type="button" onClick={() => void releaseToAi()} disabled={releasing} className="rounded-md border border-sky-500 bg-sky-950/60 px-2.5 py-1 text-xs text-sky-100 hover:bg-sky-900/70 disabled:cursor-not-allowed disabled:opacity-50">
          {releasing ? "放回中..." : "放回AI"}
        </button>
        <span className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200">{formatCountryCode(countryCode) || "未知国家"}</span>
        <button type="button" onClick={() => void openEditor()} className="rounded-md border border-amber-700 px-2.5 py-1 text-xs text-amber-200 hover:bg-amber-950/40">改国家</button>
        <button type="button" onClick={() => void resendLink()} disabled={resending || !countryCode} className="rounded-md border border-emerald-700 px-2.5 py-1 text-xs text-emerald-200 hover:bg-emerald-950/40 disabled:cursor-not-allowed disabled:opacity-50">
          {resending ? "补发中..." : "补发正确链接"}
        </button>
      </div>
      {!open && error ? <div className="mt-2 rounded-md border border-rose-800 bg-rose-950/40 px-2 py-1 text-xs text-rose-200">{error}</div> : null}
      {!open && notice ? <div className="mt-2 text-xs text-emerald-300">{notice}</div> : null}
      {open ? (
        <div className="absolute right-0 z-20 mt-2 w-[22rem] rounded-xl border border-slate-700 bg-slate-950 p-4 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-medium text-white">更正用户国家</div>
            <button type="button" onClick={() => setOpen(false)} className="text-xs text-slate-400 hover:text-slate-200">关闭</button>
          </div>
          <p className="mb-3 text-xs leading-5 text-slate-400">改成 T1 国家仍留在待人工列表。改成非 T1（例如 MX）会交回 AI，并从左侧列表移除。</p>
          <label className="mb-1 block text-xs text-slate-400">国家代码</label>
          <input
            list={"country-correction-" + conversationId}
            value={draftCode}
            maxLength={2}
            onChange={(event) => {
              const next = event.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 2);
              setDraftCode(next);
              if (next.length === 2) void loadPreview(next);
            }}
            placeholder="US"
            className="mb-2 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm uppercase tracking-widest text-white"
          />
          <datalist id={"country-correction-" + conversationId}>
            {options.map((code) => <option key={code} value={code} />)}
          </datalist>
          <label className="mb-1 block text-xs text-slate-400">备注（可选）</label>
          <input value={note} onChange={(event) => setNote(event.target.value.slice(0, 200))} placeholder="例如：用户自述在美国" className="mb-3 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" />
          <div className="mb-3 space-y-1 rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300">
            <div>当前：{formatCountryCode(preview?.current_country_code || countryCode) || "-"} · {sourceLabel}</div>
            <div>拟定：{formatCountryCode(shownCode) || shownCode}{preview?.is_t1 ? " · T1" : preview ? " · 非 T1" : ""}</div>
            <div>自述：{formatCountryCode(preview?.stated_country_code) || preview?.stated_country_code || "-"} · 手机号：{formatCountryCode(preview?.telegram_phone_country) || preview?.telegram_phone_country || "-"}</div>
            {preview?.country_mismatch ? <div className="text-amber-300">自述/手机号与分级国家不一致，会保留原证据并标记 mismatch。</div> : null}
            <div className="break-all text-slate-400">链接：{loading ? "预览加载中..." : (preview?.destination_url || "暂无")}</div>
          </div>
          {error ? <div className="mb-3 rounded-md border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">{error}</div> : null}
          {notice ? <div className="mb-3 text-xs text-emerald-300">{notice}</div> : null}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => void saveCountry()} disabled={saving} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50">
              {saving ? "保存中..." : "保存国家"}
            </button>
            <button type="button" onClick={() => void resendLink()} disabled={resending || !(preview?.proposed_country_code || countryCode)} className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">
              {resending ? "补发中..." : "补发正确链接"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
function ComposePanel({ hasSelectedUser, assist, assistLoading, draft, draftNotice, sendLoading, sendError, mediaFile, mediaPreview, onDraftChange, onSelectMedia, onGenerateAssist, onSaveDraft, onConfirmSend }: {
  hasSelectedUser: boolean;
  assist: OpsAiAssistResponse | null;
  assistLoading: boolean;
  draft: string;
  draftNotice: string | null;
  sendLoading: boolean;
  sendError: string | null;
  mediaFile: File | null;
  mediaPreview: string | null;
  onDraftChange: (value: string) => void;
  onSelectMedia: (file: File | null) => void;
  onGenerateAssist: () => void;
  onSaveDraft: () => void;
  onConfirmSend: () => void;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">AI辅助与人工草稿</h2>
          <p className="mt-3 text-sm text-slate-400">AI 只基于当前聊天生成建议，最终发送由坐席确认。</p>
        </div>
        <button type="button" onClick={onGenerateAssist} disabled={!hasSelectedUser || assistLoading} className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50">
          {assistLoading ? "生成中..." : assist ? "重新生成" : "生成建议"}
        </button>
      </div>
      {assist ? (
        <div className="mb-4 rounded-lg border border-slate-800 bg-slate-950 p-4">
          <div className="mb-3 text-sm text-slate-400">推荐策略：{assist.summary.recommended_strategy || "按当前聊天自然回复"}</div>
          <div className="grid gap-3 md:grid-cols-3">
            {assist.suggested_replies.map((reply) => (
              <button key={reply.rank} type="button" onClick={() => onDraftChange(reply.text)} className="rounded-md border border-slate-800 p-3 text-left text-sm text-slate-200 hover:border-violet-600">
                <div className="mb-2 text-xs text-violet-300">建议回复 {reply.rank}</div>
                <div className="whitespace-pre-wrap break-words">{reply.text}</div>
                {reply.translation_zh ? <div className="mt-2 border-t border-slate-800 pt-2 text-xs text-amber-200">{reply.translation_zh}</div> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {sendError ? <div className="mb-3 rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{sendError}</div> : null}
      {draftNotice ? <div className="mb-3 text-sm text-emerald-300">{draftNotice}</div> : null}
      {!hasSelectedUser ? <div className="mb-3 text-sm text-amber-300">请先在上方点击一个用户，再输入或生成回复内容。</div> : null}
      <textarea disabled={!hasSelectedUser} value={draft} onChange={(event) => onDraftChange(event.target.value)} rows={6} placeholder={hasSelectedUser ? "选择 AI 建议后在这里修改，或直接输入要发送给用户的内容。" : "选择用户后即可在这里聊天。"} className="w-full rounded-md border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 disabled:cursor-not-allowed disabled:opacity-60" />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className={`cursor-pointer rounded-md border border-sky-700 px-3 py-2 text-sm text-sky-200 hover:bg-sky-950/50 ${!hasSelectedUser ? "pointer-events-none opacity-50" : ""}`}>
          选择图片
          <input type="file" accept="image/*" className="hidden" onChange={(event) => { onSelectMedia(event.target.files?.[0] || null); event.currentTarget.value = ""; }} />
        </label>
        <label className={`cursor-pointer rounded-md border border-cyan-700 px-3 py-2 text-sm text-cyan-200 hover:bg-cyan-950/50 ${!hasSelectedUser ? "pointer-events-none opacity-50" : ""}`}>
          选择视频
          <input type="file" accept="video/*" className="hidden" onChange={(event) => { onSelectMedia(event.target.files?.[0] || null); event.currentTarget.value = ""; }} />
        </label>
        <label className={`cursor-pointer rounded-md border border-amber-700 px-3 py-2 text-sm text-amber-200 hover:bg-amber-950/50 ${!hasSelectedUser ? "pointer-events-none opacity-50" : ""}`}>
          选择音频
          <input type="file" accept="audio/*" className="hidden" onChange={(event) => { onSelectMedia(event.target.files?.[0] || null); event.currentTarget.value = ""; }} />
        </label>
        <span className="text-xs text-slate-500">图片最大20MB，视频最大100MB，音频最大50MB</span>
      </div>
      {mediaFile && mediaPreview ? (
        <div className="mt-3 flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-950 p-3">
          {mediaFile.type.startsWith("image/") ? (
            <img src={mediaPreview} alt="待发送图片" className="max-h-40 max-w-56 rounded object-contain" />
          ) : mediaFile.type.startsWith("video/") ? (
            <video src={mediaPreview} controls className="max-h-48 max-w-sm rounded" />
          ) : (
            <audio src={mediaPreview} controls className="w-80 max-w-full" />
          )}
          <div className="min-w-0 text-xs text-slate-400">
            <div className="break-all text-slate-200">{mediaFile.name}</div>
            <div className="mt-1">{(mediaFile.size / 1024 / 1024).toFixed(2)} MB</div>
            <button type="button" onClick={() => onSelectMedia(null)} className="mt-3 text-rose-300 hover:text-rose-200">移除文件</button>
          </div>
        </div>
      ) : null}
      <div className="mt-4 flex justify-end gap-3">
        <button type="button" onClick={onSaveDraft} disabled={!hasSelectedUser} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">保存草稿</button>
        <button type="button" onClick={onConfirmSend} disabled={sendLoading} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">
          {sendLoading ? "发送中..." : "确认发送"}
        </button>
      </div>
    </section>
  );
}

function formatChatTime(value?: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}
