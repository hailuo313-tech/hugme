"use client";

import { useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

interface AttributionSummary {
  days: number;
  overview: {
    clicked_links: number;
    click_users: number;
    download_users: number;
    register_users: number;
    paid_users: number;
    revenue_cents: number;
    click_to_download_rate: number;
    download_to_register_rate: number;
    register_to_pay_rate: number;
  };
  by_country: Array<{ country_code: string; clicks: number; payments: number }>;
  top_scripts: Array<{
    script_key: string;
    clicks: number;
    downloads: number;
    registrations: number;
    payments: number;
    revenue_cents: number;
  }>;
}

const formatUsd = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format((cents || 0) / 100);

const formatRate = (value: number) => `${((value || 0) * 100).toFixed(1)}%`;

export default function DataPage() {
  return (
    <AuthGate>
      {(operator) => <DataDashboard operator={operator} />}
    </AuthGate>
  );
}

function DataDashboard({ operator }: { operator: Operator }) {
  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState<AttributionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiFetch<AttributionSummary>(`/admin/attribution/summary?days=${days}`)
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
  }, [days]);

  const overview = summary?.overview;
  const funnel = useMemo(
    () => [
      { label: "链接点击用户", value: overview?.click_users ?? 0 },
      { label: "下载用户", value: overview?.download_users ?? 0, rate: formatRate(overview?.click_to_download_rate ?? 0) },
      { label: "注册用户", value: overview?.register_users ?? 0, rate: formatRate(overview?.download_to_register_rate ?? 0) },
      { label: "付费用户", value: overview?.paid_users ?? 0, rate: formatRate(overview?.register_to_pay_rate ?? 0) },
    ],
    [overview]
  );

  return (
    <AdminFrame
      operator={operator}
      active="data"
      title="数据总览"
      subtitle="监控话术链接点击、国家/年龄分布、App 下载注册与付费归因，帮助判断哪些话术真正带来转化。"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-slate-800 bg-slate-900 p-1">
          {[7, 14, 30, 90].map((value) => (
            <button
              key={value}
              onClick={() => setDays(value)}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                days === value ? "bg-violet-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {value} 天
            </button>
          ))}
        </div>
        <span className="text-sm text-slate-500">{loading ? "加载中" : `最近 ${summary?.days ?? days} 天`}</span>
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          数据加载失败：{error}
        </div>
      )}

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard label="被点击链接" value={overview?.clicked_links ?? 0} />
        <MetricCard label="点击用户" value={overview?.click_users ?? 0} />
        <MetricCard label="付费用户" value={overview?.paid_users ?? 0} />
        <MetricCard label="归因收入" value={formatUsd(overview?.revenue_cents ?? 0)} />
      </section>

      <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-5 py-4">
          <h2 className="text-lg font-semibold">链接到 App 转化漏斗</h2>
        </div>
        <div className="grid grid-cols-1 divide-y divide-slate-800 md:grid-cols-4 md:divide-x md:divide-y-0">
          {funnel.map((step) => (
            <div key={step.label} className="px-5 py-5">
              <div className="text-sm text-slate-500">{step.label}</div>
              <div className="mt-2 text-2xl font-semibold text-white">{step.value}</div>
              {step.rate && <div className="mt-2 text-sm text-emerald-300">上一步转化 {step.rate}</div>}
            </div>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <TablePanel
          title="国家点击与付费"
          empty="暂无国家数据"
          headers={["国家", "点击", "付费"]}
          rows={(summary?.by_country ?? []).map((row) => [row.country_code, row.clicks, row.payments])}
        />
        <TablePanel
          title="高转化话术"
          empty="暂无话术归因"
          headers={["话术/命中", "点击", "下载", "注册", "付费", "收入"]}
          rows={(summary?.top_scripts ?? []).map((row) => [
            row.script_key,
            row.clicks,
            row.downloads,
            row.registrations,
            row.payments,
            formatUsd(row.revenue_cents),
          ])}
        />
      </section>
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

function TablePanel({
  title,
  empty,
  headers,
  rows,
}: {
  title: string;
  empty: string;
  headers: string[];
  rows: Array<Array<string | number>>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      {rows.length === 0 ? (
        <div className="px-5 py-8 text-sm text-slate-500">{empty}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-950/50 text-slate-500">
              <tr>
                {headers.map((header) => (
                  <th key={header} className="whitespace-nowrap px-5 py-3 font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="whitespace-nowrap px-5 py-4 text-slate-300">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
