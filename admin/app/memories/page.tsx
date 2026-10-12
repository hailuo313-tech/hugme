"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";

interface MemoryRow {
  id: string;
  user_id: string;
  memory_type: string | null;
  content: string | null;
  importance_score: number | null;
  memory_scope: string | null;
  character_id: string | null;
  created_at: string | null;
  last_used_at: string | null;
}

interface RetrieveHit {
  id: string;
  content: string;
  memory_type: string | null;
  importance_score: number | null;
  final_score: number;
  similarity: number;
  created_at: string | null;
}

interface ConversationSearchItem {
  user_id: string | null;
  nickname: string | null;
  external_id: string | null;
}

interface UserDataExport {
  user: {
    id: string;
    external_id: string | null;
    nickname: string | null;
    language: string | null;
    status: string | null;
    risk_level: string | null;
    created_at: string | null;
    updated_at: string | null;
  } | null;
  profile: {
    country_code: string | null;
    city?: string | null;
    age?: number | string | null;
    preferences: Record<string, unknown> | null;
    loneliness_score: number | null;
    vip_level: number | null;
    relationship_stage: string | null;
    user_level?: string | null;
  } | null;
  recent_messages?: Array<{
    id: string;
    sender_type: string | null;
    content: string | null;
    created_at: string | null;
  }>;
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

interface TranslateResponse {
  translations: Array<{ id: string; text: string }>;
}

const MEMORY_TYPE_LABELS: Record<string, string> = {
  fact: "基础信息",
  preference: "兴趣偏好",
  event: "近期事件",
  emotion: "情绪状态",
  relationship: "关系信息",
  goal: "目标诉求",
  milestone: "关键节点",
};

function memoryTypeLabel(type: string | null | undefined): string {
  if (!type) return "未分类";
  return MEMORY_TYPE_LABELS[type] || "其他信息";
}

function memoryScopeLabel(scope: string | null | undefined): string | null {
  if (!scope) return null;
  if (scope === "global") return "全局";
  if (scope === "character") return "角色专属";
  return scope;
}

function displayProfileValue(value: unknown, fallback = "未记录"): string {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text ? text : fallback;
}

async function translateToChinese(
  items: Array<{ id: string; text: string }>,
): Promise<Record<string, string>> {
  if (items.length === 0) return {};
  const response = await apiFetch<TranslateResponse>("/ops-ai/translate", {
    method: "POST",
    body: JSON.stringify({
      target_language: "zh-CN",
      items: items.map((item) => ({
        id: item.id,
        text: item.text,
        sender_type: "assistant",
      })),
    }),
  });
  const merged: Record<string, string> = {};
  for (const item of response.translations || []) {
    merged[item.id] = item.text;
  }
  return merged;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f-]{36}$/i.test(value.trim());
}

function MemoriesContent({ operator }: { operator: Operator }) {
  const searchParams = useSearchParams();
  const initialUserId = searchParams.get("user_id")?.trim() || "";

  const [lookupInput, setLookupInput] = useState(initialUserId);
  const [userId, setUserId] = useState(initialUserId);
  const [userLabel, setUserLabel] = useState<string | null>(null);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retrieveQuery, setRetrieveQuery] = useState("");
  const [retrieveLoading, setRetrieveLoading] = useState(false);
  const [retrieveHits, setRetrieveHits] = useState<RetrieveHit[]>([]);
  const [retrieveMeta, setRetrieveMeta] = useState<string | null>(null);
  const [analysisSummary, setAnalysisSummary] = useState("请先查询用户，系统会根据该用户的长期记忆生成分析总结。");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [userData, setUserData] = useState<UserDataExport | null>(null);

  const resolveUserId = useCallback(async (input: string): Promise<{ userId: string; label: string } | null> => {
    const trimmed = input.trim();
    if (!trimmed) return null;
    if (isUuid(trimmed)) {
      return { userId: trimmed, label: trimmed };
    }

    const response = await apiFetch<{ items: ConversationSearchItem[] }>(
      `/memories/resolve-user?query=${encodeURIComponent(trimmed)}`,
    );
    const row = response.items?.[0];
    if (!row?.user_id) return null;
    const label = [row.nickname, row.external_id].filter(Boolean).join(" / ") || row.user_id;
    return { userId: row.user_id, label };
  }, []);

  const loadMemories = useCallback(async (targetUserId: string) => {
    setLoading(true);
    setError(null);
    setRetrieveHits([]);
    setRetrieveMeta(null);
    try {
      const [rows, dataExport] = await Promise.all([
        apiFetch<MemoryRow[]>(`/users/${targetUserId}/memories`),
        apiFetch<UserDataExport>(`/users/${targetUserId}/data-export`),
      ]);
      setMemories(rows || []);
      setUserData(dataExport || null);
      setUserId(targetUserId);
      const url = new URL(window.location.href);
      url.searchParams.set("user_id", targetUserId);
      window.history.replaceState(null, "", url.toString());
    } catch (err) {
      setMemories([]);
      setUserData(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const handleLookup = useCallback(async () => {
    setError(null);
    setUserLabel(null);
    try {
      const resolved = await resolveUserId(lookupInput);
      if (!resolved) {
        setError("找不到该用户，请输入有效的 user_id 或 external_id（如 tg_123456789）。");
        setMemories([]);
        setUserId("");
        return;
      }
      setUserLabel(resolved.label);
      await loadMemories(resolved.userId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [loadMemories, lookupInput, resolveUserId]);

  useEffect(() => {
    if (!initialUserId) return;
    setLookupInput(initialUserId);
    void (async () => {
      try {
        const resolved = await resolveUserId(initialUserId);
        if (resolved) {
          setUserLabel(resolved.label);
          await loadMemories(resolved.userId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [initialUserId, loadMemories, resolveUserId]);

  async function handleRetrieve(event: React.FormEvent) {
    event.preventDefault();
    if (!userId || !retrieveQuery.trim()) return;
    setRetrieveLoading(true);
    setRetrieveMeta(null);
    try {
      const response = await apiFetch<{
        hits: RetrieveHit[];
        embedding_used: boolean;
        fallback_reason: string | null;
        latency_ms: number;
      }>(`/users/${userId}/memories/retrieve`, {
        method: "POST",
        body: JSON.stringify({ query: retrieveQuery.trim(), k: 10 }),
      });
      setRetrieveHits(response.hits || []);
      setRetrieveMeta(
        `召回 ${response.hits?.length || 0} 条 · ${response.embedding_used ? "向量检索" : "关键词回退"} · ${response.latency_ms}ms`,
      );
    } catch (err) {
      setRetrieveHits([]);
      setRetrieveMeta(err instanceof Error ? err.message : String(err));
    } finally {
      setRetrieveLoading(false);
    }
  }

  async function handleDelete(memoryId: string) {
    if (!window.confirm("确认停用这条记忆？停用后 AI 将不再使用它。")) return;
    try {
      await apiFetch(`/memories/${memoryId}`, { method: "DELETE" });
      if (userId) await loadMemories(userId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const sortedMemories = useMemo(
    () =>
      [...memories].sort((a, b) => {
        const scoreDiff = (b.importance_score ?? 0) - (a.importance_score ?? 0);
        if (scoreDiff !== 0) return scoreDiff;
        return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
      }),
    [memories],
  );

  useEffect(() => {
    if (!userId) {
      setAnalysisSummary("请先查询用户，系统会根据该用户的长期记忆生成分析总结。");
      setAnalysisLoading(false);
      return;
    }
    if (sortedMemories.length === 0) {
      const recentUserMessages = (userData?.recent_messages || [])
        .filter((message) => message.sender_type === "user" && message.content?.trim())
        .slice(0, 6);
      const latestUserSignals = recentUserMessages
        .map((message) => message.content?.trim())
        .filter(Boolean)
        .join("；");
      setAnalysisSummary(
        recentUserMessages.length > 0
          ? `该用户目前暂无活跃长期记忆，但已有 ${userData?.recent_messages?.length || 0} 条近期聊天记录可参考。用户最近表达过：${latestUserSignals}。运营回复时应优先承接这些最新上下文，继续观察并等待系统写入稳定记忆。`
          : "该用户目前暂无活跃记忆，也没有可参考的近期聊天内容，暂时无法形成稳定画像。建议继续观察用户的偏好、关系状态、情绪痛点和近期目标。",
      );
      setAnalysisLoading(false);
      return;
    }

    let cancelled = false;
    setAnalysisLoading(true);

    void (async () => {
      try {
        const typeCounts = sortedMemories.reduce<Record<string, number>>((acc, memory) => {
          const key = memory.memory_type || "未分类";
          acc[key] = (acc[key] || 0) + 1;
          return acc;
        }, {});
        const topTypes = Object.entries(typeCounts)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([type, count]) => `${memoryTypeLabel(type)} ${count} 条`)
          .join("、");

        const importantMemories = sortedMemories
          .filter((memory) => (memory.importance_score ?? 0) >= 7)
          .slice(0, 3);
        const recentMemories = [...sortedMemories]
          .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
          .slice(0, 2);
        const signalSource = importantMemories.length > 0 ? importantMemories : recentMemories;
        const signalItems = signalSource
          .map((memory, index) => ({
            id: String(index),
            text: memory.content?.trim() || "",
          }))
          .filter((item) => item.text);

        const translatedSignals = signalItems.length > 0 ? await translateToChinese(signalItems) : {};
        const signals = signalItems
          .map((item) => translatedSignals[item.id] || item.text)
          .join("；");

        const latestMemory = recentMemories[0]?.created_at
          ? `最近一次记忆写入在 ${fmtTime(recentMemories[0].created_at)}`
          : "暂无最近写入时间";

        if (cancelled) return;

        setAnalysisSummary(
          `该用户当前共有 ${sortedMemories.length} 条活跃记忆，主要集中在 ${topTypes || "未分类信息"}。${latestMemory}。${
            signals ? `关键信号：${signals}。` : ""
          }运营沟通时建议优先承接这些已记录的信息，避免重复追问已知内容，并围绕用户已表达的兴趣、情绪和目标做更自然的回应。`,
        );
      } catch (err) {
        if (!cancelled) {
          setAnalysisSummary(
            `已读取 ${sortedMemories.length} 条记忆，但生成中文分析总结失败：${
              err instanceof Error ? err.message : String(err)
            }`,
          );
        }
      } finally {
        if (!cancelled) setAnalysisLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sortedMemories, userData?.recent_messages, userId]);

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  const profile = userData?.profile || null;
  const preferences = profile?.preferences || {};
  const displayCountry = displayProfileValue(
    profile?.country_code || preferences.country_code || preferences.country || preferences.geo_country || preferences.ip_country,
  );
  const displayCity = displayProfileValue(
    profile?.city ||
      preferences.current_city ||
      preferences.city ||
      preferences.user_city ||
      preferences.location ||
      preferences.work_city ||
      preferences.living_city,
  );
  const displayAge = displayProfileValue(profile?.age || preferences.age || preferences.user_age);
  const displayVip = displayProfileValue(profile?.vip_level, "—");
  const displayRelationshipStage = displayProfileValue(profile?.relationship_stage, "—");

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-500">/</span>
          <a href="/admin" className="text-slate-300 hover:text-white">
            会话
          </a>
          <span className="text-violet-300 font-medium">记忆</span>
          <a href="/admin/scripts" className="text-slate-300 hover:text-white">
            话术库
          </a>
          <a href="/admin/characters" className="text-slate-300 hover:text-white">
            角色
          </a>
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-300">
          <span>{operator.username}</span>
          <button onClick={handleLogout} className="text-slate-400 hover:text-white">
            退出
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold mb-1">用户记忆</h1>
          <p className="text-slate-400 text-sm">
            按 user_id 或 external_id 查询长期记忆，支持语义召回测试与停用。
          </p>
        </div>

        <section className="rounded-2xl border border-slate-700 bg-slate-800/60 p-5">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void handleLookup();
            }}
          >
            <label className="flex-1 min-w-[280px]">
              <span className="block text-sm font-medium text-slate-200 mb-1">用户 ID / external_id</span>
              <input
                value={lookupInput}
                onChange={(event) => setLookupInput(event.target.value)}
                placeholder="例如 2f7581b6-... 或 tg_6799525866"
                className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
              />
            </label>
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
            >
              {loading ? "加载中…" : "查询记忆"}
            </button>
          </form>
          {userId && (
            <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-400">
              <span>
                当前用户：<span className="text-slate-200">{userLabel || userId}</span>
              </span>
              <a href={`/admin/users/${userId}`} className="text-sky-300 hover:text-sky-200">
                查看画像
              </a>
            </div>
          )}
        </section>

        {error && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/60 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        {userId && (
          <section className="rounded-2xl border border-slate-700 bg-slate-800/60 p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h2 className="text-lg font-semibold">用户基础信息</h2>
              <span className="text-xs text-slate-500">即使暂无记忆，也会显示用户记录</span>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">用户</div>
                <div className="mt-1 text-slate-100">{userData?.user?.nickname || "—"}</div>
                <div className="text-xs text-slate-500">{userData?.user?.external_id || userId}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">国家 / 城市 / 年龄</div>
                <div className="mt-1 text-slate-100">
                  {displayCountry} / {displayCity} / {displayAge}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">语言 / 状态 / 风险</div>
                <div className="mt-1 text-slate-100">
                  {userData?.user?.language || "—"} / {userData?.user?.status || "—"} / {userData?.user?.risk_level || "—"}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">孤独值</div>
                <div className="mt-1 text-slate-100">{userData?.profile?.loneliness_score ?? "—"}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">VIP / 关系阶段</div>
                <div className="mt-1 text-slate-100">
                  {displayVip} / {displayRelationshipStage}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3">
                <div className="text-xs text-slate-500">创建 / 更新</div>
                <div className="mt-1 text-slate-100 text-sm">
                  {fmtTime(userData?.user?.created_at)} / {fmtTime(userData?.user?.updated_at)}
                </div>
              </div>
            </div>
          </section>
        )}

        {userId && (
          <section className="rounded-2xl border border-slate-700 bg-slate-800/60 p-5">
            <h2 className="text-lg font-semibold mb-3">语义召回测试</h2>
            <form className="flex flex-wrap gap-3" onSubmit={handleRetrieve}>
              <input
                value={retrieveQuery}
                onChange={(event) => setRetrieveQuery(event.target.value)}
                placeholder="输入一句查询，测试会召回哪些记忆"
                className="flex-1 min-w-[280px] rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
              />
              <button
                type="submit"
                disabled={retrieveLoading || !retrieveQuery.trim()}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-50"
              >
                {retrieveLoading ? "召回中…" : "测试召回"}
              </button>
            </form>
            {retrieveMeta && <p className="mt-3 text-xs text-slate-500">{retrieveMeta}</p>}
            {retrieveHits.length > 0 && (
              <div className="mt-4 space-y-2">
                {retrieveHits.map((hit) => (
                  <div key={hit.id} className="rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm">
                    <div className="mb-1 flex flex-wrap gap-2 text-xs text-slate-500">
                      <span>{memoryTypeLabel(hit.memory_type)}</span>
                      <span>相关度 {hit.final_score.toFixed(3)}</span>
                      <span>相似度 {hit.similarity.toFixed(3)}</span>
                    </div>
                    <div className="text-slate-200 break-words">{hit.content}</div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {userId && (
          <section className="rounded-2xl border border-slate-700 bg-slate-800/60 p-5">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-lg font-semibold">用户分析总结</h2>
              <span className="text-xs text-slate-500">
                基于当前活跃记忆；无记忆时参考最近聊天
              </span>
            </div>
            <p className="rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm leading-7 text-slate-200">
              {analysisLoading ? "正在生成中文分析总结…" : analysisSummary}
            </p>
          </section>
        )}

        {userId && (
          <section className="rounded-2xl border border-slate-700 bg-slate-800/60 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
              <h2 className="text-lg font-semibold">最近聊天信息</h2>
              <span className="text-sm text-slate-500">
                {userData?.recent_messages?.length ? `${userData.recent_messages.length} 条` : "暂无"}
              </span>
            </div>
            <div className="divide-y divide-slate-800">
              {userData?.recent_messages?.length ? (
                userData.recent_messages.slice(0, 12).map((message) => (
                  <div key={message.id} className="grid gap-2 px-6 py-3 text-sm md:grid-cols-[120px_180px_1fr]">
                    <div className="text-slate-500">{fmtTime(message.created_at)}</div>
                    <div className="text-slate-400">{message.sender_type || "unknown"}</div>
                    <div className="break-words text-slate-200">{message.content || "—"}</div>
                  </div>
                ))
              ) : (
                <div className="px-6 py-8 text-center text-sm text-slate-500">
                  该用户暂无可参考的近期聊天信息
                </div>
              )}
            </div>
          </section>
        )}

        <section className="rounded-2xl border border-slate-700 bg-slate-800/60 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-lg font-semibold">记忆列表</h2>
            <span className="text-sm text-slate-500">
              {loading ? "加载中…" : userId ? `${sortedMemories.length} 条` : "请先查询用户"}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">时间</th>
                  <th className="text-left px-4 py-3 font-medium">类型</th>
                  <th className="text-left px-4 py-3 font-medium">内容</th>
                  <th className="text-left px-4 py-3 font-medium">重要度</th>
                  <th className="text-right px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {!loading && userId && sortedMemories.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                      该用户暂无活跃记忆
                    </td>
                  </tr>
                )}
                {!userId && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                      输入 user_id 或 tg external_id 后查询
                    </td>
                  </tr>
                )}
                {sortedMemories.map((memory) => (
                  <tr key={memory.id} className="border-t border-slate-800 align-top">
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap">{fmtTime(memory.created_at)}</td>
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                      <div>{memoryTypeLabel(memory.memory_type)}</div>
                      {memoryScopeLabel(memory.memory_scope) && (
                        <div className="text-xs text-slate-500">{memoryScopeLabel(memory.memory_scope)}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-200 break-words max-w-xl">{memory.content || "—"}</td>
                    <td className="px-4 py-3 text-slate-400 tabular-nums">
                      {memory.importance_score != null ? memory.importance_score.toFixed(1) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => void handleDelete(memory.id)}
                        className="text-rose-300 hover:text-rose-200"
                      >
                        停用
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

export default function MemoriesPage() {
  return (
    <AuthGate>
      {(operator) => (
        <Suspense
          fallback={
            <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center">
              加载中…
            </div>
          }
        >
          <MemoriesContent operator={operator} />
        </Suspense>
      )}
    </AuthGate>
  );
}
