"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型 ──────────────────────────────────────────────────────────

interface ConversationRow {
  conversation_id: string;
  state: string | null;
  handoff_count: number | null;
  channel: string | null;
  last_message_at: string | null;
  created_at: string | null;
  assigned_operator_id: string | null;
  user_id: string | null;
  nickname: string | null;
  external_id: string | null;
  user_channel: string | null;
  risk_level: string | null;
  user_status: string | null;
  loneliness_score: number | null;
  vip_level: number | null;
  relationship_stage: string | null;
  character_id: string | null;
  character_name: string | null;
}

interface ListResponse {
  items: ConversationRow[];
  total: number;
  page: number;
  page_size: number;
}

interface MessageRow {
  id: string;
  sender_type: string | null;
  content: string | null;
  content_type: string | null;
  is_operator_message: boolean | null;
  model_name: string | null;
  safety_result: unknown;
  created_at: string | null;
}

interface DetailResponse {
  conversation: ConversationRow & {
    ai_model_used?: string | null;
    language?: string | null;
    timezone?: string | null;
    chat_style?: string | null;
    interests?: unknown;
    forbidden_topics?: unknown;
  };
  messages: MessageRow[];
}

interface OpsAiSummary {
  user_state: string;
  key_facts: string[];
  risk_flags: string[];
  recommended_strategy: string;
}

interface OpsAiReply {
  rank: number;
  text: string;
  reason: string;
}

interface OpsAiAssistResponse {
  conversation_id: string;
  handoff_task_id: string | null;
  summary: OpsAiSummary;
  suggested_replies: OpsAiReply[];
  model_used?: string | null;
  latency_ms?: number | null;
}

interface TranslationResponse {
  translations: Array<{
    id: string;
    text: string;
  }>;
  model_used?: string | null;
  latency_ms?: number | null;
}

const STATE_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "AI_ACTIVE", label: "AI 活跃" },
  { value: "WAITING_OPERATOR", label: "等待接管" },
  { value: "HUMAN_LOCKED", label: "人工锁定" },
  { value: "CLOSED", label: "已关闭" },
];

const CHANNEL_OPTIONS = [
  { value: "", label: "全部渠道" },
  { value: "telegram", label: "Telegram" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "web", label: "Web" },
  { value: "discord", label: "Discord" },
];

const PAGE_SIZE = 20;

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function stateColor(s: string | null): string {
  switch (s) {
    case "AI_ACTIVE":
      return "bg-emerald-900/40 text-emerald-300 border-emerald-800";
    case "WAITING_OPERATOR":
      return "bg-amber-900/40 text-amber-300 border-amber-800";
    case "HUMAN_LOCKED":
      return "bg-violet-900/40 text-violet-300 border-violet-800";
    case "CLOSED":
      return "bg-slate-800 text-slate-400 border-slate-700";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

function riskColor(r: string | null): string {
  switch (r) {
    case "high":
      return "text-rose-400";
    case "elevated":
      return "text-amber-400";
    case "normal":
    default:
      return "text-slate-400";
  }
}

// ── 主页面（内部组件，由 AuthGate 传入 operator） ─────────────────

function DashboardContent({ operator }: { operator: Operator }) {
  // 列表状态
  const [items, setItems] = useState<ConversationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [state, setState] = useState("");
  const [channel, setChannel] = useState("");
  const [search, setSearch] = useState("");
  // 已应用的搜索词；仅在用户点击 [搜索] / [重置] 时更新，避免每个键击都请求
  const [appliedSearch, setAppliedSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 详情抽屉
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [assist, setAssist] = useState<OpsAiAssistResponse | null>(null);
  const [assistLoading, setAssistLoading] = useState(false);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [copiedReplyRank, setCopiedReplyRank] = useState<number | null>(null);
  const [draftReply, setDraftReply] = useState("");
  const [messageTranslations, setMessageTranslations] = useState<Record<string, string>>({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (state) qs.set("state", state);
      if (channel) qs.set("channel", channel);
      if (appliedSearch.trim()) qs.set("search", appliedSearch.trim());
      const resp = await apiFetch<ListResponse>(
        `/admin/conversations?${qs.toString()}`
      );
      setItems(resp.items);
      setTotal(resp.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, state, channel, appliedSearch]);

  useEffect(() => {
    load();
  }, [load]);

  async function openDetail(cid: string) {
    setDetail(null);
    setDetailError(null);
    setAssist(null);
    setAssistError(null);
    setDraftReply("");
    setMessageTranslations({});
    setTranslationError(null);
    setDetailLoading(true);
    try {
      const resp = await apiFetch<DetailResponse>(
        `/admin/conversations/${cid}`
      );
      setDetail(resp);
      void translateMessages(resp);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  }

  async function translateMessages(resp: DetailResponse) {
    const items = resp.messages
      .filter((m) => (m.content || "").trim())
      .map((m) => ({
        id: m.id,
        text: m.content || "",
        sender_type: m.sender_type,
      }));
    if (items.length === 0) {
      setMessageTranslations({});
      return;
    }

    setTranslationLoading(true);
    setTranslationError(null);
    try {
      const preserveTerms = [
        resp.conversation.nickname,
        resp.conversation.external_id,
      ].filter((v): v is string => !!v && v.trim().length > 0);
      const translated = await apiFetch<TranslationResponse>("/ops-ai/translate", {
        method: "POST",
        body: JSON.stringify({
          target_language: "zh-CN",
          preserve_terms: preserveTerms,
          items,
        }),
      });
      setMessageTranslations(
        Object.fromEntries(
          translated.translations.map((item) => [item.id, item.text])
        )
      );
    } catch (e) {
      setTranslationError(e instanceof Error ? e.message : String(e));
      setMessageTranslations({});
    } finally {
      setTranslationLoading(false);
    }
  }

  async function generateAssist() {
    if (!detail) return;
    setAssistLoading(true);
    setAssistError(null);
    try {
      const resp = await apiFetch<OpsAiAssistResponse>(
        `/ops-ai/conversations/${detail.conversation.conversation_id}/assist`,
        {
          method: "POST",
          body: JSON.stringify({
            language: detail.conversation.language || "zh-CN",
            tone: "warm",
            max_context_messages: 30,
          }),
        }
      );
      setAssist(resp);
    } catch (e) {
      setAssistError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssistLoading(false);
    }
  }

  async function copyReply(reply: OpsAiReply) {
    await navigator.clipboard.writeText(reply.text);
    setCopiedReplyRank(reply.rank);
    window.setTimeout(() => setCopiedReplyRank(null), 1500);
  }

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setAppliedSearch(search);
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-400 text-sm">运营后台</span>
          <nav className="flex items-center gap-1 ml-4">
            <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
              会话
            </span>
            <a
              href="/admin/memories"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              记忆
            </a>
            <a
              href="/admin/scripts"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              话术库
            </a>
            <a
              href="/admin/characters"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              角色
            </a>
            <a
              href="/admin/push"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              推送
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-300">
            {operator.display_name || operator.username}
            <span className="ml-2 text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
              {operator.role}
            </span>
          </span>
          <button
            onClick={handleLogout}
            className="text-sm text-slate-400 hover:text-white transition"
          >
            退出
          </button>
        </div>
      </header>

      {/* Main */}
      <main className="p-8 max-w-7xl mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold mb-1">会话总览</h1>
            <p className="text-slate-400 text-sm">
              共 {total} 条会话 · 第 {page} / {totalPages} 页
            </p>
          </div>
        </div>

        {/* Filters */}
        <form
          onSubmit={handleSearchSubmit}
          className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex flex-wrap items-center gap-3"
        >
          <select
            value={state}
            onChange={(e) => {
              setPage(1);
              setState(e.target.value);
            }}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {STATE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            value={channel}
            onChange={(e) => {
              setPage(1);
              setChannel(e.target.value);
            }}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {CHANNEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索昵称 / external_id"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 flex-1 min-w-[200px]"
          />
          <button
            type="submit"
            className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
          >
            搜索
          </button>
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setAppliedSearch("");
              setState("");
              setChannel("");
              setPage(1);
            }}
            className="text-slate-400 hover:text-white text-sm transition"
          >
            重置
          </button>
        </form>

        {/* Error */}
        {error && (
          <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
            加载失败：{error}
          </div>
        )}

        {/* Table */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3 font-medium">用户</th>
                <th className="text-left px-4 py-3 font-medium">渠道</th>
                <th className="text-left px-4 py-3 font-medium">状态</th>
                <th className="text-left px-4 py-3 font-medium">角色</th>
                <th className="text-right px-4 py-3 font-medium">孤独感分</th>
                <th className="text-left px-4 py-3 font-medium">风险</th>
                <th className="text-left px-4 py-3 font-medium">最后消息</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60">
              {loading && (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-8 text-center text-slate-500"
                  >
                    加载中…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-12 text-center text-slate-500"
                  >
                    暂无会话
                  </td>
                </tr>
              )}
              {!loading &&
                items.map((row) => (
                  <tr
                    key={row.conversation_id}
                    className="hover:bg-slate-700/30 transition"
                  >
                    <td className="px-4 py-3">
                      <div className="text-slate-100">
                        {row.nickname || (
                          <span className="text-slate-500 italic">未命名</span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 font-mono">
                        {row.external_id || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {row.channel || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${stateColor(
                          row.state
                        )}`}
                      >
                        {row.state || "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {row.character_name || "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                      {row.loneliness_score != null
                        ? row.loneliness_score.toFixed(1)
                        : "—"}
                    </td>
                    <td className={`px-4 py-3 ${riskColor(row.risk_level)}`}>
                      {row.risk_level || "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {fmtTime(row.last_message_at || row.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                      {row.user_id && (
                        <a
                          href={`/admin/users/${row.user_id}`}
                          className="text-sky-400 hover:text-sky-300 text-xs"
                          title="用户画像"
                        >
                          画像
                        </a>
                      )}
                      <button
                        onClick={() => openDetail(row.conversation_id)}
                        className="text-violet-400 hover:text-violet-300 text-xs"
                      >
                        详情
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-4 text-sm">
          <span className="text-slate-500">
            第 {page} / {totalPages} 页
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="px-3 py-1.5 border border-slate-700 rounded-md text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              上一页
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="px-3 py-1.5 border border-slate-700 rounded-md text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              下一页
            </button>
          </div>
        </div>
      </main>

      {/* 详情抽屉 */}
      {(detail || detailLoading || detailError) && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex justify-end"
          onClick={() => {
            setDetail(null);
            setDetailError(null);
            setAssist(null);
            setAssistError(null);
            setDraftReply("");
            setMessageTranslations({});
            setTranslationError(null);
          }}
        >
          <div
            className="w-full max-w-2xl bg-slate-900 h-full border-l border-slate-700 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">会话详情</h2>
              <button
                onClick={() => {
                  setDetail(null);
                  setDetailError(null);
                  setAssist(null);
                  setAssistError(null);
                  setDraftReply("");
                  setMessageTranslations({});
                  setTranslationError(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="p-6 space-y-6">
              {detailLoading && (
                <p className="text-slate-500 text-sm">加载中…</p>
              )}
              {detailError && (
                <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
                  {detailError}
                </div>
              )}
              {detail && (
                <>
                  {/* 元信息 */}
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <Meta label="昵称" value={detail.conversation.nickname} />
                    <Meta
                      label="外部 ID"
                      value={detail.conversation.external_id}
                      mono
                    />
                    <Meta label="渠道" value={detail.conversation.channel} />
                    <Meta label="状态" value={detail.conversation.state} />
                    <Meta
                      label="角色"
                      value={detail.conversation.character_name}
                    />
                    <Meta
                      label="AI 模型"
                      value={detail.conversation.ai_model_used}
                    />
                    <Meta
                      label="孤独感分"
                      value={
                        detail.conversation.loneliness_score != null
                          ? detail.conversation.loneliness_score.toFixed(1)
                          : null
                      }
                    />
                    <Meta
                      label="风险等级"
                      value={detail.conversation.risk_level}
                    />
                    <Meta
                      label="关系阶段"
                      value={detail.conversation.relationship_stage}
                    />
                    <Meta
                      label="VIP 等级"
                      value={
                        detail.conversation.vip_level != null
                          ? String(detail.conversation.vip_level)
                          : null
                      }
                    />
                    <Meta
                      label="创建时间"
                      value={fmtTime(detail.conversation.created_at)}
                    />
                    <Meta
                      label="最后消息"
                      value={fmtTime(detail.conversation.last_message_at)}
                    />
                  </div>

                  {/* 快捷导航 */}
                  {detail.conversation.user_id && (
                    <div className="flex gap-3">
                      <a
                        href={`/admin/users/${detail.conversation.user_id}`}
                        className="text-sm text-sky-400 hover:text-sky-300 transition"
                      >
                        查看画像
                      </a>
                      <a
                        href={`/admin/memories?user_id=${detail.conversation.user_id}`}
                        className="text-sm text-violet-400 hover:text-violet-300 transition"
                      >
                        查看记忆
                      </a>
                    </div>
                  )}

                  {/* AI 辅助 */}
                  <div className="border border-violet-800/70 bg-violet-950/20 rounded-xl p-4 space-y-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-sm font-medium text-violet-200">
                          AI 辅助：摘要 + 3 条推荐回复
                        </h3>
                        <p className="text-xs text-slate-400 mt-1">
                          仅供人工参考，不会自动发送消息。
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={generateAssist}
                        disabled={assistLoading}
                        className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium px-3 py-2 rounded-md transition whitespace-nowrap"
                      >
                        {assistLoading ? "生成中…" : assist ? "重新生成" : "生成建议"}
                      </button>
                    </div>

                    {assistError && (
                      <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-3 py-2 flex items-center justify-between gap-3">
                        <span>生成失败：{assistError}</span>
                        <button
                          type="button"
                          onClick={generateAssist}
                          disabled={assistLoading}
                          className="text-xs text-rose-100 hover:text-white underline"
                        >
                          重试
                        </button>
                      </div>
                    )}

                    {assist && (
                      <>
                        <div className="grid gap-3 text-sm">
                          <AssistBlock
                            label="用户当前状态"
                            value={assist.summary.user_state}
                          />
                          <AssistList
                            label="关键事实"
                            items={assist.summary.key_facts}
                          />
                          <AssistList
                            label="风险 flags"
                            items={assist.summary.risk_flags}
                            empty="暂无明显风险"
                          />
                          <AssistBlock
                            label="推荐处理策略"
                            value={assist.summary.recommended_strategy}
                          />
                        </div>

                        <div className="space-y-3">
                          {assist.suggested_replies.map((reply) => (
                            <div
                              key={reply.rank}
                              className="border border-slate-700 bg-slate-900/70 rounded-lg p-3"
                            >
                              <div className="flex items-center justify-between gap-3 mb-2">
                                <span className="text-xs text-violet-300">
                                  推荐回复 {reply.rank}
                                </span>
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    onClick={() => copyReply(reply)}
                                    className="text-xs text-sky-400 hover:text-sky-300"
                                  >
                                    {copiedReplyRank === reply.rank ? "已复制" : "复制"}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setDraftReply(reply.text)}
                                    className="text-xs text-violet-400 hover:text-violet-300"
                                  >
                                    填入草稿
                                  </button>
                                </div>
                              </div>
                              <p className="text-sm text-slate-100 whitespace-pre-wrap">
                                {reply.text}
                              </p>
                              {reply.reason && (
                                <p className="text-xs text-slate-500 mt-2">
                                  理由：{reply.reason}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>

                        <div>
                          <label className="block text-xs text-slate-400 mb-2">
                            运营回复草稿（需人工确认后再发送）
                          </label>
                          <textarea
                            value={draftReply}
                            onChange={(e) => setDraftReply(e.target.value)}
                            rows={4}
                            placeholder="点击“填入草稿”后可在这里编辑；当前页面不会自动发送。"
                            className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-100 placeholder-slate-600"
                          />
                        </div>
                      </>
                    )}
                  </div>

                  {/* 消息流 */}
                  <div>
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <h3 className="text-sm font-medium text-slate-300">
                        最近消息（中文展示，最多 50 条）
                      </h3>
                      {translationLoading && (
                        <span className="text-xs text-slate-500">正在翻译…</span>
                      )}
                    </div>
                    {translationError && (
                      <div className="bg-amber-900/20 border border-amber-800 text-amber-200 text-xs rounded-md px-3 py-2 mb-3">
                        翻译失败，当前显示原文：{translationError}
                      </div>
                    )}
                    {detail.messages.length === 0 ? (
                      <p className="text-slate-500 text-sm">暂无消息</p>
                    ) : (
                      <div className="space-y-3">
                        {[...detail.messages].reverse().map((m) => (
                          <MessageBubble
                            key={m.id}
                            msg={m}
                            translatedContent={messageTranslations[m.id]}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 页面入口（AuthGate 包裹，守卫由 AuthGate 统一处理） ───────────

export default function DashboardPage() {
  return (
    <AuthGate>
      {(operator) => <DashboardContent operator={operator} />}
    </AuthGate>
  );
}

// ── 小组件 ────────────────────────────────────────────────────────

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div
        className={`text-slate-200 ${mono ? "font-mono text-xs" : ""}`}
      >
        {value || <span className="text-slate-600">—</span>}
      </div>
    </div>
  );
}

function AssistBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className="text-slate-200">{value || "—"}</div>
    </div>
  );
}

function AssistList({
  label,
  items,
  empty = "—",
}: {
  label: string;
  items: string[];
  empty?: string;
}) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      {items.length === 0 ? (
        <div className="text-slate-500">{empty}</div>
      ) : (
        <ul className="list-disc list-inside text-slate-200 space-y-1">
          {items.map((item, idx) => (
            <li key={`${item}-${idx}`}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MessageBubble({
  msg,
  translatedContent,
}: {
  msg: MessageRow;
  translatedContent?: string;
}) {
  const isUser = msg.sender_type === "user";
  const isAssistant = msg.sender_type === "assistant" || msg.sender_type === "ai";
  const isOperator =
    msg.is_operator_message || msg.sender_type === "operator";
  const originalContent = msg.content || "";
  const displayContent = translatedContent || originalContent;
  const hasTranslated =
    !!translatedContent && translatedContent.trim() !== originalContent.trim();

  let bg = "bg-slate-800 border-slate-700";
  let label = msg.sender_type || "unknown";

  if (isUser) {
    bg = "bg-slate-800 border-slate-700";
    label = "用户";
  } else if (isOperator) {
    bg = "bg-amber-900/30 border-amber-800";
    label = "运营";
  } else if (isAssistant) {
    bg = "bg-violet-900/30 border-violet-800";
    label = msg.model_name ? `AI · ${msg.model_name}` : "AI";
  }

  return (
    <div className={`border rounded-lg px-4 py-3 ${bg}`}>
      <div className="flex items-center justify-between text-xs mb-2">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-500">{fmtTime(msg.created_at)}</span>
      </div>
      <div className="text-slate-100 text-sm whitespace-pre-wrap break-words">
        {displayContent || <span className="text-slate-500 italic">（空）</span>}
      </div>
      {hasTranslated && (
        <details className="mt-2 text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">
            查看原文
          </summary>
          <div className="mt-1 whitespace-pre-wrap break-words text-slate-400">
            {originalContent}
          </div>
        </details>
      )}
    </div>
  );
}
