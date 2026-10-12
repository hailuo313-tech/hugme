"use client";

import { useCallback, useEffect, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

type State = {
  account_id: string;
  username?: string;
  connection_days: number;
  tier: number;
  effective_daily_limit: number;
  health_check_status: string;
  last_health_check_at?: string;
  last_health_error?: string;
  health_display_error?: string;
  is_new_account: boolean;
  status: string;
  pause_reason?: string;
  user_count?: number;
  active_today?: number;
};

type Overview = {
  latest?: {
    started_at: string;
    completed_at?: string;
    checked_count: number;
    healthy_count: number;
    new_count: number;
    pending_count: number;
    banned_count: number;
  };
  counts: {
    total: number;
    healthy: number;
    pending: number;
    restricted: number;
    banned: number;
    new_accounts: number;
    user_total?: number;
    active_today?: number;
  };
  schedule: string[];
};

const formatBeijingTime = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });

function healthLabel(status: string) {
  if (status === "healthy") return <span className="text-emerald-300">健康</span>;
  if (status === "banned") return <span className="text-red-300">确认被封</span>;
  if (status === "restricted") return <span className="text-amber-300">受限制</span>;
  return <span className="text-yellow-300">待复查</span>;
}

export default function Page() {
  return <AuthGate>{(op) => <Content operator={op} />}</AuthGate>;
}

function Content({ operator }: { operator: Operator }) {
  const [data, setData] = useState<Overview | null>(null);
  const [items, setItems] = useState<State[]>([]);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const [o, s] = await Promise.all([
      apiFetch<Overview>("/video-reinvite/admin/health-checks/overview"),
      apiFetch<{ items: State[] }>("/video-reinvite/admin/account-states"),
    ]);
    setData(o);
    setItems(s.items);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run() {
    await apiFetch("/video-reinvite/admin/health-checks/run", { method: "POST" });
    setNotice("体检已启动；系统正在逐个检查账号，请稍后刷新。");
  }

  const cards = data
    ? [
        ["账号总数", data.counts.total],
        ["绑定用户", data.counts.user_total ?? items.reduce((sum, item) => sum + (item.user_count || 0), 0)],
        ["今日活跃", data.counts.active_today ?? items.reduce((sum, item) => sum + (item.active_today || 0), 0)],
        ["健康", data.counts.healthy],
        ["新增账号", data.counts.new_accounts],
        ["待复查", data.counts.pending],
        ["受限制", data.counts.restricted],
        ["确认被封", data.counts.banned],
      ]
    : [];

  return (
    <AdminFrame
      operator={operator}
      active="tg-health"
      title="每日 TG 账号体检"
      subtitle="每天先检查账号授权、封禁、限制和新增状态；只有当天体检通过的账号才能执行视频二次邀请。用户数是该账号在 peer cache 里绑定过的去重用户。"
    >
      <div className="space-y-5">
        {notice && <div className="rounded border border-sky-700 bg-sky-950 p-3 text-sky-200">{notice}</div>}
        {data && (
          <>
            <section className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
              {cards.map(([k, v]) => (
                <div key={String(k)} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                  <div className="text-sm text-slate-400">{k}</div>
                  <div className="mt-2 text-2xl">{v}</div>
                </div>
              ))}
            </section>
            <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex items-center justify-between">
                <div>
                  <div>定时检查</div>
                  <div className="mt-2 text-sm text-slate-400">{data.schedule.join("；")}</div>
                </div>
                <button onClick={run} className="rounded bg-sky-700 px-4 py-2">
                  立即检查
                </button>
              </div>
            </section>
          </>
        )}
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-slate-400">
                  <th className="p-2">用户名</th>
                  <th>用户数</th>
                  <th>今日活跃</th>
                  <th>接入天数</th>
                  <th>等级/额度</th>
                  <th>体检结果</th>
                  <th>最近检查（北京时间）</th>
                  <th>错误/处理</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => {
                  const username = a.username ? `@${a.username.replace(/^@/, "")}` : "未设置用户名";
                  return (
                    <tr key={a.account_id} className="border-t border-slate-800">
                      <td className="p-2">
                        {username}
                        {a.is_new_account && (
                          <span className="ml-2 rounded bg-violet-900 px-2 py-0.5 text-xs">新增</span>
                        )}
                      </td>
                      <td className="font-medium text-sky-200">{a.user_count ?? 0}</td>
                      <td>{a.active_today ?? 0}</td>
                      <td>{a.connection_days}天</td>
                      <td>
                        L{a.tier} / {a.effective_daily_limit}人
                      </td>
                      <td>{healthLabel(a.health_check_status)}</td>
                      <td>{a.last_health_check_at ? formatBeijingTime(a.last_health_check_at) : "未检查"}</td>
                      <td className="max-w-sm break-all">
                        {a.health_display_error || a.last_health_error || a.pause_reason || "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </AdminFrame>
  );
}
