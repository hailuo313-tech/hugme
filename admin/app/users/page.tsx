"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";
import { formatBeijingDateTime } from "@/lib/reportTime";

const INITIAL_BATCH_SIZE = 10;
const LOAD_MORE_BATCH_SIZE = 20;
const T1_COUNTRY_OPTIONS = [
  ["US", "美国"],
  ["CA", "加拿大"],
  ["GB", "英国"],
  ["DE", "德国"],
  ["FR", "法国"],
  ["IT", "意大利"],
  ["ES", "西班牙"],
  ["NL", "荷兰"],
  ["BE", "比利时"],
  ["CH", "瑞士"],
  ["AT", "奥地利"],
  ["IE", "爱尔兰"],
  ["DK", "丹麦"],
  ["NO", "挪威"],
  ["SE", "瑞典"],
  ["FI", "芬兰"],
  ["IS", "冰岛"],
  ["LU", "卢森堡"],
  ["PT", "葡萄牙"],
  ["GR", "希腊"],
  ["CZ", "捷克"],
  ["JP", "日本"],
  ["AU", "澳大利亚"],
  ["NZ", "新西兰"],
  ["SG", "新加坡"],
  ["HK", "中国香港"],
] as const;

interface UserListRow {
  user_id: string;
  nickname: string | null;
  external_id: string | null;
  channel: string | null;
  language: string | null;
  user_status: string | null;
  risk_level: string | null;
  is_minor_suspected: boolean | null;
  first_seen_at: string | null;
  user_level: string | null;
  chat_route: string | null;
  country_code: string | null;
  city: string | null;
  age: string | null;
  relationship_stage: string | null;
  vip_level: number | null;
  loneliness_score: number | null;
  conversation_id: string | null;
  conversation_state: string | null;
  last_message_at: string | null;
  telegram_account_label: string | null;
  telegram_account_phone: string | null;
  telegram_account_username: string | null;
  user_messages: number;
  ai_messages: number;
  operator_messages: number;
  last_user_message: string | null;
  last_system_message: string | null;
  link_exposures: number;
  link_clicks: number;
  first_link_sent_at: string | null;
  first_link_click_at: string | null;
  last_link_click_at: string | null;
  video_calls: number;
  video_completed: number;
  video_failed: number;
  auto_answered_calls: number;
  latest_video_status: string | null;
  latest_video_at: string | null;
  nurture_tasks: number;
  nurture_running: number;
  nurture_completed: number;
  latest_nurture_at: string | null;
  is_t1_country: boolean;
}

interface UserListResponse {
  items: UserListRow[];
  total: number;
  page: number;
  page_size: number;
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "-";
  return formatBeijingDateTime(value);
}

function shortText(value: string | null | undefined, max = 48): string {
  if (!value) return "-";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function badgeClass(kind: "level" | "status" | "risk", value: string | null | undefined): string {
  if (kind === "level") {
    if (value === "S") return "border-rose-500/60 bg-rose-950/40 text-rose-200";
    if (value === "A") return "border-amber-500/60 bg-amber-950/40 text-amber-200";
    if (value === "B") return "border-sky-500/60 bg-sky-950/40 text-sky-200";
    return "border-slate-700 bg-slate-900 text-slate-300";
  }
  if (kind === "risk") {
    if (value === "high" || value === "critical") return "border-rose-500/60 bg-rose-950/40 text-rose-200";
    if (value === "elevated") return "border-amber-500/60 bg-amber-950/40 text-amber-200";
    return "border-emerald-700 bg-emerald-950/30 text-emerald-300";
  }
  if (value === "frozen" || value === "suspended") return "border-amber-500/60 bg-amber-950/40 text-amber-200";
  return "border-slate-700 bg-slate-900 text-slate-300";
}

function routeLabel(value: string | null | undefined): string {
  if (value === "manual_premium") return "人工优先";
  if (value === "ai_assisted") return "AI辅助";
  if (value === "ai_auto") return "AI自动";
  return value || "-";
}

function stateLabel(value: string | null | undefined): string {
  if (value === "HUMAN_LOCKED") return "人工中";
  if (value === "WAITING_OPERATOR") return "待人工";
  if (value === "AI_ACTIVE") return "AI自动";
  if (value === "CLOSED") return "已关闭";
  return value || "-";
}

function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
      <div className="flex items-center justify-between gap-4 border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function UsersContent({ operator }: { operator: Operator }) {
  const [items, setItems] = useState<UserListRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [country, setCountry] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hasMore = useMemo(() => items.length < total, [items.length, total]);

  const load = useCallback(async (offset = 0, append = false) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    try {
      const batchSize = append ? LOAD_MORE_BATCH_SIZE : INITIAL_BATCH_SIZE;
      const qs = new URLSearchParams({
        page: "1",
        page_size: String(batchSize),
        offset: String(offset),
      });
      if (channel) qs.set("channel", channel);
      if (status) qs.set("status", status);
      if (country) qs.set("country", country);
      if (appliedSearch.trim()) qs.set("search", appliedSearch.trim());
      const response = await apiFetch<UserListResponse>(`/admin/users?${qs.toString()}`, { retries: 1 });
      setItems((current) => append ? [...current, ...(response.items || [])] : (response.items || []));
      setTotal(response.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      if (!append) {
        setItems([]);
        setTotal(0);
      }
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, [appliedSearch, channel, country, status]);

  useEffect(() => {
    void load(0, false);
  }, [load]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAppliedSearch(search);
  }

  function resetFilters() {
    setSearch("");
    setAppliedSearch("");
    setChannel("");
    setStatus("");
    setCountry("");
  }

  return (
    <AdminFrame
      operator={operator}
      active="users"
      title="用户列表"
      subtitle="按最近活跃查看用户画像、链接点击、视频、培育和运营状态。列表只放核心字段，详情进入用户画像页继续处理。"
    >
      <Panel
        title="用户筛选"
        action={<span className="text-sm text-slate-500">共 {total} 个用户</span>}
      >
        <form onSubmit={submitSearch} className="grid gap-3 p-5 lg:grid-cols-[180px_160px_220px_1fr_auto_auto]">
          <select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            <option value="">全部渠道</option>
            <option value="telegram_real_user">真人 TG</option>
            <option value="telegram">Telegram</option>
            <option value="web">Web</option>
          </select>
          <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            <option value="">全部状态</option>
            <option value="active">active</option>
            <option value="frozen">frozen</option>
            <option value="suspended">suspended</option>
          </select>
          <select value={country} onChange={(event) => setCountry(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            <option value="">全部国家</option>
            <option value="T2">T2</option>
            <option value="T3">T3</option>
            {T1_COUNTRY_OPTIONS.map(([code, name]) => (
              <option key={code} value={code}>{name} {code}</option>
            ))}
          </select>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索昵称 / external_id / TG 用户名 / 最近消息"
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
          />
          <button type="submit" className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500">搜索</button>
          <button type="button" onClick={resetFilters} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">重置</button>
        </form>
      </Panel>

      <div className="mt-6">
        <Panel
          title="用户明细"
          action={<span className="text-xs text-slate-500">已加载 {items.length} / {total} 条</span>}
        >
          {error && <div className="m-5 rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1480px] text-sm">
              <thead className="bg-slate-950 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">用户</th>
                  <th className="px-4 py-3 text-left font-medium">国家 / 城市 / 年龄</th>
                  <th className="px-4 py-3 text-left font-medium">等级 / 状态</th>
                  <th className="px-4 py-3 text-left font-medium">接待 TG</th>
                  <th className="px-4 py-3 text-left font-medium">消息</th>
                  <th className="px-4 py-3 text-left font-medium">链接</th>
                  <th className="px-4 py-3 text-left font-medium">视频</th>
                  <th className="px-4 py-3 text-left font-medium">培育</th>
                  <th className="px-4 py-3 text-left font-medium">最近消息</th>
                  <th className="px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900/35">
                {loading && <tr><td colSpan={10} className="px-4 py-10 text-center text-slate-500">加载中...</td></tr>}
                {!loading && items.length === 0 && <tr><td colSpan={10} className="px-4 py-10 text-center text-slate-500">暂无用户</td></tr>}
                {!loading && items.map((row) => (
                  <tr key={row.user_id} className="transition hover:bg-slate-800/70">
                    <td className="px-4 py-4 align-top">
                      <a
                        href={`/admin/users/${row.user_id}#chat-history`}
                        className="font-medium text-sky-300 underline decoration-sky-700/70 underline-offset-4 hover:text-sky-200"
                        title="查看该用户的全部聊天记录"
                      >
                        {shortText(row.nickname || row.external_id, 34)}
                      </a>
                      <div className="mt-1 font-mono text-xs text-slate-500">{row.external_id || row.user_id}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.channel || "-"} / {row.language || "en"}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-100">{row.country_code || "-"}</span>
                        {row.is_t1_country ? <span className="rounded-full bg-emerald-950 px-2 py-0.5 text-xs text-emerald-300">T1</span> : null}
                      </div>
                      <div className="mt-1 text-slate-400">{row.city || "-"} / {row.age || "-"}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="flex flex-wrap gap-2">
                        <span className={`rounded-full border px-2 py-0.5 text-xs ${badgeClass("level", row.user_level)}`}>{row.user_level || "C"}</span>
                        <span className={`rounded-full border px-2 py-0.5 text-xs ${badgeClass("status", row.user_status)}`}>{row.user_status || "-"}</span>
                        <span className={`rounded-full border px-2 py-0.5 text-xs ${badgeClass("risk", row.risk_level)}`}>{row.is_minor_suspected ? "疑似未成年" : (row.risk_level || "normal")}</span>
                      </div>
                      <div className="mt-2 text-xs text-slate-500">{routeLabel(row.chat_route)} / {stateLabel(row.conversation_state)}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">{shortText(row.telegram_account_label, 34)}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.telegram_account_phone || row.telegram_account_username || "-"}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">用户 {row.user_messages || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">AI {row.ai_messages || 0} / 人工 {row.operator_messages || 0}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">点击 {row.link_clicks || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">曝光 {row.link_exposures || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">最近 {fmtTime(row.last_link_click_at)}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">通话 {row.video_calls || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">成功 {row.video_completed || 0} / 自动 {row.auto_answered_calls || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.latest_video_status || "-"} {fmtTime(row.latest_video_at)}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">任务 {row.nurture_tasks || 0}</div>
                      <div className="mt-1 text-xs text-slate-500">执行中 {row.nurture_running || 0} / 完成 {row.nurture_completed || 0}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="max-w-[320px] text-slate-200">{shortText(row.last_user_message, 72)}</div>
                      <div className="mt-2 text-xs text-slate-500">最后活跃 {fmtTime(row.last_message_at)}</div>
                    </td>
                    <td className="px-4 py-4 text-right align-top">
                      <div className="flex justify-end gap-2">
                        {row.conversation_id ? (
                          <a href={`/admin/conversations?conversation_id=${row.conversation_id}`} className="rounded-md border border-slate-700 px-3 py-2 text-xs text-sky-300 hover:bg-slate-800">会话</a>
                        ) : null}
                        <a href={`/admin/users/${row.user_id}`} className="rounded-md bg-violet-600 px-3 py-2 text-xs font-medium text-white hover:bg-violet-500">画像</a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-center border-t border-slate-800 px-5 py-4">
            <button
              type="button"
              disabled={!hasMore || loading || loadingMore}
              onClick={() => void load(items.length, true)}
              className="min-w-40 rounded-md border border-slate-700 px-5 py-2 text-sm text-slate-300 disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-800"
            >
              {loadingMore ? "加载中..." : hasMore ? "再加载 20 条" : "已加载全部用户"}
            </button>
          </div>
        </Panel>
      </div>
    </AdminFrame>
  );
}

export default function UsersPage() {
  return <AuthGate>{(operator) => <UsersContent operator={operator} />}</AuthGate>;
}
