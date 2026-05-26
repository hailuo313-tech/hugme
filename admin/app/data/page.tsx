"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
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
  assistant_messages: number;
  last_message_at?: string | null;
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
}

const QUICK_RANGES = [
  { label: "今日", days: 1 },
  { label: "本周", days: 7 },
  { label: "14 天", days: 14 },
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

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    const query = selectedDate
      ? `/admin/attribution/summary?date=${selectedDate}`
      : `/admin/attribution/summary?days=${days}`;

    apiFetch<AttributionSummary>(query)
      .then((data) => {
        if (!mounted) return;
        setSummary(data);
        setError(null);
      })
      .catch((err: Error) => {
        if (!mounted) return;
        setError(err.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [days, selectedDate]);

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

  const rangeLabel = selectedDate ? `${selectedDate} 当天` : QUICK_RANGES.find((item) => item.days === days)?.label || `最近 ${days} 天`;

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
              key={item.days}
              onClick={() => {
                setDays(item.days);
                setSelectedDate("");
              }}
              className={`rounded px-3 py-1.5 text-sm transition ${
                !selectedDate && days === item.days
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
                <div className="font-mono text-xs text-sky-300">{row.script_key}</div>
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

function TelegramAccountPanel({ rows }: { rows: TelegramAccountRow[] }) {
  return (
    <section className="mb-6 overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">TG 账号接待表现</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-950/50 text-slate-500">
            <tr>
              <th className="px-5 py-3 font-medium">TG 账号</th>
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
                  <td className="px-5 py-4 text-slate-100">{row.new_users}</td>
                  <td className="px-5 py-4 text-slate-100">{row.served_users}</td>
                  <td className="px-5 py-4 text-slate-300">{row.assistant_messages}</td>
                  <td className="px-5 py-4 text-slate-400">{formatDate(row.last_message_at)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-5 py-8 text-sm text-slate-500" colSpan={5}>
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
