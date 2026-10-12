"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import AdminFrame from "@/components/AdminFrame";
import AuthGate from "@/components/AuthGate";
import { apiFetch, API_BASE, getToken, Operator } from "@/lib/auth";
import {
  callDurationLabel,
  callStatusClassName,
  callStatusLabel,
} from "@/lib/callBroadcastStatus";

type AssetType = "image" | "video" | "voice" | "audio";

type FixedAsset = {
  id: string;
  asset_type: AssetType;
  asset_url: string;
  original_filename?: string | null;
  caption?: string | null;
  sort_order: number;
};

type Rule = {
  id: string;
  name: string;
  text_content: string;
  delay_seconds: number;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
  assets: FixedAsset[];
};

type Job = {
  id: string;
  rule_name: string;
  external_user_id: string;
  status: string;
  send_at: string;
  sent_at?: string | null;
  failure_reason?: string | null;
  delivery_count: number;
  failed_delivery_count: number;
  created_at: string;
};

type CallHistoryRecord = {
  job_id: string;
  user_id: string | null;
  nickname: string | null;
  external_id: string | null;
  chat_id: number | null;
  status: string | null;
  trigger_source: string | null;
  call_at: string | null;
  started_at?: string | null;
  video_title: string | null;
  duration_seconds: number;
  inbound_call_number: number | null;
  telegram_account_id: string | null;
  telegram_account_label: string | null;
  telegram_account_phone: string | null;
  telegram_account_name: string | null;
  telegram_account_username: string | null;
  telegram_account_reply_mode?: string | null;
};

type CallHistoryResponse = {
  items: CallHistoryRecord[];
  total: number;
  page: number;
  page_size: number;
};

type FixedOverviewSummary = {
  fixed_account_count: number;
  connected_fixed_account_count: number;
  total_rule_count: number;
  active_rule_count: number;
  today_new_users: number;
  today_touched_users: number;
  today_reply_users: number;
  today_video_users: number;
  today_video_success_users: number;
  today_link_received_users: number;
  today_link_click_users: number;
  today_generated_jobs: number;
  today_sent_jobs: number;
  today_pending_jobs: number;
  today_failed_jobs: number;
  today_skipped_jobs: number;
  today_video_calls?: number;
  today_video_success?: number;
};

type FixedOverviewAccount = {
  id: string;
  phone?: string | null;
  display_name?: string | null;
  username?: string | null;
  status?: string | null;
  is_active?: boolean;
  last_connected_at?: string | null;
  error_message?: string | null;
  today_new_users: number;
  today_touched_users: number;
  today_sent_jobs: number;
  today_failed_jobs: number;
  today_reply_users: number;
  today_video_users: number;
  today_video_calls: number;
  today_video_success: number;
};

type FixedOverviewRule = {
  id: string;
  name: string;
  delay_seconds: number;
  is_active: boolean;
  total_users: number;
  sent_users: number;
  pending_jobs: number;
  failed_jobs: number;
  reply_users: number;
  video_users: number;
  video_success_users: number;
};

type FixedOverviewFailure = {
  reason: string;
  count: number;
  last_at?: string | null;
};

type FixedOverview = {
  summary: FixedOverviewSummary;
  accounts: FixedOverviewAccount[];
  rules: FixedOverviewRule[];
  failures: FixedOverviewFailure[];
};

type OverviewRange = "today" | "yesterday" | "week" | "month" | "custom";

const overviewRangeOptions: Array<{ key: Exclude<OverviewRange, "custom">; label: string; prefix: string }> = [
  { key: "today", label: "今天", prefix: "今天" },
  { key: "yesterday", label: "昨天", prefix: "昨天" },
  { key: "week", label: "本周", prefix: "本周" },
  { key: "month", label: "本月", prefix: "本月" },
];

const emptyOverviewSummary: FixedOverviewSummary = {
  fixed_account_count: 0,
  connected_fixed_account_count: 0,
  total_rule_count: 0,
  active_rule_count: 0,
  today_new_users: 0,
  today_touched_users: 0,
  today_reply_users: 0,
  today_video_users: 0,
  today_video_success_users: 0,
  today_link_received_users: 0,
  today_link_click_users: 0,
  today_generated_jobs: 0,
  today_sent_jobs: 0,
  today_pending_jobs: 0,
  today_failed_jobs: 0,
  today_skipped_jobs: 0,
};

const emptyOverview: FixedOverview = {
  summary: emptyOverviewSummary,
  accounts: [],
  rules: [],
  failures: [],
};

function normalizeOverview(value: Partial<FixedOverview> | null | undefined): FixedOverview {
  return {
    summary: { ...emptyOverviewSummary, ...(value?.summary || {}) },
    accounts: Array.isArray(value?.accounts) ? value.accounts : [],
    rules: Array.isArray(value?.rules) ? value.rules : [],
    failures: Array.isArray(value?.failures) ? value.failures : [],
  };
}

type RuleForm = {
  id?: string;
  name: string;
  text_content: string;
  delay_seconds: number;
  is_active: boolean;
};

const emptyForm: RuleForm = {
  name: "",
  text_content: "",
  delay_seconds: 0,
  is_active: false,
};

const assetLabels: Record<AssetType, string> = {
  image: "图片",
  video: "视频",
  voice: "语音",
  audio: "音频",
};

const statusLabels: Record<string, string> = {
  pending: "待发送",
  sending: "发送中",
  sent: "已发送",
  failed: "失败",
  skipped: "已跳过",
};

const VIDEO_CALL_LIST_SIZE = 20;
const VIDEO_CALL_REFRESH_MS = 5 * 60 * 1000;

function fmtDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function triggerSourceLabel(source: string | null) {
  switch (source) {
    case "inbound_keyword_review":
      return "文字打视频";
    case "inbound_keyword":
      return "8866 触发";
    case "inbound_call":
      return "来电自动接听";
    case "inbound_operator_review":
      return "人工接听";
    case "admin_manual":
      return "后台手动";
    default:
      return source || "—";
  }
}

function delayText(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
  return `${Math.round(seconds / 3600)} 小时`;
}

function pct(value: number, total: number) {
  if (!total) return "0.0%";
  return `${((value / total) * 100).toFixed(1)}%`;
}

function overviewPrefix(range: OverviewRange, customDate: string) {
  if (range === "custom") return customDate || "所选日期";
  return overviewRangeOptions.find((item) => item.key === range)?.prefix || "今天";
}

function buildOverviewParams(
  range: OverviewRange,
  dateValue: string,
  forceRefresh = false,
) {
  const params = new URLSearchParams();
  if (range === "custom" && dateValue) {
    params.set("date", dateValue);
  } else {
    params.set("range", range === "custom" ? "today" : range);
  }
  if (forceRefresh) {
    params.set("force_refresh", "true");
  }
  return params;
}

function overviewStatCard(label: string, value: string | number, hint: string) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
      <div className="text-sm text-slate-400">{label}</div>
      <div className="mt-2 text-3xl font-semibold">{value}</div>
      <div className="mt-2 text-xs text-slate-500">{hint}</div>
    </div>
  );
}

function accountLabel(account: FixedOverviewAccount) {
  if (account.display_name) return account.display_name;
  if (account.username) return `@${account.username}`;
  if (account.phone) return account.phone;
  return account.id;
}

function ruleToForm(rule: Rule): RuleForm {
  return {
    id: rule.id,
    name: rule.name,
    text_content: rule.text_content,
    delay_seconds: rule.delay_seconds,
    is_active: rule.is_active,
  };
}

function FixedRepliesPage({ operator }: { operator: Operator }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [form, setForm] = useState<RuleForm>(emptyForm);
  const [assetRuleId, setAssetRuleId] = useState<string>("");
  const [assetType, setAssetType] = useState<AssetType>("image");
  const [assetCaption, setAssetCaption] = useState("");
  const [assetSortOrder, setAssetSortOrder] = useState(0);
  const [assetFile, setAssetFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [callRecords, setCallRecords] = useState<CallHistoryRecord[]>([]);
  const [callTotal, setCallTotal] = useState(0);
  const [callSearch, setCallSearch] = useState("");
  const callSearchRef = useRef(callSearch);
  callSearchRef.current = callSearch;
  const [callLoading, setCallLoading] = useState(false);
  const [callError, setCallError] = useState("");
  const [overview, setOverview] = useState<FixedOverview | null>(null);
  const [overviewRange, setOverviewRange] = useState<OverviewRange>("today");
  const [overviewDate, setOverviewDate] = useState("");
  const [overviewSummaryLoading, setOverviewSummaryLoading] = useState(false);
  const [overviewDetailsLoading, setOverviewDetailsLoading] = useState(false);
  const [overviewAccountsRefreshing, setOverviewAccountsRefreshing] = useState(false);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [callHistoryOpen, setCallHistoryOpen] = useState(false);
  const skipOverviewRangeReload = useRef(true);
  const callHistorySectionRef = useRef<HTMLElement | null>(null);

  const activeCount = useMemo(() => rules.filter((rule) => rule.is_active).length, [rules]);
  const overviewData = overview || emptyOverview;
  const overviewSummary = overviewData.summary;
  const overviewAccounts = overviewData.accounts;
  const overviewRules = overviewData.rules;
  const overviewPeriodLabel = overviewPrefix(overviewRange, overviewDate);

  const loadOverviewSummary = useCallback(async (
    range = overviewRange,
    dateValue = overviewDate,
    forceRefresh = false,
  ) => {
    setOverviewSummaryLoading(true);
    try {
      const params = buildOverviewParams(range, dateValue, forceRefresh);
      const res = await apiFetch<{ summary: FixedOverviewSummary }>(
        `/fixed-auto-replies/admin/overview/summary?${params.toString()}`,
        { retries: 1 },
      );
      setOverview((current) => ({
        ...normalizeOverview(current),
        summary: { ...emptyOverviewSummary, ...(res.summary || {}) },
      }));
    } finally {
      setOverviewSummaryLoading(false);
    }
  }, [overviewRange, overviewDate]);

  const loadOverviewDetails = useCallback(async (
    range = overviewRange,
    dateValue = overviewDate,
    forceRefresh = false,
  ) => {
    setOverviewDetailsLoading(true);
    try {
      const params = buildOverviewParams(range, dateValue, forceRefresh);
      const [accountsRes, rulesRes] = await Promise.all([
        apiFetch<{ accounts: FixedOverviewAccount[] }>(
          `/fixed-auto-replies/admin/overview/accounts?${params.toString()}`,
          { retries: 1 },
        ),
        apiFetch<{ rules: FixedOverviewRule[] }>(
          `/fixed-auto-replies/admin/overview/rules?${params.toString()}`,
          { retries: 1 },
        ),
      ]);
      setOverview((current) => ({
        ...normalizeOverview(current),
        accounts: accountsRes.accounts || [],
        rules: rulesRes.rules || [],
      }));
    } finally {
      setOverviewDetailsLoading(false);
    }
  }, [overviewRange, overviewDate]);

  const refreshOverviewAccounts = useCallback(async () => {
    setOverviewAccountsRefreshing(true);
    setError("");
    try {
      await apiFetch("/telegram/accounts/sync-profiles", { method: "POST", retries: 1 });
      const params = buildOverviewParams(overviewRange, overviewDate, true);
      const accountsRes = await apiFetch<{ accounts: FixedOverviewAccount[] }>(
        `/fixed-auto-replies/admin/overview/accounts?${params.toString()}`,
        { retries: 1 },
      );
      setOverview((current) => ({
        ...normalizeOverview(current),
        accounts: accountsRes.accounts || [],
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "TG 账号接待表现刷新失败");
    } finally {
      setOverviewAccountsRefreshing(false);
    }
  }, [overviewRange, overviewDate]);

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const jobRes = await apiFetch<{ items: Job[] }>("/fixed-auto-replies/admin/jobs?limit=50", { retries: 1 });
      setJobs(jobRes.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送记录加载失败");
    } finally {
      setJobsLoading(false);
    }
  }, []);

  const loadInitialPage = useCallback(async () => {
    setError("");
    const [ruleRes] = await Promise.all([
      apiFetch<{ items: Rule[] }>("/fixed-auto-replies/admin/rules", { retries: 1 }),
      loadOverviewSummary(),
    ]);
    setRules(ruleRes.items || []);
    void loadOverviewDetails();
    void loadJobs();
  }, [loadOverviewSummary, loadOverviewDetails, loadJobs]);

  const reloadOverview = useCallback(async (forceRefresh = false) => {
    await loadOverviewSummary(overviewRange, overviewDate, forceRefresh);
    await loadOverviewDetails(overviewRange, overviewDate, forceRefresh);
  }, [loadOverviewDetails, loadOverviewSummary, overviewDate, overviewRange]);

  const loadFixedCallHistory = useCallback(async (
    search = callSearch,
    options?: { silent?: boolean },
  ) => {
    if (!options?.silent) setCallLoading(true);
    setCallError("");
    try {
      const params = new URLSearchParams({
        page: "1",
        page_size: String(VIDEO_CALL_LIST_SIZE),
        reply_mode: "fixed",
      });
      if (search.trim()) params.set("search", search.trim());
      const data = await apiFetch<CallHistoryResponse>(
        `/call-broadcast/admin/call-history?${params.toString()}`,
        { retries: 1 },
      );
      setCallRecords(data.items || []);
      setCallTotal(data.total || 0);
    } catch (err) {
      setCallError(err instanceof Error ? err.message : "视频接听列表加载失败");
    } finally {
      if (!options?.silent) setCallLoading(false);
    }
  }, [callSearch]);

  useEffect(() => {
    loadInitialPage().catch((err) => setError(err.message || "数据加载失败"));
  }, [loadInitialPage]);

  useEffect(() => {
    if (skipOverviewRangeReload.current) {
      skipOverviewRangeReload.current = false;
      return;
    }
    reloadOverview().catch((err) => setError(err.message || "运营总览加载失败"));
  }, [overviewRange, overviewDate, reloadOverview]);

  useEffect(() => {
    const node = callHistorySectionRef.current;
    if (!node || callHistoryOpen) return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setCallHistoryOpen(true);
      },
      { rootMargin: "240px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [callHistoryOpen]);

  useEffect(() => {
    if (!callHistoryOpen) return undefined;
    loadFixedCallHistory(callSearchRef.current).catch(
      (err) => setCallError(err.message || "视频接听列表加载失败"),
    );
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadFixedCallHistory(callSearchRef.current, { silent: true });
    }, VIDEO_CALL_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [callHistoryOpen, loadFixedCallHistory]);

  async function saveRule(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setNotice("");
    setError("");
    try {
      const payload = {
        name: form.name.trim(),
        text_content: form.text_content,
        delay_seconds: Number(form.delay_seconds || 0),
        is_active: form.is_active,
      };
      if (!payload.name) throw new Error("请填写规则名称");
      if (form.id) {
        await apiFetch(`/fixed-auto-replies/admin/rules/${form.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        setNotice("规则已更新");
      } else {
        await apiFetch("/fixed-auto-replies/admin/rules", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setNotice("规则已创建");
      }
      setForm(emptyForm);
      await loadInitialPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setLoading(false);
    }
  }

  async function toggleRule(rule: Rule) {
    setError("");
    setNotice("");
    await apiFetch(`/fixed-auto-replies/admin/rules/${rule.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !rule.is_active }),
    });
    setNotice(rule.is_active ? "规则已停用" : "规则已启用，新进用户会开始排队发送");
    await loadInitialPage();
  }

  async function deleteRule(rule: Rule) {
    if (!window.confirm(`删除规则「${rule.name}」？发送记录会一起删除。`)) return;
    setError("");
    setNotice("");
    await apiFetch(`/fixed-auto-replies/admin/rules/${rule.id}`, { method: "DELETE" });
    setNotice("规则已删除");
    await loadInitialPage();
  }

  async function uploadAsset(event: FormEvent) {
    event.preventDefault();
    if (!assetRuleId || !assetFile) {
      setError("请选择规则和文件");
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const token = getToken();
      const data = new FormData();
      data.append("asset_type", assetType);
      data.append("caption", assetCaption);
      data.append("sort_order", String(assetSortOrder || 0));
      data.append("file", assetFile);
      const res = await fetch(`${API_BASE}/fixed-auto-replies/admin/rules/${assetRuleId}/assets`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: data,
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "上传失败");
      }
      setNotice("附件已上传");
      setAssetCaption("");
      setAssetSortOrder(0);
      setAssetFile(null);
      const input = document.getElementById("fixed-asset-file") as HTMLInputElement | null;
      if (input) input.value = "";
      await loadInitialPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  }

  async function deleteAsset(asset: FixedAsset) {
    setError("");
    setNotice("");
    await apiFetch(`/fixed-auto-replies/admin/assets/${asset.id}`, { method: "DELETE" });
    setNotice("附件已删除");
    await loadInitialPage();
  }

  async function runOnce() {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const res = await apiFetch<{ enqueued: number; sent: number; failed: number }>(
        "/fixed-auto-replies/admin/run-once",
        { method: "POST" },
      );
      setNotice(`已执行一次：新增任务 ${res.enqueued}，发送成功 ${res.sent}，失败 ${res.failed}`);
      await loadInitialPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "执行失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AdminFrame
      operator={operator}
      active="fixed"
      title="固定自动回复"
      subtitle="独立配置用户进来后的固定文字和媒体，不进入 AI、话术库、培育和精聊链路。"
    >
      <div className="space-y-6">
        {(notice || error) && (
          <div
            className={`rounded-md border px-4 py-3 text-sm ${
              error
                ? "border-rose-700 bg-rose-950/40 text-rose-200"
                : "border-violet-700 bg-violet-950/40 text-violet-200"
            }`}
          >
            {error || notice}
          </div>
        )}

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 p-4">
            <div>
              <h2 className="text-lg font-semibold">
                运营总览
                {overviewSummaryLoading ? (
                  <span className="ml-2 text-sm font-normal text-slate-500">指标刷新中...</span>
                ) : null}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                仅统计 fixed 模式 TG 账号与固定回复任务；时间范围按北京时间计算。
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <div className="flex rounded-md border border-slate-800 bg-slate-950 p-1">
                {overviewRangeOptions.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setOverviewRange(item.key);
                      setOverviewDate("");
                    }}
                    className={`rounded px-3 py-1.5 text-sm ${
                      overviewRange === item.key
                        ? "bg-violet-600 text-white"
                        : "text-slate-300 hover:bg-slate-800"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <input
                type="date"
                value={overviewDate}
                onChange={(event) => {
                  setOverviewDate(event.target.value);
                  setOverviewRange(event.target.value ? "custom" : "today");
                }}
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500"
              />
              <button
                type="button"
                onClick={() => reloadOverview(true).catch((err) => setError(err.message || "刷新失败"))}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
              >
                刷新数据
              </button>
            </div>
          </div>
          <div className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {overviewStatCard(
                "固定 TG 账号",
                overviewSummary.fixed_account_count,
                `配置项 · 已连接 ${overviewSummary.connected_fixed_account_count}`,
              )}
              {overviewStatCard(
                "启用规则",
                overviewSummary.active_rule_count || activeCount,
                `配置项 · 规则总数 ${overviewSummary.total_rule_count || rules.length}`,
              )}
            </div>

            <div>
              <h3 className="text-sm font-medium text-slate-300">用户指标（按用户去重）</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {overviewStatCard(
                  `${overviewPeriodLabel}新增用户`,
                  overviewSummary.today_new_users,
                  "按 Telegram 用户去重 · 进多个固定号只计1人 · 北京时间",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}触达用户`,
                  overviewSummary.today_touched_users,
                  "按 Telegram 用户去重 · 进多个固定号只计1人 · 北京时间",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}回复用户`,
                  overviewSummary.today_reply_users,
                  `按 Telegram 用户去重 · 跨TG号只计1人 · 回复率 ${pct(overviewSummary.today_reply_users, overviewSummary.today_touched_users)}`,
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}收到链接用户`,
                  overviewSummary.today_link_received_users,
                  `ERIS用户去重 · 跨TG号只计1次 · 多条链接只计1次 · 北京时间0点-0点 · 点击率 ${pct(overviewSummary.today_link_click_users, overviewSummary.today_link_received_users)}`,
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}点击链接用户`,
                  overviewSummary.today_link_click_users,
                  "ERIS用户去重 · 跨TG号只计1次 · 多次点击只计1次 · 北京时间0点-0点",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}视频用户`,
                  overviewSummary.today_video_users,
                  "按 Telegram 用户去重 · 跨TG号只计1人 · 北京时间",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}成功播放用户`,
                  overviewSummary.today_video_success_users,
                  "按 Telegram 用户去重 · 跨TG号只计1人 · 北京时间",
                )}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-medium text-slate-300">任务指标（按任务条数）</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {overviewStatCard(
                  `${overviewPeriodLabel}生成任务`,
                  overviewSummary.today_generated_jobs,
                  "按任务数量 · 按北京时间统计",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}已发送任务`,
                  overviewSummary.today_sent_jobs,
                  "按任务数量 · 按 sent_at · 按北京时间统计",
                )}
                {overviewStatCard(
                  "待发送任务",
                  overviewSummary.today_pending_jobs,
                  "按任务数量 · 当前排队中（含未到发送时间）",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}失败任务`,
                  overviewSummary.today_failed_jobs,
                  "按任务数量 · 按北京时间统计",
                )}
                {overviewStatCard(
                  `${overviewPeriodLabel}跳过任务`,
                  overviewSummary.today_skipped_jobs,
                  "按任务数量 · 按北京时间统计",
                )}
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="flex flex-col gap-3 border-b border-slate-800 p-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">
                TG 账号接待表现
                {overviewDetailsLoading ? (
                  <span className="ml-2 text-sm font-normal text-slate-500">加载中...</span>
                ) : null}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                看每个接入固定回复的 TG 账号{overviewPeriodLabel}新增、接待、发送、视频和成功播放情况。
              </p>
            </div>
            <button
              type="button"
              onClick={() => refreshOverviewAccounts()}
              disabled={overviewAccountsRefreshing}
              className="shrink-0 rounded-md border border-sky-500 px-5 py-2 text-sm font-semibold text-sky-200 shadow-sm shadow-sky-950/40 hover:bg-sky-950/40 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {overviewAccountsRefreshing ? "正在刷新..." : "刷新TG账号"}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-4 py-3">账号</th>
                  <th className="px-4 py-3">连接</th>
                  <th className="px-4 py-3">{overviewPeriodLabel}新用户</th>
                  <th className="px-4 py-3">{overviewPeriodLabel}接待用户</th>
                  <th className="px-4 py-3">{overviewPeriodLabel}发送消息</th>
                  <th className="px-4 py-3">{overviewPeriodLabel}视频通话用户</th>
                  <th className="px-4 py-3">{overviewPeriodLabel}成功播放</th>
                  <th className="px-4 py-3">最后接待</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {overviewDetailsLoading && overviewAccounts.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={8}>
                      加载账号表现...
                    </td>
                  </tr>
                ) : overviewAccounts.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={8}>
                      暂无固定回复账号
                    </td>
                  </tr>
                ) : (
                  overviewAccounts.map((account) => (
                    <tr key={account.id} className="text-slate-200">
                      <td className="px-4 py-3">
                        <div className="font-medium">{accountLabel(account)}</div>
                        <div className="text-xs text-slate-500">
                          {account.username ? `@${account.username}` : account.id}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={account.status === "connected" ? "text-emerald-300" : "text-amber-300"}>
                          {account.status || "-"}
                        </span>
                      </td>
                      <td className="px-4 py-3">{account.today_new_users ?? 0}</td>
                      <td className="px-4 py-3">{account.today_touched_users ?? 0}</td>
                      <td className="px-4 py-3">{account.today_sent_jobs ?? 0}</td>
                      <td className="px-4 py-3">{account.today_video_users ?? 0}</td>
                      <td className="px-4 py-3">{account.today_video_success ?? 0}</td>
                      <td className="px-4 py-3 text-slate-400">{fmtDate(account.last_connected_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <h2 className="text-lg font-semibold">
              规则效果排行
              {overviewDetailsLoading ? (
                <span className="ml-2 text-sm font-normal text-slate-500">加载中...</span>
              ) : null}
            </h2>
            <p className="mt-1 text-sm text-slate-400">看每条固定回复规则带来的用户回复和视频来电，方便运营调整内容和延迟。</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-4 py-3">规则</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">延迟</th>
                  <th className="px-4 py-3">发送用户</th>
                  <th className="px-4 py-3">回复用户</th>
                  <th className="px-4 py-3">视频用户</th>
                  <th className="px-4 py-3">成功视频</th>
                  <th className="px-4 py-3">失败任务</th>
                  <th className="px-4 py-3">回复率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {overviewDetailsLoading && overviewRules.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={9}>
                      加载规则效果...
                    </td>
                  </tr>
                ) : overviewRules.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={9}>
                      暂无规则效果数据
                    </td>
                  </tr>
                ) : (
                  overviewRules.map((rule) => (
                    <tr key={rule.id} className="text-slate-200">
                      <td className="px-4 py-3 font-medium">{rule.name}</td>
                      <td className="px-4 py-3">
                        <span className={rule.is_active ? "text-emerald-300" : "text-slate-500"}>
                          {rule.is_active ? "启用" : "停用"}
                        </span>
                      </td>
                      <td className="px-4 py-3">{delayText(rule.delay_seconds)}</td>
                      <td className="px-4 py-3">{rule.sent_users}</td>
                      <td className="px-4 py-3">{rule.reply_users}</td>
                      <td className="px-4 py-3">{rule.video_users}</td>
                      <td className="px-4 py-3">{rule.video_success_users}</td>
                      <td className="px-4 py-3 text-rose-200">{rule.failed_jobs}</td>
                      <td className="px-4 py-3">{pct(rule.reply_users, rule.sent_users)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 p-4">
            <div>
              <h2 className="text-lg font-semibold">新增 / 编辑规则</h2>
              <p className="mt-1 text-sm text-slate-400">启用后只对启用之后新进入的 TG 用户生效。</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={runOnce}
                disabled={loading}
                className="rounded-md border border-cyan-700 px-4 py-2 text-sm text-cyan-200 hover:bg-cyan-950 disabled:opacity-50"
              >
                立即跑一次
              </button>
              <button
                type="button"
                onClick={() => loadInitialPage().catch((err) => setError(err.message || "刷新失败"))}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
              >
                刷新
              </button>
            </div>
          </div>
          <form onSubmit={saveRule} className="grid gap-4 p-4 lg:grid-cols-[1fr_160px_120px]">
            <label className="block">
              <span className="text-sm text-slate-300">规则名称</span>
              <input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
                placeholder="例如：新用户欢迎图文"
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-300">延迟时间（秒）</span>
              <input
                type="number"
                min={0}
                value={form.delay_seconds}
                onChange={(event) => setForm({ ...form, delay_seconds: Number(event.target.value || 0) })}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
              />
            </label>
            <label className="block lg:col-span-2">
              <span className="text-sm text-slate-300">文字内容</span>
              <textarea
                value={form.text_content}
                onChange={(event) => setForm({ ...form, text_content: event.target.value })}
                className="mt-2 min-h-32 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
                placeholder="用户进来后按延迟发送的固定文字"
              />
            </label>
            <div className="flex flex-wrap items-center gap-3 lg:col-span-3">
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) => setForm({ ...form, is_active: event.target.checked })}
                  className="h-4 w-4 accent-violet-500"
                />
                启用规则
              </label>
              <button
                disabled={loading}
                className="rounded-md bg-violet-600 px-5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                {form.id ? "保存修改" : "新增规则"}
              </button>
              {form.id && (
                <button
                  type="button"
                  onClick={() => setForm(emptyForm)}
                  className="rounded-md border border-slate-700 px-5 py-2 text-sm text-slate-200 hover:bg-slate-800"
                >
                  取消编辑
                </button>
              )}
            </div>
          </form>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <h2 className="text-lg font-semibold">上传附件</h2>
            <p className="mt-1 text-sm text-slate-400">附件会跟在文字后面按排序发送，支持图片、视频、语音和音频。</p>
          </div>
          <form onSubmit={uploadAsset} className="grid gap-4 p-4 lg:grid-cols-[1fr_140px_120px_1fr]">
            <label className="block">
              <span className="text-sm text-slate-300">选择规则</span>
              <select
                value={assetRuleId}
                onChange={(event) => setAssetRuleId(event.target.value)}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
              >
                <option value="">请选择规则</option>
                {rules.map((rule) => (
                  <option key={rule.id} value={rule.id}>
                    {rule.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm text-slate-300">类型</span>
              <select
                value={assetType}
                onChange={(event) => setAssetType(event.target.value as AssetType)}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
              >
                {Object.entries(assetLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm text-slate-300">排序</span>
              <input
                type="number"
                value={assetSortOrder}
                onChange={(event) => setAssetSortOrder(Number(event.target.value || 0))}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-300">文件</span>
              <input
                id="fixed-asset-file"
                type="file"
                onChange={(event) => setAssetFile(event.target.files?.[0] || null)}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white file:mr-3 file:rounded-md file:border-0 file:bg-slate-700 file:px-3 file:py-1 file:text-white"
              />
            </label>
            <label className="block lg:col-span-4">
              <span className="text-sm text-slate-300">附件标题（可选）</span>
              <input
                value={assetCaption}
                onChange={(event) => setAssetCaption(event.target.value)}
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
                placeholder="发图片/视频时附带的 caption"
              />
            </label>
            <div className="lg:col-span-4">
              <button
                disabled={loading}
                className="rounded-md bg-violet-600 px-5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                上传到规则
              </button>
            </div>
          </form>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <h2 className="text-lg font-semibold">规则列表</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {rules.length === 0 ? (
              <div className="p-6 text-sm text-slate-500">暂无规则</div>
            ) : (
              rules.map((rule) => (
                <div key={rule.id} className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-violet-950 px-2 py-0.5 text-xs font-medium text-violet-200">
                          #{rule.sort_order}
                        </span>
                        <h3 className="text-base font-semibold">{rule.name}</h3>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            rule.is_active
                              ? "bg-emerald-950 text-emerald-300"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {rule.is_active ? "启用" : "停用"}
                        </span>
                        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                          延迟 {delayText(rule.delay_seconds)}
                        </span>
                      </div>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">
                        {rule.text_content || "未配置文字，只发送附件"}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {rule.assets.length === 0 ? (
                          <span className="text-sm text-slate-500">暂无附件</span>
                        ) : (
                          rule.assets.map((asset) => (
                            <span
                              key={asset.id}
                              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200"
                            >
                              {assetLabels[asset.asset_type]} · {asset.original_filename || asset.asset_url}
                              <button
                                type="button"
                                onClick={() => deleteAsset(asset).catch((err) => setError(err.message || "删除附件失败"))}
                                className="text-rose-300 hover:text-rose-100"
                              >
                                删除
                              </button>
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setForm(ruleToForm(rule))}
                        className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleRule(rule).catch((err) => setError(err.message || "启停失败"))}
                        className={`rounded-md border px-3 py-2 text-sm ${
                          rule.is_active
                            ? "border-amber-700 text-amber-300 hover:bg-amber-950"
                            : "border-emerald-700 text-emerald-300 hover:bg-emerald-950"
                        }`}
                      >
                        {rule.is_active ? "停用" : "启用"}
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteRule(rule).catch((err) => setError(err.message || "删除失败"))}
                        className="rounded-md border border-rose-700 px-3 py-2 text-sm text-rose-300 hover:bg-rose-950"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <h2 className="text-lg font-semibold">发送记录</h2>
            <p className="mt-1 text-sm text-slate-400">最近 50 条任务，按创建时间倒序。</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-4 py-3">用户</th>
                  <th className="px-4 py-3">规则</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">计划发送</th>
                  <th className="px-4 py-3">实际发送</th>
                  <th className="px-4 py-3">附件结果</th>
                  <th className="px-4 py-3">失败原因</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {jobsLoading ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={7}>
                      加载发送记录...
                    </td>
                  </tr>
                ) : jobs.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={7}>
                      暂无发送记录
                    </td>
                  </tr>
                ) : (
                  jobs.map((job) => (
                    <tr key={job.id} className="text-slate-200">
                      <td className="px-4 py-3 font-mono text-xs">{job.external_user_id}</td>
                      <td className="px-4 py-3">{job.rule_name}</td>
                      <td className="px-4 py-3">{statusLabels[job.status] || job.status}</td>
                      <td className="px-4 py-3">{fmtDate(job.send_at)}</td>
                      <td className="px-4 py-3">{fmtDate(job.sent_at)}</td>
                      <td className="px-4 py-3">
                        {job.delivery_count} 条
                        {job.failed_delivery_count > 0 ? ` / 失败 ${job.failed_delivery_count}` : ""}
                      </td>
                      <td className="max-w-xs truncate px-4 py-3 text-rose-200">{job.failure_reason || "-"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section ref={callHistorySectionRef} className="rounded-md border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <h2 className="text-lg font-semibold">视频接听列表</h2>
            <p className="mt-1 text-sm text-slate-400">
              只显示固定回复账号最近 20 条视频通话记录，成功和不成功都会展示，滚动到此处后自动加载，每 5 分钟自动刷新。
            </p>
          </div>
          {!callHistoryOpen ? (
            <div className="flex flex-wrap items-center gap-3 p-4">
              <p className="text-sm text-slate-500">向下滚动后将自动加载视频接听列表。</p>
              <button
                type="button"
                onClick={() => setCallHistoryOpen(true)}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
              >
                立即加载
              </button>
            </div>
          ) : null}
          {callError ? (
            <div className="mx-4 mt-4 rounded-md border border-amber-800 bg-amber-950/40 px-4 py-3 text-sm text-amber-200">
              {callError}
            </div>
          ) : null}
          {callHistoryOpen ? (
          <div className="flex flex-wrap items-end gap-3 p-4">
            <label className="block min-w-[220px] flex-1 text-sm text-slate-300">
              搜索
              <input
                value={callSearch}
                onChange={(event) => setCallSearch(event.target.value)}
                placeholder="昵称 / Telegram ID / 接听账号"
                className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-500"
              />
            </label>
            <button
              type="button"
              onClick={() => loadFixedCallHistory(callSearch)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              搜索
            </button>
            <button
              type="button"
              onClick={() => loadFixedCallHistory(callSearch)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            >
              刷新
            </button>
          </div>
          ) : null}
          {callHistoryOpen ? (
          <div className="overflow-x-auto px-4 pb-4">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950 text-slate-400">
                <tr>
                  <th className="px-4 py-3">用户</th>
                  <th className="px-4 py-3">用户 Telegram</th>
                  <th className="px-4 py-3">接听 TG 账号</th>
                  <th className="px-4 py-3">通话时间</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">第几次</th>
                  <th className="px-4 py-3">触发方式</th>
                  <th className="px-4 py-3">播放视频</th>
                  <th className="px-4 py-3">通话时长</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {callLoading ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={9}>
                      加载视频接听列表...
                    </td>
                  </tr>
                ) : callRecords.length === 0 ? (
                  <tr>
                    <td className="px-4 py-6 text-center text-slate-500" colSpan={9}>
                      暂无视频接听记录
                    </td>
                  </tr>
                ) : (
                  callRecords.map((record) => (
                    <tr key={record.job_id} className="text-slate-200 hover:bg-slate-950/60">
                      <td className="px-4 py-3">
                        {record.nickname || "未命名"}
                        {record.user_id ? (
                          <div className="text-xs text-slate-500">{record.user_id}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {record.external_id || "—"}
                        {record.chat_id ? (
                          <div className="text-xs text-slate-500">chat {record.chat_id}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {record.telegram_account_label || "—"}
                        {record.telegram_account_phone &&
                        record.telegram_account_phone !== record.telegram_account_label ? (
                          <div className="text-xs text-slate-500">{record.telegram_account_phone}</div>
                        ) : null}
                        {record.telegram_account_id ? (
                          <div className="text-xs text-slate-500">{record.telegram_account_id}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-slate-400">{fmtDate(record.call_at)}</td>
                      <td className={`px-4 py-3 font-semibold ${callStatusClassName(record.status)}`}>
                        {callStatusLabel(record.status)}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {record.inbound_call_number ? `第 ${record.inbound_call_number} 次` : "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {triggerSourceLabel(record.trigger_source)}
                      </td>
                      <td className="px-4 py-3 text-slate-400">{record.video_title || "—"}</td>
                      <td className="px-4 py-3 font-medium text-slate-200">
                        {callDurationLabel(record)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
              <span>共 {callTotal} 条固定回复视频接听记录，当前显示 {callRecords.length} 条</span>
              <span>每 5 分钟自动刷新</span>
            </div>
          </div>
          ) : null}
        </section>
      </div>
    </AdminFrame>
  );
}

export default function Page() {
  return (
    <AuthGate>
      {(operator) => <FixedRepliesPage operator={operator} />}
    </AuthGate>
  );
}
