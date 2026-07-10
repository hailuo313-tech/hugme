"use client";

import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

/*
运营校验词：TG 新用户数、TG 接待用户数、发送链接用户、点击链接用户、访问下载页、完成下载、
链接点击率、点击到下载页、点击到下载、平均点击耗时、核心下载漏斗、下载话术效果、接待用户。
*/

interface Overview {
  sent_links: number;
  sent_users: number;
  exposed_users: number;
  click_events: number;
  click_users: number;
  today_click_users: number;
  download_page_users: number;
  download_users: number;
  click_rate: number;
  click_to_download_page_rate: number;
  click_to_download_rate: number;
  avg_sent_to_click_seconds: number;
  tg_new_users: number;
  tg_served_users: number;
}

interface DimensionRow {
  key: string;
  country_code?: string;
  is_t1_country?: boolean;
  exposures: number;
  clicks: number;
  click_users: number;
  downloads: number;
}

interface ScriptRow {
  script_key: string;
  intent?: string | null;
  persona?: string | null;
  scene_step?: string | null;
  sender_account_id?: string | null;
  content?: string | null;
  operator_translation_zh?: string | null;
  clicks: number;
  downloads: number;
}

interface TelegramAccountRow {
  account_id: string;
  account_label: string;
  phone?: string | null;
  username?: string | null;
  served_users: number;
  new_users: number;
  new_users_last_30m: number;
  assistant_messages: number;
  last_message_at?: string | null;
}

interface ClickedUserRow {
  user_id: string;
  external_id?: string | null;
  nickname?: string | null;
  channel?: string | null;
  country_code?: string | null;
  user_level?: string | null;
  click_count: number;
  clicked_links: number;
  first_click_at?: string | null;
  last_click_at?: string | null;
  latest_tracking_id?: string | null;
  latest_destination_url?: string | null;
  latest_script_category?: string | null;
  latest_sender_account_id?: string | null;
}

interface AttributionSummary {
  days: number;
  date?: string | null;
  mode?: "range" | "daily";
  overview: Overview;
  funnel: Array<{ step: string; users: number; events: number }>;
  countries: DimensionRow[];
  age_bands: DimensionRow[];
  levels: DimensionRow[];
  sender_accounts: DimensionRow[];
  script_categories: DimensionRow[];
  top_click_scripts: ScriptRow[];
  top_download_scripts: ScriptRow[];
  telegram_accounts: TelegramAccountRow[];
  clicked_users: ClickedUserRow[];
}

const QUICK_RANGES = [
  { label: "今日", days: 1 },
  { label: "昨天", days: 1, dateOffsetDays: -1 },
  { label: "本周", days: 7 },
  { label: "30 天", days: 30 },
];

const FUNNEL_LABELS = ["话术发送", "链接曝光", "链接点击", "下载页访问", "App 下载"];

const formatRate = (value: number) => `${((value || 0) * 100).toFixed(1)}%`;

function formatDuration(seconds: number) {
  if (!seconds) return "-";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} 小时`;
  return `${(seconds / 86400).toFixed(1)} 天`;
}

export default function DataPage() {
  return (
    <AuthGate>
      {(operator) => <DataDashboard operator={operator} />}
    </AuthGate>
  );
}

function DataDashboard({ operator }: { operator: Operator }) {
  const [days, setDays] = useState(7);
  const [selectedDate, setSelectedDate] = useState("");
  const [summary, setSummary] = useState<AttributionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);

  const loadSummary = useCallback(
    async (mounted = true) => {
      setLoading(true);
      const query = selectedDate
        ? `/admin/attribution/summary?date=${selectedDate}`
        : `/admin/attribution/summary?days=${days}`;

      try {
        const data = await apiFetch<AttributionSummary>(query);
        if (!mounted) return;
        setSummary(data);
        setError(null);
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (mounted) setLoading(false);
      }
    },
    [days, selectedDate]
  );

  useEffect(() => {
    let mounted = true;
    void loadSummary(mounted);

    return () => {
      mounted = false;
    };
  }, [loadSummary]);

  async function deleteClickedUser(row: ClickedUserRow) {
    const label = row.nickname || row.external_id || row.user_id;
    if (!window.confirm(`确认删除 ${label} 的点击链接记录吗？只删除点击归因记录，不删除 TG 用户和聊天记录。`)) return;
    setDeletingUserId(row.user_id);
    setLoading(true);
    try {
      await apiFetch(`/admin/attribution/clicked-users/${encodeURIComponent(row.user_id)}`, { method: "DELETE" });
      await loadSummary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingUserId(null);
      setLoading(false);
    }
  }

  const overview = summary?.overview;
  const funnel = useMemo(() => {
    const source = summary?.funnel ?? [];
    return FUNNEL_LABELS.map((label, index) => {
      const row = source[index];
      return {
        label,
        users: row?.users ?? 0,
        events: row?.events ?? 0,
      };
    });
  }, [summary]);

  const yesterdayDate = formatDateOffset(-1);
  const activeQuickLabel = selectedDate === yesterdayDate ? "昨天" : QUICK_RANGES.find((item) => !item.dateOffsetDays && item.days === days)?.label;
  const rangeLabel = selectedDate ? `${selectedDate} 当天` : activeQuickLabel || `最近 ${days} 天`;

  return (
    <AdminFrame
      operator={operator}
      active="data"
      title="下载转化总览"
      subtitle="只看从 TG 新用户接待，到发送下载链接、点击链接、完成 App 下载这一段核心业务数据。"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-md border border-slate-800 bg-slate-900 p-1">
          {QUICK_RANGES.map((item) => (
            <button
              key={item.label}
              onClick={() => {
                setDays(item.days);
                setSelectedDate(item.dateOffsetDays ? formatDateOffset(item.dateOffsetDays) : "");
              }}
              className={`rounded px-3 py-1.5 text-sm transition ${
                (item.dateOffsetDays ? selectedDate === formatDateOffset(item.dateOffsetDays) : !selectedDate && days === item.days)
                  ? "bg-violet-600 text-white"
                  : "text-slate-400 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-2">
          <span className="text-sm text-slate-500">按日期</span>
          <input
            type="date"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200 outline-none focus:border-violet-500"
          />
          {selectedDate && (
            <button onClick={() => setSelectedDate("")} className="rounded px-2 py-1 text-sm text-slate-400 hover:bg-slate-800 hover:text-white">
              清除
            </button>
          )}
        </div>
        <span className="text-sm text-slate-500">{loading ? "加载中..." : rangeLabel}</span>
      </div>

      {error && (
        <div className="mb-5 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          数据加载失败：{error}
        </div>
      )}

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="TG 新用户" value={overview?.tg_new_users ?? 0} />
        <MetricCard label="TG 接待用户" value={overview?.tg_served_users ?? 0} />
        <MetricCard label="发送链接用户" value={overview?.sent_users ?? 0} />
        <MetricCard label="点击链接用户" value={overview?.click_users ?? 0} />
        <MetricCard label="访问下载页" value={overview?.download_page_users ?? 0} />
        <MetricCard label="完成下载" value={overview?.download_users ?? 0} />
      </section>

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard label="链接点击率" value={formatRate(overview?.click_rate ?? 0)} />
        <MetricCard label="点击到下载页" value={formatRate(overview?.click_to_download_page_rate ?? 0)} />
        <MetricCard label="点击到下载" value={formatRate(overview?.click_to_download_rate ?? 0)} />
        <MetricCard label="平均点击耗时" value={formatDuration(overview?.avg_sent_to_click_seconds ?? 0)} />
      </section>

      <section className="mb-6 rounded-md border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-5 py-4">
          <h2 className="text-lg font-semibold">核心下载漏斗</h2>
        </div>
        <div className="grid grid-cols-1 divide-y divide-slate-800 md:grid-cols-5 md:divide-x md:divide-y-0">
          {funnel.map((step) => (
            <div key={step.label} className="px-5 py-5">
              <div className="text-sm text-slate-500">{step.label}</div>
              <div className="mt-2 text-2xl font-semibold text-white">{step.users}</div>
              <div className="mt-2 text-xs text-slate-500">事件 {step.events}</div>
            </div>
          ))}
        </div>
      </section>

      <TelegramAccountPanel rows={summary?.telegram_accounts ?? []} />

      <section className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ScriptPanel title="点击效果最好的话术" rows={summary?.top_click_scripts ?? []} metric="clicks" />
        <ScriptPanel title="下载效果最好的话术" rows={summary?.top_download_scripts ?? []} metric="downloads" />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <DimensionPanel title="国家 / T1 效果" rows={summary?.countries ?? []} label="国家" />
        <DimensionPanel title="年龄段效果" rows={summary?.age_bands ?? []} label="年龄段" />
        <DimensionPanel title="用户等级效果" rows={summary?.levels ?? []} label="等级" />
        <DimensionPanel title="话术分类效果" rows={summary?.script_categories ?? []} label="分类" />
      </section>

      <ClickedUsersPanel rows={summary?.clicked_users ?? []} deletingUserId={deletingUserId} onDelete={deleteClickedUser} />
    </AdminFrame>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function ScriptPanel({ title, rows, metric }: { title: string; rows: ScriptRow[]; metric: keyof Pick<ScriptRow, "clicks" | "downloads"> }) {
  return (
    <Panel title={title} empty="暂无话术数据" hasRows={rows.length > 0}>
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-950/50 text-slate-500">
          <tr>
            <th className="px-5 py-3 font-medium">话术</th>
            <th className="px-5 py-3 font-medium">场景</th>
            <th className="px-5 py-3 font-medium">{metric === "clicks" ? "点击" : "下载"}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={`${title}-${row.script_key}`}>
              <td className="px-5 py-4 text-slate-300">
                <div className="group relative inline-block max-w-full">
                  <div className="cursor-help truncate font-mono text-xs text-sky-300">{row.script_key}</div>
                  <div className="pointer-events-none absolute left-0 top-6 z-20 hidden w-[360px] max-w-[80vw] rounded-md border border-slate-700 bg-slate-950 p-3 text-sm leading-6 text-slate-200 shadow-xl group-hover:block">
                    <div className="mb-1 text-xs text-slate-500">中文参考</div>
                    <div className="whitespace-pre-wrap">{scriptChineseText(row)}</div>
                  </div>
                </div>
                <div className="mt-1 text-xs text-slate-500">{row.sender_account_id || "未记录账号"}</div>
              </td>
              <td className="px-5 py-4 text-slate-400">
                <div>{row.scene_step || "-"}</div>
                <div className="mt-1 text-xs text-slate-500">{row.intent || row.persona || "-"}</div>
              </td>
              <td className="px-5 py-4 text-slate-100">{String(row[metric] ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function DimensionPanel({ title, rows, label }: { title: string; rows: DimensionRow[]; label: string }) {
  return (
    <Panel title={title} empty="暂无维度数据" hasRows={rows.length > 0}>
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-950/50 text-slate-500">
          <tr>
            <th className="px-5 py-3 font-medium">{label}</th>
            <th className="px-5 py-3 font-medium">曝光</th>
            <th className="px-5 py-3 font-medium">点击</th>
            <th className="px-5 py-3 font-medium">下载</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={`${title}-${row.country_code || row.key}`}>
              <td className="px-5 py-4 text-slate-300">
                {row.country_code || row.key}
                {row.is_t1_country && <span className="ml-2 rounded-full bg-sky-500/10 px-2 py-0.5 text-xs text-sky-300">T1</span>}
              </td>
              <td className="px-5 py-4 text-slate-300">{row.exposures}</td>
              <td className="px-5 py-4 text-slate-300">{row.clicks}</td>
              <td className="px-5 py-4 text-slate-300">{row.downloads}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ClickedUsersPanel({
  rows,
  deletingUserId,
  onDelete,
}: {
  rows: ClickedUserRow[];
  deletingUserId: string | null;
  onDelete: (row: ClickedUserRow) => void;
}) {
  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold">点击链接用户明细</h2>
          <p className="mt-1 text-sm text-slate-500">看清楚哪些 TG 用户点过链接、点了几次、最后点的是哪条链接。</p>
          <p className="mt-1 text-xs text-slate-600">排名规则：最近点击时间越近，越排在最上面。</p>
        </div>
        <span className="shrink-0 text-sm text-slate-500">最多显示 500 个</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-950/50 text-slate-500">
            <tr>
              <th className="px-5 py-3 font-medium">用户</th>
              <th className="px-5 py-3 font-medium">点击次数</th>
              <th className="px-5 py-3 font-medium">国家 / 等级</th>
              <th className="px-5 py-3 font-medium">最近点击</th>
              <th className="px-5 py-3 font-medium">最近链接</th>
              <th className="px-5 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.length ? (
              rows.map((row) => (
                <tr key={row.user_id}>
                  <td className="px-5 py-4 text-slate-300">
                    <div className="font-medium text-slate-100">{row.nickname || row.external_id || row.user_id}</div>
                    <div className="mt-1 font-mono text-xs text-slate-500">{row.external_id || row.user_id}</div>
                    <div className="mt-1 text-xs text-slate-600">{row.channel || "telegram"}</div>
                  </td>
                  <td className="px-5 py-4 text-slate-100">
                    <div className="text-xl font-semibold">{row.click_count}</div>
                    <div className="mt-1 text-xs text-slate-500">链接 {row.clicked_links}</div>
                  </td>
                  <td className="px-5 py-4 text-slate-300">
                    <div>{row.country_code || "-"}</div>
                    <div className="mt-1 text-xs text-slate-500">{row.user_level || "-"}</div>
                  </td>
                  <td className="px-5 py-4 text-slate-400">
                    <div>{formatDate(row.last_click_at)}</div>
                    <div className="mt-1 text-xs text-slate-500">首次 {formatDate(row.first_click_at)}</div>
                  </td>
                  <td className="px-5 py-4 text-slate-300">
                    <div className="max-w-[360px] truncate text-sky-300" title={row.latest_destination_url || ""}>
                      {shortUrl(row.latest_destination_url)}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {row.latest_script_category || "未记录话术分类"} / {row.latest_sender_account_id || "未记录账号"}
                    </div>
                    <div className="mt-1 font-mono text-xs text-slate-600">{row.latest_tracking_id || "-"}</div>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button
                      type="button"
                      onClick={() => onDelete(row)}
                      disabled={deletingUserId === row.user_id}
                      className="rounded border border-rose-500/70 px-3 py-1.5 text-sm text-rose-300 transition hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {deletingUserId === row.user_id ? "删除中" : "删除"}
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-5 py-8 text-sm text-slate-500" colSpan={6}>
                  暂无点击链接用户
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TelegramAccountPanel({ rows }: { rows: TelegramAccountRow[] }) {
  return (
    <section className="mb-6 overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">TG 账号接待表现</h2>
        <p className="mt-1 text-xs text-slate-500">
          按最近滚动 30 分钟由各 TG 账号实际新增的去重用户数从高到低排列，无需已接待。
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-950/50 text-slate-500">
            <tr>
              <th className="px-5 py-3 font-medium">TG 账号</th>
              <th className="px-5 py-3 font-medium">近30分钟实际新增</th>
              <th className="px-5 py-3 font-medium">新用户</th>
              <th className="px-5 py-3 font-medium">接待用户</th>
              <th className="px-5 py-3 font-medium">发送消息</th>
              <th className="px-5 py-3 font-medium">最后接待</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.length ? (
              rows.map((row) => (
                <tr key={row.account_id}>
                  <td className="px-5 py-4 text-slate-300">
                    <div className="font-medium text-slate-100">{row.account_label}</div>
                    <div className="mt-1 text-xs text-slate-500">{row.username || row.phone || row.account_id}</div>
                  </td>
                  <td className="px-5 py-4 font-semibold text-sky-300">{row.new_users_last_30m}</td>
                  <td className="px-5 py-4 text-slate-100">{row.new_users}</td>
                  <td className="px-5 py-4 text-slate-100">{row.served_users}</td>
                  <td className="px-5 py-4 text-slate-300">{row.assistant_messages}</td>
                  <td className="px-5 py-4 text-slate-400">{formatDate(row.last_message_at)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-5 py-8 text-sm text-slate-500" colSpan={6}>
                  暂无 TG 账号接待数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Panel({ title, empty, hasRows, children }: { title: string; empty: string; hasRows: boolean; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        {hasRows ? children : <div className="px-5 py-8 text-sm text-slate-500">{empty}</div>}
      </div>
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 16);
}

function formatDateOffset(offsetDays: number) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function scriptChineseText(row: ScriptRow) {
  const translated = row.operator_translation_zh?.trim();
  if (translated) return translated;
  const original = row.content?.trim();
  if (original) return `暂无中文翻译，原文：\n${original}`;
  return "暂无中文翻译";
}

function shortUrl(value?: string | null) {
  if (!value) return "-";
  try {
    const url = new URL(value);
    return `${url.hostname}${url.pathname}`.slice(0, 80);
  } catch {
    return value.slice(0, 80);
  }
}
