"use client";

import { useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

interface Overview {
  sent_links: number;
  sent_users: number;
  exposed_users: number;
  clicked_links: number;
  click_events: number;
  click_users: number;
  unique_click_users: number;
  today_click_users: number;
  download_page_users: number;
  download_users: number;
  register_users: number;
  paid_users: number;
  upgraded_paid_users: number;
  revenue_cents: number;
  click_rate: number;
  click_to_download_page_rate: number;
  click_to_download_rate: number;
  download_to_register_rate: number;
  click_to_register_rate: number;
  register_to_pay_rate: number;
  click_to_pay_rate: number;
  avg_sent_to_click_seconds: number;
  avg_click_to_register_seconds: number;
  avg_click_to_payment_seconds: number;
}

interface DimensionRow {
  key: string;
  country_code?: string;
  is_t1_country?: boolean;
  exposures: number;
  clicks: number;
  click_users: number;
  downloads: number;
  registrations: number;
  payments: number;
  revenue_cents: number;
}

interface ScriptRow {
  script_key: string;
  script_template_id?: string | null;
  script_hit_id?: string | null;
  intent?: string | null;
  persona?: string | null;
  scene_step?: string | null;
  sender_account_id?: string | null;
  clicks: number;
  downloads: number;
  registrations: number;
  payments: number;
  revenue_cents: number;
}

interface LinkRow {
  tracking_id: string;
  destination_url: string;
  script_key: string;
  sent_at?: string | null;
  sender_account_id?: string | null;
  platform?: string | null;
  clicks: number;
  click_users: number;
  first_click_at?: string | null;
  avg_seconds_to_click: number;
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
  personas: DimensionRow[];
  intents: DimensionRow[];
  platforms: DimensionRow[];
  devices: DimensionRow[];
  sender_accounts: DimensionRow[];
  script_categories: DimensionRow[];
  top_click_scripts: ScriptRow[];
  top_download_scripts: ScriptRow[];
  top_register_scripts: ScriptRow[];
  top_payment_scripts: ScriptRow[];
  links: LinkRow[];
}

const formatUsd = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format((cents || 0) / 100);

const formatRate = (value: number) => `${((value || 0) * 100).toFixed(1)}%`;

function formatDuration(seconds: number) {
  if (!seconds) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
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
  const funnel = useMemo(() => summary?.funnel ?? [], [summary]);

  return (
    <AdminFrame
      operator={operator}
      active="data"
      title="链接与 App 转化"
      subtitle="追踪话术发送、链接曝光、点击、下载、注册、付费和升 A/S 的完整归因链路。"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-slate-800 bg-slate-900 p-1">
          {[1, 7, 14, 30, 90].map((value) => (
            <button
              key={value}
              onClick={() => {
                setDays(value);
                setSelectedDate("");
              }}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                days === value ? "bg-violet-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {value} 天
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
          <span className="text-sm text-slate-500">按天查询</span>
          <input
            type="date"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200 outline-none focus:border-violet-500"
          />
          {selectedDate && (
            <button
              onClick={() => setSelectedDate("")}
              className="rounded-md px-2 py-1 text-sm text-slate-400 transition hover:bg-slate-800 hover:text-white"
            >
              清除
            </button>
          )}
        </div>
        <span className="text-sm text-slate-500">
          {loading ? "加载中" : summary?.date ? `${summary.date} 当日` : `最近 ${summary?.days ?? days} 天`}
        </span>
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          数据加载失败：{error}
        </div>
      )}

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard label="今日链接点击人数" value={overview?.today_click_users ?? 0} />
        <MetricCard label="点击率" value={formatRate(overview?.click_rate ?? 0)} />
        <MetricCard label="下载转化率" value={formatRate(overview?.click_to_download_rate ?? 0)} />
        <MetricCard label="点击后付费金额" value={formatUsd(overview?.revenue_cents ?? 0)} />
        <MetricCard label="注册转化率" value={formatRate(overview?.click_to_register_rate ?? 0)} />
        <MetricCard label="付费转化率" value={formatRate(overview?.click_to_pay_rate ?? 0)} />
        <MetricCard label="点击到注册平均耗时" value={formatDuration(overview?.avg_click_to_register_seconds ?? 0)} />
        <MetricCard label="点击到首付平均耗时" value={formatDuration(overview?.avg_click_to_payment_seconds ?? 0)} />
      </section>

      <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-5 py-4">
          <h2 className="text-lg font-semibold">完整转化漏斗</h2>
        </div>
        <div className="grid grid-cols-1 divide-y divide-slate-800 md:grid-cols-4 md:divide-x md:divide-y-0 xl:grid-cols-8">
          {funnel.map((step) => (
            <div key={step.step} className="px-5 py-5">
              <div className="text-sm text-slate-500">{step.step}</div>
              <div className="mt-2 text-2xl font-semibold text-white">{step.users}</div>
              <div className="mt-2 text-xs text-slate-500">事件 {step.events}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ScriptPanel title="Top 点击话术" rows={summary?.top_click_scripts ?? []} metric="clicks" />
        <ScriptPanel title="Top 下载话术" rows={summary?.top_download_scripts ?? []} metric="downloads" />
        <ScriptPanel title="Top 注册话术" rows={summary?.top_register_scripts ?? []} metric="registrations" />
        <ScriptPanel title="Top 付费话术" rows={summary?.top_payment_scripts ?? []} metric="payments" />
      </section>

      <section className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <DimensionPanel title="国家点击排行" rows={summary?.countries ?? []} label="国家 / T1" />
        <DimensionPanel title="年龄段点击排行" rows={summary?.age_bands ?? []} label="年龄段" />
        <DimensionPanel title="各等级点击与付费" rows={summary?.levels ?? []} label="等级" />
        <DimensionPanel title="persona 转化" rows={summary?.personas ?? []} label="persona" />
        <DimensionPanel title="intent 转化" rows={summary?.intents ?? []} label="intent" />
        <DimensionPanel title="话术类目转化" rows={summary?.script_categories ?? []} label="类目" />
        <DimensionPanel title="TG 账号转化" rows={summary?.sender_accounts ?? []} label="账号" />
        <DimensionPanel title="渠道转化" rows={summary?.platforms ?? []} label="渠道" />
        <DimensionPanel title="设备系统转化" rows={summary?.devices ?? []} label="设备" />
      </section>

      <LinkPanel rows={summary?.links ?? []} />
    </AdminFrame>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function ScriptPanel({ title, rows, metric }: { title: string; rows: ScriptRow[]; metric: keyof ScriptRow }) {
  return (
    <Panel title={title} empty="暂无话术归因">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-950/50 text-slate-500">
          <tr>
            <th className="px-5 py-3 font-medium">话术</th>
            <th className="px-5 py-3 font-medium">intent / persona</th>
            <th className="px-5 py-3 font-medium">指标</th>
            <th className="px-5 py-3 font-medium">收入</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={`${title}-${row.script_key}`}>
              <td className="px-5 py-4 text-slate-300">
                <div className="font-mono text-xs text-sky-300">{row.script_key}</div>
                <div className="mt-1 text-xs text-slate-500">{row.scene_step || "-"} · {row.sender_account_id || "-"}</div>
              </td>
              <td className="px-5 py-4 text-slate-400">{row.intent || "-"} / {row.persona || "-"}</td>
              <td className="px-5 py-4 text-slate-100">{String(row[metric] ?? 0)}</td>
              <td className="px-5 py-4 text-slate-300">{formatUsd(row.revenue_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function DimensionPanel({ title, rows, label }: { title: string; rows: DimensionRow[]; label: string }) {
  return (
    <Panel title={title} empty="暂无维度数据">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-950/50 text-slate-500">
          <tr>
            <th className="px-5 py-3 font-medium">{label}</th>
            <th className="px-5 py-3 font-medium">点击</th>
            <th className="px-5 py-3 font-medium">下载</th>
            <th className="px-5 py-3 font-medium">注册</th>
            <th className="px-5 py-3 font-medium">付费</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={`${title}-${row.country_code || row.key}`}>
              <td className="px-5 py-4 text-slate-300">
                {row.country_code || row.key}
                {row.is_t1_country && <span className="ml-2 rounded-full bg-sky-500/10 px-2 py-0.5 text-xs text-sky-300">T1</span>}
              </td>
              <td className="px-5 py-4 text-slate-300">{row.clicks}</td>
              <td className="px-5 py-4 text-slate-300">{row.downloads}</td>
              <td className="px-5 py-4 text-slate-300">{row.registrations}</td>
              <td className="px-5 py-4 text-slate-300">{row.payments}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function LinkPanel({ rows }: { rows: LinkRow[] }) {
  return (
    <Panel title="单条链接明细" empty="暂无链接数据">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-950/50 text-slate-500">
          <tr>
            <th className="px-5 py-3 font-medium">tracking_id</th>
            <th className="px-5 py-3 font-medium">话术</th>
            <th className="px-5 py-3 font-medium">渠道/账号</th>
            <th className="px-5 py-3 font-medium">点击</th>
            <th className="px-5 py-3 font-medium">首点时间</th>
            <th className="px-5 py-3 font-medium">平均点击耗时</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={row.tracking_id}>
              <td className="px-5 py-4 font-mono text-xs text-sky-300">{row.tracking_id}</td>
              <td className="px-5 py-4 text-slate-300">{row.script_key}</td>
              <td className="px-5 py-4 text-slate-400">{row.platform || "-"} / {row.sender_account_id || "-"}</td>
              <td className="px-5 py-4 text-slate-300">{row.clicks} / {row.click_users}</td>
              <td className="px-5 py-4 text-slate-400">{row.first_click_at || "-"}</td>
              <td className="px-5 py-4 text-slate-300">{formatDuration(row.avg_seconds_to_click)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Panel({ title, empty, children }: { title: string; empty: string; children: React.ReactNode }) {
  const hasRows = String(children).length > 0;
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        {hasRows ? children : <div className="px-5 py-8 text-sm text-slate-500">{empty}</div>}
      </div>
    </div>
  );
}
