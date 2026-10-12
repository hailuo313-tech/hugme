"use client";

import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";
import { beijingYmd, REPORT_TIMEZONE } from "@/lib/reportTime";

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

interface VideoCallsOverview {
  participating_users: number;
  completed_calls: number;
  auto_answer_completed: number;
  operator_queue_entered: number;
  operator_accepted: number;
  operator_cancelled: number;
  total_jobs: number;
  completion_rate: number;
  operator_accept_rate: number;
  auto_answer_share: number;
  avg_duration_seconds: number;
}

interface NurtureBucket {
  bucket: "new" | "old";
  label: string;
  target_users: number;
  executed_users: number;
  running_users: number;
  completed_users: number;
  replied_users: number;
  called_users: number;
  successful_video_users: number;
  failed_users: number;
  stopped_users: number;
  scheduled_tasks: number;
  sent_tasks: number;
  running_tasks: number;
  failed_tasks: number;
  reply_rate: number;
  call_rate: number;
  successful_video_rate: number;
}

interface NurtureReasonRow {
  bucket: "new" | "old";
  reason: string;
  users: number;
  tasks: number;
}

interface NurtureSummary {
  buckets: NurtureBucket[];
  stop_reasons: NurtureReasonRow[];
  failure_reasons: NurtureReasonRow[];
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
  admin_display_name?: string | null;
  phone?: string | null;
  username?: string | null;
  telegram_profile_name?: string | null;
  served_users: number;
  new_users_today: number;
  new_users_yesterday: number;
  new_users_total: number;
  new_users_last_30m: number;
  assistant_messages: number;
  last_message_at?: string | null;
  video_call_users: number;
  video_call_completed: number;
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
  timezone?: string;
  range_start_date?: string;
  range_end_date?: string;
  overview: Overview;
  video_calls: VideoCallsOverview;
  nurture?: NurtureSummary;
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
  { label: "今日", days: 1, dateOffsetDays: 0 },
  { label: "昨天", days: 1, dateOffsetDays: -1 },
  { label: "本周", days: 7 },
  { label: "30 天", days: 30 },
];

const FUNNEL_LABELS = ["话术发送", "链接曝光", "链接点击", "下载页访问", "App 下载"];
const SUMMARY_REFRESH_MS = 10 * 60 * 1000;

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
  const [days, setDays] = useState(1);
  const [selectedDate, setSelectedDate] = useState(beijingYmd(0));
  const [summary, setSummary] = useState<AttributionSummary | null>(null);
  const [nurture, setNurture] = useState<NurtureSummary | undefined>(undefined);
  const [nurtureLoading, setNurtureLoading] = useState(false);
  const [telegramAccounts, setTelegramAccounts] = useState<TelegramAccountRow[]>([]);
  const [telegramAccountsLoading, setTelegramAccountsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [telegramAccountsRefreshing, setTelegramAccountsRefreshing] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);

  const queryParams = selectedDate ? `date=${selectedDate}` : `days=${days}`;

  const loadNurture = useCallback(async (mounted = true) => {
    setNurtureLoading(true);
    try {
      const data = await apiFetch<NurtureSummary>("/admin/attribution/nurture", { retries: 1 });
      if (!mounted) return;
      setNurture(data);
    } catch (err) {
      if (!mounted) return;
      setError(err instanceof Error ? err.message : "培育数据加载失败");
    } finally {
      if (mounted) setNurtureLoading(false);
    }
  }, []);

  const loadTelegramAccounts = useCallback(async (mounted = true) => {
    setTelegramAccountsLoading(true);
    try {
      const data = await apiFetch<{ telegram_accounts: TelegramAccountRow[] }>(
        `/admin/attribution/telegram-accounts?${queryParams}`,
        { retries: 1 }
      );
      if (!mounted) return;
      setTelegramAccounts(data.telegram_accounts ?? []);
    } catch (err) {
      if (!mounted) return;
      setError(err instanceof Error ? err.message : "TG 账号接待表现加载失败");
    } finally {
      if (mounted) setTelegramAccountsLoading(false);
    }
  }, [queryParams]);

  const loadSummary = useCallback(
    async (mounted = true) => {
      setLoading(true);
      const coreQuery = `/admin/attribution/summary/core?${queryParams}`;

      void loadNurture(mounted);
      void loadTelegramAccounts(mounted);

      try {
        const data = await apiFetch<AttributionSummary>(coreQuery, { retries: 2 });
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
    [queryParams, loadNurture, loadTelegramAccounts]
  );

  const refreshTelegramAccounts = useCallback(async () => {
    setTelegramAccountsRefreshing(true);
    try {
      await apiFetch("/telegram/accounts/sync-profiles", { method: "POST", retries: 1 });
      const data = await apiFetch<{ telegram_accounts: TelegramAccountRow[] }>(
        `/admin/attribution/telegram-accounts?${queryParams}&refresh=1`,
        { retries: 1 }
      );
      setTelegramAccounts(data.telegram_accounts ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "TG 账号接待表现刷新失败");
    } finally {
      setTelegramAccountsRefreshing(false);
    }
  }, [queryParams]);

  useEffect(() => {
    let mounted = true;
    void loadSummary(mounted);
    const refreshTimer = window.setInterval(() => {
      void loadSummary(mounted);
    }, SUMMARY_REFRESH_MS);

    return () => {
      mounted = false;
      window.clearInterval(refreshTimer);
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
  const videoCalls = summary?.video_calls;
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

  const todayDate = beijingYmd(0);
  const yesterdayDate = beijingYmd(-1);
  const activeQuickLabel = QUICK_RANGES.find((item) =>
    item.dateOffsetDays !== undefined ? selectedDate === beijingYmd(item.dateOffsetDays) : !selectedDate && days === item.days
  )?.label;
  const rangeLabel = selectedDate
    ? selectedDate === todayDate
      ? "今日（北京时间）"
      : selectedDate === yesterdayDate
        ? "昨天（北京时间）"
        : `${selectedDate} 当天（北京时间）`
    : activeQuickLabel === "本周"
      ? `本周 ${summary?.range_start_date ?? ""} ~ ${summary?.range_end_date ?? ""}（北京时间）`
      : activeQuickLabel === "30 天"
        ? `最近 30 天 ${summary?.range_start_date ?? ""} ~ ${summary?.range_end_date ?? ""}（北京时间）`
        : activeQuickLabel
          ? `${activeQuickLabel}（北京时间）`
          : `最近 ${days} 天（北京时间）`;

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
                setSelectedDate(item.dateOffsetDays !== undefined ? beijingYmd(item.dateOffsetDays) : "");
              }}
              className={`rounded px-3 py-1.5 text-sm transition ${
                (item.dateOffsetDays !== undefined ? selectedDate === beijingYmd(item.dateOffsetDays) : !selectedDate && days === item.days)
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
        <MetricCard label="TG 新用户" value={overview?.tg_new_users ?? 0} hint="按 Telegram 用户去重 · 进多个 TG 号只计 1 人" />
        <MetricCard label="TG 接待用户" value={overview?.tg_served_users ?? 0} hint="按 Telegram 用户去重 · 跨 TG 号只计 1 人" />
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

      <section className="mb-3">
        <h2 className="text-base font-semibold text-slate-200">视频通话概览</h2>
        <p className="mt-1 text-sm text-slate-500">
          统计期内按任务创建时间（北京时间）计算。“参与通话人数”按 Telegram 用户去重；其余通话指标均按任务次数累计，同一用户多次通话会计多次。
        </p>
      </section>
      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="参与通话人数" value={videoCalls?.participating_users ?? 0} hint="人数 · 按 Telegram 用户去重" />
        <MetricCard label="成功播放次数" value={videoCalls?.completed_calls ?? 0} hint="次数 · 按成功通话任务累计" />
        <MetricCard label="自动接听次数" value={videoCalls?.auto_answer_completed ?? 0} hint="次数 · 按自动接听成功任务累计" />
        <MetricCard label="进入人工队列次数" value={videoCalls?.operator_queue_entered ?? 0} hint="次数 · 按进入队列任务累计" />
        <MetricCard label="人工接听成功次数" value={videoCalls?.operator_accepted ?? 0} hint="次数 · 按人工接听成功任务累计" />
        <MetricCard label="队列超时/拒绝次数" value={videoCalls?.operator_cancelled ?? 0} hint="次数 · 按超时或拒绝任务累计" />
      </section>
      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard label="接通率" value={formatRate(videoCalls?.completion_rate ?? 0)} />
        <MetricCard label="人工接听率" value={formatRate(videoCalls?.operator_accept_rate ?? 0)} />
        <MetricCard label="自动接听占比" value={formatRate(videoCalls?.auto_answer_share ?? 0)} />
        <MetricCard label="平均通话时长" value={formatDuration(videoCalls?.avg_duration_seconds ?? 0)} />
      </section>

      <NurturePanel summary={nurture} loading={nurtureLoading} />

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

      <TelegramAccountPanel
        rows={telegramAccounts}
        loading={telegramAccountsLoading}
        refreshing={telegramAccountsRefreshing}
        onRefresh={refreshTelegramAccounts}
      />

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

function MetricCard({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      {hint ? <div className="mt-2 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

function NurturePanel({ summary, loading }: { summary?: NurtureSummary; loading: boolean }) {
  const buckets = summary?.buckets ?? [
    emptyNurtureBucket("new", "新用户培育"),
    emptyNurtureBucket("old", "老用户培育"),
  ];
  const byBucket = new Map(buckets.map((bucket) => [bucket.bucket, bucket]));
  const rows = [
    byBucket.get("new") ?? emptyNurtureBucket("new", "新用户培育"),
    byBucket.get("old") ?? emptyNurtureBucket("old", "老用户培育"),
  ];

  return (
    <section className="mb-6 overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold">培育数据</h2>
        <p className="mt-1 text-sm text-slate-500">
          按培育任务生命周期统计；未完成任务跨天保留，完成/失败结果保留最近 7 天；24 小时内为新用户，超过 24 小时为老用户。
          {loading ? " 正在加载..." : ""}
        </p>
      </div>
      <div className="grid grid-cols-1 divide-y divide-slate-800 xl:grid-cols-2 xl:divide-x xl:divide-y-0">
        {rows.map((bucket) => (
          <div key={bucket.bucket} className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-100">{bucket.label}</h3>
              <span className="rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-400">
                任务 {bucket.scheduled_tasks}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <MiniMetric label="目标用户" value={bucket.target_users} />
              <MiniMetric label="已执行用户" value={bucket.executed_users} />
              <MiniMetric label="正在执行" value={bucket.running_users} />
              <MiniMetric label="完成用户" value={bucket.completed_users} />
              <MiniMetric label="有回复" value={bucket.replied_users} hint={formatRate(bucket.reply_rate)} />
              <MiniMetric label="打视频" value={bucket.called_users} hint={formatRate(bucket.call_rate)} />
              <MiniMetric label="视频成功" value={bucket.successful_video_users} hint={formatRate(bucket.successful_video_rate)} />
              <MiniMetric label="发送失败" value={bucket.failed_users} />
              <MiniMetric label="完成后不执行" value={bucket.stopped_users} />
              <MiniMetric label="已发任务" value={bucket.sent_tasks} />
              <MiniMetric label="待发任务" value={bucket.running_tasks} />
              <MiniMetric label="失败任务" value={bucket.failed_tasks} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function MiniMetric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 px-3 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function emptyNurtureBucket(bucket: "new" | "old", label: string): NurtureBucket {
  return {
    bucket,
    label,
    target_users: 0,
    executed_users: 0,
    running_users: 0,
    completed_users: 0,
    replied_users: 0,
    called_users: 0,
    successful_video_users: 0,
    failed_users: 0,
    stopped_users: 0,
    scheduled_tasks: 0,
    sent_tasks: 0,
    running_tasks: 0,
    failed_tasks: 0,
    reply_rate: 0,
    call_rate: 0,
    successful_video_rate: 0,
  };
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

function TelegramAccountPanel({
  rows,
  loading,
  refreshing,
  onRefresh,
}: {
  rows: TelegramAccountRow[];
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="mb-6 overflow-hidden rounded-md border border-slate-800 bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold">TG 账号接待表现</h2>
          <p className="mt-1 text-xs text-slate-500">
            按最近滚动 30 分钟由各 TG 账号实际新增的去重用户数从高到低排列，无需已接待。
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="rounded-md border border-sky-500 px-5 py-2 text-sm font-semibold text-sky-200 shadow-sm shadow-sky-950/40 hover:bg-sky-950/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {refreshing ? "正在刷新..." : "刷新TG账号"}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-max min-w-full text-left text-sm">
          <thead className="bg-slate-950/50 text-slate-500">
            <tr>
              <th className="min-w-[148px] whitespace-nowrap px-4 py-3 font-medium">TG 账号</th>
              <th className="min-w-[88px] whitespace-nowrap px-3 py-3 font-medium">显示名称</th>
              <th className="min-w-[92px] whitespace-nowrap px-3 py-3 font-medium text-center">30分钟新增</th>
              <th className="min-w-[92px] whitespace-nowrap px-3 py-3 font-medium text-center">今日新用户</th>
              <th className="min-w-[80px] whitespace-nowrap px-3 py-3 font-medium text-center">昨日用户</th>
              <th className="min-w-[88px] whitespace-nowrap px-3 py-3 font-medium text-center">TG总用户</th>
              <th className="min-w-[80px] whitespace-nowrap px-3 py-3 font-medium text-center">接待用户</th>
              <th className="min-w-[80px] whitespace-nowrap px-3 py-3 font-medium text-center">发送消息</th>
              <th className="min-w-[104px] whitespace-nowrap px-3 py-3 font-medium text-center">视频通话用户</th>
              <th className="min-w-[80px] whitespace-nowrap px-3 py-3 font-medium text-center">成功播放</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.length ? (
              rows.map((row) => (
                <tr key={row.account_id}>
                  <td className="px-4 py-4 text-slate-300">
                    <div className="font-medium text-slate-100">
                      {row.username ? `@${row.username}` : row.phone || row.account_label}
                    </div>
                    {row.telegram_profile_name ? (
                      <div className="mt-1 text-xs text-slate-500">{row.telegram_profile_name}</div>
                    ) : (
                      <div className="mt-1 text-xs text-slate-500">{row.phone || row.account_id}</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-4 text-slate-100">{row.admin_display_name || "-"}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center font-semibold text-sky-300">{row.new_users_last_30m}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.new_users_today}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.new_users_yesterday}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.new_users_total}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.served_users}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-300">{row.assistant_messages}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.video_call_users}</td>
                  <td className="whitespace-nowrap px-3 py-4 text-center text-slate-100">{row.video_call_completed}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-5 py-8 text-sm text-slate-500" colSpan={10}>
                  {loading || refreshing ? "正在加载 TG 账号接待数据..." : "暂无 TG 账号接待数据"}
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
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.replace("T", " ").slice(0, 16);
  return parsed.toLocaleString("zh-CN", {
    timeZone: REPORT_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
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
