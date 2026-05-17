"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型 ──────────────────────────────────────────────────────────

interface MemoryRow {
  id: string;
  memory_type: string | null;
  importance_score: number | null;
  content: string | null;
  created_at: string | null;
  memory_scope: string | null;
  character_id: string | null;
  is_active: boolean | null;
}

// ── 工具函数 ──────────────────────────────────────────────────────

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function truncate(s: string | null, maxLen = 80): string {
  if (!s) return "—";
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
}

function scoreColor(score: number | null): string {
  if (score === null) return "text-slate-500";
  if (score >= 8) return "text-rose-400";
  if (score >= 5) return "text-amber-400";
  return "text-slate-400";
}

function typeColor(t: string | null): string {
  switch (t) {
    case "emotion":
      return "bg-violet-900/40 text-violet-300 border-violet-800";
    case "preference":
      return "bg-sky-900/40 text-sky-300 border-sky-800";
    case "event":
      return "bg-emerald-900/40 text-emerald-300 border-emerald-800";
    case "identity":
      return "bg-amber-900/40 text-amber-300 border-amber-800";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

// ── Nav header（无 searchParams 依赖，可复用） ─────────────────────

function NavHeader({
  operator,
  onLogout,
}: {
  operator: Operator;
  onLogout: () => void;
}) {
  return (
    <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xl font-bold text-violet-400">ERIS</span>
        <span className="text-slate-400 text-sm">运营后台</span>
        <nav className="flex items-center gap-1 ml-4">
          <a
            href="/admin"
            className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
          >
            会话
          </a>
          <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
            记忆
          </span>
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
          onClick={onLogout}
          className="text-sm text-slate-400 hover:text-white transition"
        >
          退出
        </button>
      </div>
    </header>
  );
}

// ── 主内容（使用 useSearchParams，需包在 Suspense 内） ────────────

function MemoriesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialUid = searchParams.get("user_id") ?? "";
  const [userId, setUserId] = useState(initialUid);
  const [draftUid, setDraftUid] = useState(initialUid);
  const inputRef = useRef<HTMLInputElement>(null);

  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async (uid: string) => {
    if (!uid.trim()) {
      setMemories([]);
      return;
    }
    setLoading(true);
    setError(null);
    setExpanded(new Set());
    try {
      const data = await apiFetch<MemoryRow[]>(
        `/users/${encodeURIComponent(uid.trim())}/memories`
      );
      setMemories(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setMemories([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(userId);
  }, [userId, load]);

  function handleUidSubmit(e: React.FormEvent) {
    e.preventDefault();
    const uid = draftUid.trim();
    const params = new URLSearchParams(searchParams.toString());
    if (uid) {
      params.set("user_id", uid);
    } else {
      params.delete("user_id");
    }
    router.replace(`/memories?${params.toString()}`); // basePath 下 Next Router 自动加 /admin 前缀
    setUserId(uid);
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <main className="p-8 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold mb-1">用户记忆</h1>
        <p className="text-slate-400 text-sm">
          查看用户的长期记忆列表（按 importance_score 降序）
        </p>
      </div>

      {/* 用户搜索框 */}
      <form
        onSubmit={handleUidSubmit}
        className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex flex-wrap items-center gap-3"
      >
        <label className="text-sm text-slate-400 whitespace-nowrap">
          user_id
        </label>
        <input
          ref={inputRef}
          type="text"
          value={draftUid}
          onChange={(e) => setDraftUid(e.target.value)}
          placeholder="输入 user_id 后按 Enter 查询"
          className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 flex-1 min-w-[260px] font-mono"
        />
        <button
          type="submit"
          className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
        >
          查询
        </button>
        {userId && (
          <button
            type="button"
            onClick={() => {
              setDraftUid("");
              setUserId("");
              setMemories([]);
              setError(null);
              router.replace("/memories"); // basePath 下 Next Router 自动加 /admin 前缀
              setTimeout(() => inputRef.current?.focus(), 50);
            }}
            className="text-slate-400 hover:text-white text-sm transition"
          >
            清除
          </button>
        )}
      </form>

      {/* 摘要行 */}
      {userId && !loading && !error && (
        <div className="text-xs text-slate-500 mb-3 font-mono">
          user_id: <span className="text-slate-300">{userId}</span>
          {" · "}共{" "}
          <span className="text-slate-300">{memories.length}</span> 条记忆
        </div>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
          加载失败：{error}
        </div>
      )}

      {/* 空态：未输入 user_id */}
      {!userId && !loading && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 border-dashed p-12 text-center">
          <p className="text-slate-500 text-sm mb-2">
            请在上方输入 user_id 并按 Enter 查询
          </p>
          <p className="text-slate-600 text-xs">
            也可以通过 URL 参数直接访问，例如{" "}
            <code className="bg-slate-700 px-1.5 py-0.5 rounded text-slate-400">
              /memories?user_id=xxx
            </code>
          </p>
        </div>
      )}

      {/* 表格 */}
      {(userId || loading) && !error && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3 font-medium whitespace-nowrap">
                  创建时间
                </th>
                <th className="text-left px-4 py-3 font-medium">类型</th>
                <th className="text-right px-4 py-3 font-medium w-20">
                  重要性
                </th>
                <th className="text-left px-4 py-3 font-medium">内容</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60">
              {loading && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-8 text-center text-slate-500"
                  >
                    加载中…
                  </td>
                </tr>
              )}
              {!loading && memories.length === 0 && userId && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-12 text-center text-slate-500"
                  >
                    该用户暂无记忆记录
                  </td>
                </tr>
              )}
              {!loading &&
                memories.map((row) => {
                  const isExpanded = expanded.has(row.id);
                  const hasLongContent =
                    row.content !== null && row.content.length > 80;
                  return (
                    <tr
                      key={row.id}
                      className="hover:bg-slate-700/30 transition align-top"
                    >
                      {/* 创建时间 */}
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                        {fmtTime(row.created_at)}
                      </td>

                      {/* 类型 */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className={`inline-block px-2 py-0.5 text-xs rounded-full border ${typeColor(
                            row.memory_type
                          )}`}
                        >
                          {row.memory_type || "—"}
                        </span>
                      </td>

                      {/* 重要性 */}
                      <td
                        className={`px-4 py-3 text-right tabular-nums font-mono text-sm ${scoreColor(
                          row.importance_score
                        )}`}
                      >
                        {row.importance_score != null
                          ? row.importance_score.toFixed(1)
                          : "—"}
                      </td>

                      {/* 内容（可展开） */}
                      <td className="px-4 py-3 text-slate-200 leading-relaxed max-w-[600px]">
                        <span className="break-words">
                          {isExpanded
                            ? (row.content ?? "—")
                            : truncate(row.content)}
                        </span>
                        {hasLongContent && (
                          <button
                            onClick={() => toggleExpand(row.id)}
                            className="ml-2 text-xs text-violet-400 hover:text-violet-300 whitespace-nowrap"
                          >
                            {isExpanded ? "收起" : "展开"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

// ── 页面入口（AuthGate 统一守卫 + Suspense 包裹 searchParams 消费者） ─

export default function MemoriesPage() {
  return (
    <AuthGate>
      {(operator) => (
        <div className="min-h-screen bg-slate-900 text-white">
          <NavHeader
            operator={operator}
            onLogout={() => {
              clearAuth();
              window.location.href = LOGIN_PATH;
            }}
          />
          <Suspense
            fallback={
              <main className="p-8 text-slate-500 text-sm">加载中…</main>
            }
          >
            <MemoriesContent />
          </Suspense>
        </div>
      )}
    </AuthGate>
  );
}
