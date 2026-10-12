"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";
import { formatBeijingDateTime } from "@/lib/reportTime";

type ReportRange = "today" | "yesterday" | "week" | "month" | "history";
type DistributionItem = { label: string; users: number };
type Summary = {
  total: number; profiles: number; chat_ids: number; access_hashes: number;
  source_accounts: number; phones: number; countries_known: number; countries_unknown: number;
  phone_country_fetched: number; ages: number; cities: number; user_messages: number;
  ai_replies: number; media_users: number; risk_users: number; devices_known: number;
};
type Report = {
  summary: Summary; countries: DistributionItem[]; country_sources: DistributionItem[]; devices: DistributionItem[];
  pending_steps: DistributionItem[]; channels: DistributionItem[]; generated_at_bj: string;
  intake_progress?: {
    country?: { asked?: number; replied?: number; waiting?: number };
    age?: { asked?: number; replied?: number; waiting?: number };
  };
};
type UserRow = Record<string, unknown> & { id: string; external_id: string; nickname?: string; country_code?: string; device_os?: string; chat_id?: string; access_hash?: string; created_at?: string; last_active_at?: string; user_message_count?: number; ai_message_count?: number; call_count?: number; peer_metadata?: Record<string, unknown> };
type UserListResponse = { total: number; items: UserRow[] };
type UserDetail = { user: Record<string, unknown>; conversations: Record<string, unknown>[]; messages: Record<string, unknown>[]; message_total: number; message_offset: number; links: Record<string, unknown>[]; attribution_events: Record<string, unknown>[]; calls: Record<string, unknown>[]; fixed_replies: Record<string, unknown>[]; reply_audit_gap: string };

const LIST_DISPLAY_LIMIT = 5;
const INCREMENTAL_PAGE_SIZE = 100;
const LIST_CACHE_PREFIX = "eris.user-collection.list.v1";
const DETAIL_CACHE_PREFIX = "eris.user-collection.detail.v1";

function listCacheKey(range: ReportRange) {
  return `${LIST_CACHE_PREFIX}.${range}`;
}

function detailCacheKey(userId: string) {
  return `${DETAIL_CACHE_PREFIX}.${userId}`;
}

function createdAtOf(row: UserRow): string {
  return String(row.created_at || "");
}

function mergeUserRows(cached: UserRow[], incoming: UserRow[]): UserRow[] {
  const map = new Map<string, UserRow>();
  for (const row of [...cached, ...incoming]) {
    if (row?.id) map.set(String(row.id), row);
  }
  return Array.from(map.values()).sort((a, b) => createdAtOf(b).localeCompare(createdAtOf(a)));
}

function newestCreatedAt(rows: UserRow[]): string {
  return rows.reduce((latest, row) => {
    const value = createdAtOf(row);
    return value && value > latest ? value : latest;
  }, "");
}

function readListCache(range: ReportRange): UserRow[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(listCacheKey(range));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { users?: UserRow[] };
    return Array.isArray(parsed.users) ? parsed.users : [];
  } catch {
    return [];
  }
}

function writeListCache(range: ReportRange, users: UserRow[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(listCacheKey(range), JSON.stringify({ users, updatedAt: new Date().toISOString() }));
}

function readDetailCache(userId: string): UserDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(detailCacheKey(userId));
    return raw ? JSON.parse(raw) as UserDetail : null;
  } catch {
    return null;
  }
}

function writeDetailCache(userId: string, detail: UserDetail) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(detailCacheKey(userId), JSON.stringify(detail));
}

const ranges: Array<[ReportRange, string]> = [
  ["today", "今天"], ["yesterday", "昨天"], ["week", "本周"],
  ["month", "本月"], ["history", "总计"],
];

const labels: Record<string, string> = {
  UNKNOWN: "未知", NONE: "无待收集项", country: "等待回答国家", age: "等待回答年龄",
  telegram_phone_country: "Telegram手机号国家", language_fallback: "聊天语言/内容推断",
  chat_answer: "用户回答", telegram_language_code: "Telegram语言", telegram_real_user: "Telegram真实用户",
  AI_ACTIVE: "AI接待中", HUMAN_ACTIVE: "人工接待中", PENDING: "待处理",
  click: "点击", link_exposed: "链接曝光", download_page: "打开下载页", download: "下载",
  app_register: "App注册", payment: "付费",
  user: "用户", assistant: "AI", operator: "人工",
  completed: "已完成", cancelled: "已取消", failed: "失败", queued: "排队中",
  inbound_call: "用户来电", inbound_operator_review: "人工审核来电",
  early_link_mandate: "开场强制发链接", app_download_first_push: "首次下载引导",
  platform_a: "平台A", platform_b: "平台B", platform_c: "平台C",
  onboarding_step: "引导步骤", nurture_language: "培育语言",
  age_source: "年龄来源", country_source: "国家来源", stated_country_code: "用户声明国家",
  telegram_phone_country_fetched: "手机号国家已查询", current_city: "城市",
  source: "来源", trace_id: "追踪ID", message_id: "消息ID", campaign_id: "活动ID",
  "script hit id": "话术命中ID", script_hit_id: "话术命中ID",
  mtproto_auto_reply: "MTProto自动回复",
};

const T1_COUNTRIES = new Set([
  "US", "CA", "GB", "DE", "FR", "IT", "ES", "NL", "BE", "CH", "AT", "IE", "DK",
  "NO", "SE", "FI", "IS", "LU", "PT", "GR", "CZ", "JP", "AU", "NZ", "SG", "HK",
]);
const T2_COUNTRIES = new Set([
  "AD", "AR", "BG", "BH", "BR", "BY", "CL", "CO", "CR", "CY", "DO", "EC", "EE", "FJ",
  "GT", "HR", "HU", "ID", "IL", "KW", "KZ", "LB", "LT", "LV", "MO", "MT", "MX", "MY",
  "NC", "OM", "PA", "PE", "PF", "PH", "PL", "RO", "RS", "RU", "SA", "SI", "SK", "TH",
  "TR", "TW", "UA", "UY", "VN", "ZA",
]);
const regionNames = new Intl.DisplayNames(["zh-CN"], { type: "region" });
const PREFERENCE_SKIP = new Set([
  "age", "age_source", "country_source", "stated_country_code",
  "telegram_phone_country", "telegram_phone_country_fetched", "current_city",
]);

function countryLabel(code: string) {
  if (!code || code === "UNKNOWN") return "未知";
  const tier = T1_COUNTRIES.has(code) ? "T1" : T2_COUNTRIES.has(code) ? "T2" : "T3";
  return `${tier}-${code}-${regionNames.of(code) || code}`;
}

function pct(value: number, total: number) {
  return total ? `${(value / total * 100).toFixed(1)}%` : "0.0%";
}

function isIsoTime(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value);
}

function named(value: unknown): string {
  const key = String(value ?? "");
  return labels[key] || key;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未收集";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (isIsoTime(value)) return formatBeijingDateTime(value);
  if (Array.isArray(value)) return value.length ? value.map((item) => valueText(item)).join("、") : "未收集";
  if (typeof value === "object") return objectSummary(value as Record<string, unknown>);
  return named(value);
}

function objectSummary(value: Record<string, unknown>): string {
  const parts = Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && item !== "")
    .map(([key, item]) => `${named(key)}：${typeof item === "object" ? JSON.stringify(item) : valueText(item)}`);
  return parts.length ? parts.join("；") : "未收集";
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function preferenceRows(prefs: Record<string, unknown> | undefined): Array<[string, unknown]> {
  if (!prefs) return [["偏好", null]];
  const rows = Object.entries(prefs)
    .filter(([key]) => !PREFERENCE_SKIP.has(key))
    .map(([key, value]) => [named(key), value] as [string, unknown]);
  return rows.length ? rows : [["偏好", "无额外偏好"]];
}

function pick(item: Record<string, unknown>, keys: Array<[string, string]>): Array<[string, unknown]> {
  return keys
    .map(([label, key]) => [label, item[key]] as [string, unknown])
    .filter(([, value]) => value !== null && value !== undefined && value !== "");
}

function Metric({ title, value, total, tone = "sky" }: { title: string; value: number; total: number; tone?: string }) {
  const color = tone === "amber" ? "text-amber-300" : tone === "emerald" ? "text-emerald-300" : tone === "rose" ? "text-rose-300" : "text-sky-300";
  return <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
    <div className="text-xs text-slate-500">{title}</div>
    <div className={`mt-2 text-2xl font-semibold ${color}`}>{value.toLocaleString()}</div>
    <div className="mt-1 text-xs text-slate-500">{pct(value, total)}</div>
  </div>;
}

function IntakeProgress({
  title,
  progress,
  total,
}: {
  title: string;
  progress?: { asked?: number; replied?: number; waiting?: number };
  total: number;
}) {
  const asked = Number(progress?.asked || 0);
  const replied = Number(progress?.replied || 0);
  const waiting = Number(progress?.waiting || 0);
  const rows = [
    { label: "已提问", users: asked, base: total, hint: "该周期新用户中问过的人数" },
    { label: "已回复", users: replied, base: asked, hint: "问过后已经给出答案的人数" },
    { label: "等待回复", users: waiting, base: asked, hint: "已经提问、还在等对方回答" },
  ];
  const max = Math.max(1, asked, replied, waiting);
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="mb-4 text-base font-semibold text-slate-100">{title}</h2>
      <div className="space-y-3">
        {rows.map((item) => (
          <div key={item.label}>
            <div className="mb-1 flex items-center justify-between gap-3 text-sm">
              <span className="truncate text-slate-300">{item.label}</span>
              <span className="shrink-0 text-slate-100">
                {item.users.toLocaleString()} 人{" "}
                <small className="text-slate-500">{pct(item.users, item.base)}</small>
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
              <div className="h-full rounded-full bg-cyan-500" style={{ width: `${(item.users / max) * 100}%` }} />
            </div>
            <div className="mt-1 text-[11px] text-slate-500">{item.hint}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Distribution({ title, items, total, formatLabel }: { title: string; items: DistributionItem[]; total: number; formatLabel?: (label: string) => string }) {
  const max = Math.max(1, ...items.map((item) => item.users));
  return <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
    <h2 className="mb-4 text-base font-semibold text-slate-100">{title}</h2>
    <div className="space-y-3">
      {items.map((item) => <div key={item.label}>
        <div className="mb-1 flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-slate-300">{formatLabel ? formatLabel(item.label) : (labels[item.label] || item.label)}</span>
          <span className="shrink-0 text-slate-100">{item.users.toLocaleString()} 人 <small className="text-slate-500">{pct(item.users, total)}</small></span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-500" style={{ width: `${item.users / max * 100}%` }} /></div>
      </div>)}
      {!items.length && <div className="text-sm text-slate-500">暂无数据</div>}
    </div>
  </section>;
}

function Fields({ values }: { values: Array<[string, unknown]> }) {
  return <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{values.map(([label, value]) => <div key={label} className="rounded-lg border border-slate-800 bg-slate-950/70 p-3"><div className="text-[11px] text-slate-500">{label}</div><div className={`mt-1 break-all text-sm ${value === null || value === undefined || value === "" ? "text-amber-400" : "text-slate-200"}`}>{valueText(value)}</div></div>)}</div>;
}

function RecordCard({ rows }: { rows: Array<[string, unknown]> }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <dl className="grid gap-2 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[11px] text-slate-500">{label}</dt>
            <dd className="mt-0.5 break-all text-sm text-slate-200">{valueText(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function conversationRows(item: Record<string, unknown>): Array<[string, unknown]> {
  const videoSent = [
    item.post_video_fixed_01_sent_at,
    item.post_video_fixed_02_sent_at,
    item.post_video_fixed_03_last_sent_at,
  ].some(Boolean);
  return [
    ...pick(item, [
      ["会话ID", "id"],
      ["状态", "state"],
      ["渠道", "channel"],
      ["创建时间", "created_at"],
      ["最近消息", "last_message_at"],
      ["AI模型", "ai_model_used"],
      ["接管运营", "assigned_operator_id"],
    ]),
    ["视频后固定话术", videoSent ? "已发送" : "未发送"],
    ...pick(item, [
      ["话术01时间", "post_video_fixed_01_sent_at"],
      ["话术02时间", "post_video_fixed_02_sent_at"],
      ["话术03时间", "post_video_fixed_03_last_sent_at"],
      ["话术03停止原因", "post_video_fixed_03_stop_reason"],
    ]),
  ];
}

function linkRows(item: Record<string, unknown>): Array<[string, unknown]> {
  return pick(item, [
    ["短链ID", "tracking_id"],
    ["目标链接", "destination_url"],
    ["平台", "platform"],
    ["场景", "scene_step"],
    ["话术分类", "script_category"],
    ["意图", "intent"],
    ["发送账号", "sender_account_id"],
    ["国家", "country_code"],
    ["T1国家", "is_t1_country"],
    ["发送时间", "sent_at"],
  ]);
}

function eventRows(item: Record<string, unknown>): Array<[string, unknown]> {
  const metadata = asRecord(item.metadata) || {};
  return [
    ...pick(item, [
      ["事件", "event_type"],
      ["短链ID", "tracking_id"],
      ["发生时间", "created_at"],
      ["国家", "country_code"],
      ["设备", "device_os"],
    ]),
    ...Object.entries(metadata)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => [named(key), value] as [string, unknown]),
  ];
}

function callRows(item: Record<string, unknown>): Array<[string, unknown]> {
  return pick(item, [
    ["任务ID", "id"],
    ["触发来源", "trigger_source"],
    ["状态", "status"],
    ["开始时间", "started_at"],
    ["结束时间", "ended_at"],
    ["失败原因", "failure_reason"],
    ["规则", "rule_key"],
    ["创建时间", "created_at"],
  ]);
}

function replyRows(item: Record<string, unknown>): Array<[string, unknown]> {
  return pick(item, [
    ["规则", "rule_name"],
    ["内容", "text_content"],
    ["状态", "status"],
    ["计划发送", "send_at"],
    ["实际发送", "sent_at"],
    ["失败原因", "failure_reason"],
    ["尝试次数", "send_attempts"],
    ["创建时间", "created_at"],
  ]);
}

function Records({ title, items, rowsFor }: { title: string; items: Record<string, unknown>[]; rowsFor: (item: Record<string, unknown>) => Array<[string, unknown]> }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <h3 className="mb-3 font-medium text-slate-100">{title} <span className="text-xs text-slate-500">{items.length} 条</span></h3>
      <div className="max-h-[420px] space-y-2 overflow-y-auto">
        {items.map((item, index) => <RecordCard key={String(item.id || item.tracking_id || index)} rows={rowsFor(item)} />)}
        {!items.length && <div className="text-sm text-slate-600">暂无记录</div>}
      </div>
    </section>
  );
}

function MessageThread({ items }: { items: Record<string, unknown>[] }) {
  const ordered = useMemo(
    () => [...items].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""))),
    [items],
  );
  if (!ordered.length) return <div className="text-sm text-slate-600">暂无聊天</div>;
  return (
    <div className="max-h-[520px] space-y-3 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      {ordered.map((item) => {
        const fromUser = item.sender_type === "user";
        return (
          <div key={String(item.id)} className={`flex ${fromUser ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] rounded-2xl px-3 py-2 ${fromUser ? "bg-cyan-700 text-white" : "bg-slate-800 text-slate-100"}`}>
              <div className="whitespace-pre-wrap break-words text-sm leading-6">{String(item.content || "")}</div>
              <div className={`mt-1 text-[11px] ${fromUser ? "text-cyan-100/80" : "text-slate-400"}`}>
                {named(item.sender_type)} · {valueText(item.created_at)}
                {item.model_name ? ` · ${String(item.model_name)}` : ""}
                {item.is_operator_message ? " · 人工消息" : ""}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function UserCollectionContent({ operator }: { operator: Operator }) {
  const [range, setRange] = useState<ReportRange>("today");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [cachedCount, setCachedCount] = useState(0);
  const [newCount, setNewCount] = useState(0);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("ALL");
  const [searching, setSearching] = useState(false);
  const [searchHitTotal, setSearchHitTotal] = useState(0);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setReport(await apiFetch<Report>(`/admin/user-report/collection?range=${range}`, { retries: 1 })); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  }, [range]);
  useEffect(() => { void load(); }, [load]);
  const loadUsers = useCallback(async () => {
    const query = appliedSearch.trim();
    if (query || deviceFilter !== "ALL") {
      setSearching(true);
      try {
        const collected: UserRow[] = [];
        let page = 1;
        let total = 0;
        do {
          const qs = new URLSearchParams({
            range,
            page: String(page),
            page_size: String(INCREMENTAL_PAGE_SIZE),
            search: query,
            device_os: deviceFilter,
          });
          const data = await apiFetch<UserListResponse>(`/admin/user-report/collection-users?${qs}`, { retries: 1 });
          collected.push(...(data.items || []));
          total = data.total || 0;
          page += 1;
        } while (collected.length < total && page <= 50);
        setUsers(mergeUserRows([], collected));
        setSearchHitTotal(total);
        setCachedCount(0);
        setNewCount(collected.length);
      } finally {
        setSearching(false);
      }
      return;
    }
    const cached = readListCache(range);
    const qs = new URLSearchParams({
      range,
      page: "1",
      page_size: String(LIST_DISPLAY_LIMIT),
    });
    const data = await apiFetch<UserListResponse>(`/admin/user-report/collection-users?${qs}`, { retries: 1 });
    const incoming = data.items || [];
    const merged = mergeUserRows(cached, incoming);
    writeListCache(range, merged);
    setUsers(merged.slice(0, LIST_DISPLAY_LIMIT));
    setSearchHitTotal(0);
    setCachedCount(merged.length);
    setNewCount(incoming.length);
  }, [range, appliedSearch, deviceFilter]);
  useEffect(() => {
    if (appliedSearch.trim()) return;
    const cached = readListCache(range);
    setUsers(cached.slice(0, LIST_DISPLAY_LIMIT));
    setCachedCount(cached.length);
  }, [range, appliedSearch]);
  useEffect(() => { void loadUsers(); }, [loadUsers]);
  useEffect(() => {
    const timer = window.setInterval(() => { void load(); void loadUsers(); }, 30000);
    return () => window.clearInterval(timer);
  }, [load, loadUsers]);
  function submitSearch(event?: { preventDefault?: () => void }) {
    event?.preventDefault?.();
    setAppliedSearch(search.trim());
  }
  function clearSearch() {
    setSearch("");
    setAppliedSearch("");
  }
  async function refreshAll() {
    await Promise.all([load(), loadUsers()]);
  }
  async function openUser(userId: string, messageOffset = 0, append = false) {
    if (!append && messageOffset === 0) {
      const cached = readDetailCache(userId);
      if (cached) {
        setDetail(cached);
        return;
      }
    }
    setDetailLoading(true);
    try {
      const data = await apiFetch<UserDetail>(`/admin/user-report/collection-users/${userId}?message_offset=${messageOffset}&message_limit=100`, { retries: 1 });
      setDetail((current) => {
        const next = append && current ? { ...data, messages: [...current.messages, ...data.messages] } : data;
        writeDetailCache(userId, next);
        return next;
      });
    } finally { setDetailLoading(false); }
  }
  const s = report?.summary;
  const cards = useMemo(() => s ? [
    ["用户画像", s.profiles, "emerald"], ["chat_id", s.chat_ids, "sky"], ["access_hash", s.access_hashes, "sky"],
    ["来源TG账号", s.source_accounts, "sky"], ["国家已识别", s.countries_known, "emerald"], ["国家未知", s.countries_unknown, "amber"],
    ["手机号已收集", s.phones, "emerald"],
    ["手机号国家已查询", s.phone_country_fetched, "sky"], ["年龄已收集", s.ages, "emerald"], ["城市已收集", s.cities, "emerald"],
    ["用户已发消息", s.user_messages, "sky"], ["已有AI回复", s.ai_replies, "emerald"], ["发过媒体", s.media_users, "sky"],
    ["风险用户", s.risk_users, "rose"], ["设备已识别", s.devices_known, "emerald"],
  ] as Array<[string, number, string]> : [], [s]);
  const prefs = asRecord(detail?.user.preferences);
  return <AdminFrame operator={operator} active="user-collection" title="用户收集数据" subtitle="按北京时间查看新用户身份凭据、国家画像、消息与AI回复信息的收集完整度。">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap gap-2">{ranges.map(([key, text]) => <button key={key} onClick={() => setRange(key)} className={`rounded-lg px-4 py-2 text-sm ${range === key ? "bg-cyan-600 font-medium text-white" : "border border-slate-700 text-slate-400 hover:bg-slate-800"}`}>{text}</button>)}</div>
      <div className="flex items-center gap-3"><span className="text-xs text-slate-500">{report ? `更新于 ${report.generated_at_bj}` : ""}</span><button onClick={() => void refreshAll()} disabled={loading} className="rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-300 disabled:opacity-50">{loading ? "读取中" : "立即刷新"}</button></div>
    </div>
    {error && <div className="mb-5 rounded-xl border border-rose-800 bg-rose-950/40 p-4 text-rose-200">{error}</div>}
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-5 flex items-end justify-between"><div><div className="text-sm text-slate-500">该周期新增用户</div><div className="mt-1 text-4xl font-semibold text-white">{(s?.total || 0).toLocaleString()}</div></div><div className="text-xs text-slate-500">信息完整度按用户去重统计</div></div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">{cards.map(([title, value, tone]) => <Metric key={title} title={title} value={value} total={s?.total || 0} tone={tone} />)}</div>
    </section>
    <div className="mt-5 grid gap-5 lg:grid-cols-2"><Distribution title="设备分布" items={report?.devices || []} total={s?.total || 0} /><Distribution title="国家分布" items={report?.countries || []} total={s?.total || 0} formatLabel={countryLabel} /><Distribution title="国家识别来源" items={report?.country_sources || []} total={s?.total || 0} /><IntakeProgress title="国家提问进度" progress={report?.intake_progress?.country} total={s?.total || 0} /><IntakeProgress title="年龄提问进度" progress={report?.intake_progress?.age} total={s?.total || 0} /><Distribution title="用户来源渠道" items={report?.channels || []} total={s?.total || 0} /></div>
    <section className="mt-5 rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">用户收集明细</h2>
          <p className="mt-1 text-xs text-slate-500">
            {appliedSearch
              ? `正在搜索系统全部用户，找到 ${searchHitTotal.toLocaleString()} 人。`
              : `未搜索时只展示最新 ${LIST_DISPLAY_LIMIT} 条。本机已缓存 ${cachedCount.toLocaleString()} 人，本次新拉取 ${newCount.toLocaleString()} 人。`}
          </p>
        </div>
        <form onSubmit={submitSearch} className="flex min-w-[320px] flex-1 flex-col items-end gap-2">
          <div className="flex w-full max-w-xl gap-2">
            <select value={deviceFilter} onChange={(e) => setDeviceFilter(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="ALL">全部设备</option><option value="Android">Android</option><option value="iOS">iOS</option><option value="Desktop">桌面设备</option><option value="Unknown">未知设备</option></select>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索系统全部用户：昵称 / username / chat_id"
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
            <button type="submit" disabled={searching} className="rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-300 disabled:opacity-50">
              {searching ? "搜索中" : "搜索"}
            </button>
            {appliedSearch ? (
              <button type="button" onClick={clearSearch} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">
                清除
              </button>
            ) : null}
          </div>
        </form>
      </div>
      <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-950 text-slate-500"><tr><th className="px-3 py-3">用户</th><th className="px-3 py-3">Telegram身份</th><th className="px-3 py-3">国家/画像</th><th className="px-3 py-3">设备</th><th className="px-3 py-3">消息</th><th className="px-3 py-3">时间</th><th className="px-3 py-3"></th></tr></thead><tbody className="divide-y divide-slate-800">{users.map((u) => <tr key={u.id}><td className="px-3 py-3"><div className="text-slate-100">{String(u.nickname || u.external_id)}</div><div className="text-xs text-slate-500">{u.external_id}</div></td><td className="px-3 py-3 text-xs"><div>chat_id: {valueText(u.chat_id)}</div><div>@{String(u.peer_metadata?.username || "未收集")}</div><div>手机: {String(u.peer_metadata?.phone || "未收集")}</div><div className={u.access_hash ? "text-emerald-400" : "text-amber-400"}>access_hash: {u.access_hash ? "已保存" : "未保存"}</div></td><td className="px-3 py-3">{countryLabel(String(u.country_code || "UNKNOWN"))}<div className="text-xs text-slate-500">{String(u.user_level || "-")} / {String(u.chat_route || "-")}</div></td><td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-xs ${u.device_os === "iOS" ? "bg-sky-950 text-sky-300" : u.device_os === "Android" ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-slate-400"}`}>{String(u.device_os || "Unknown")}</span></td><td className="px-3 py-3 text-xs">用户 {Number(u.user_message_count || 0)} / AI {Number(u.ai_message_count || 0)}<div>视频 {Number(u.call_count || 0)}</div></td><td className="px-3 py-3 text-xs text-slate-500"><div>进入 {valueText(u.created_at)}</div><div>活跃 {valueText(u.last_active_at)}</div></td><td className="px-3 py-3"><button onClick={() => void openUser(u.id)} className="rounded-lg bg-cyan-700 px-3 py-2 text-xs text-white">查看全部</button></td></tr>)}</tbody></table></div>
      {!users.length && <div className="mt-4 text-center text-sm text-slate-500">暂无用户</div>}
    </section>
    {detail && <section className="mt-5 rounded-2xl border border-cyan-900 bg-slate-900 p-5"><div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-semibold">{valueText(detail.user.nickname || detail.user.external_id)} 的完整收集资料</h2><p className="text-xs text-slate-500">用户ID：{valueText(detail.user.id)}</p></div><button onClick={() => setDetail(null)} className="rounded border border-slate-700 px-3 py-2 text-sm">关闭</button></div>
      <div className="space-y-5">
        <section><h3 className="mb-3 font-medium text-cyan-300">1. Telegram身份信息</h3><Fields values={[["chat_id",detail.user.chat_id],["access_hash",detail.user.access_hash],["可见手机号",(detail.user.peer_metadata as Record<string,unknown> | undefined)?.phone],["@username",(detail.user.peer_metadata as Record<string,unknown> | undefined)?.username],["昵称",detail.user.nickname],["Telegram用户ID",detail.user.external_id],["source_account_id",detail.user.source_account_id],["接收消息TG账号",detail.user.receiving_account_name],["接收账号username",detail.user.receiving_account_username],["凭据获取时间",(detail.user.peer_metadata as Record<string,unknown> | undefined)?.captured_at],["凭据验证时间",detail.user.credential_verified_at]]} /></section>
        <section>
          <h3 className="mb-3 font-medium text-cyan-300">2. 用户来源信息</h3>
          <Fields values={[["来源渠道",detail.user.channel],["首次进入",detail.user.created_at],["最近活跃",detail.user.updated_at],["归属TG账号",detail.user.source_account_id],["语言",detail.user.language],["时区",detail.user.timezone]]} />
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <Records title="会话记录" items={detail.conversations} rowsFor={conversationRows} />
            <Records title="链接发送记录" items={detail.links} rowsFor={linkRows} />
            <Records title="点击与归因记录" items={detail.attribution_events} rowsFor={eventRows} />
          </div>
        </section>
        <section><h3 className="mb-3 font-medium text-cyan-300">3. 国家、语言与设备信息</h3><Fields values={[["国家",countryLabel(String(detail.user.country_code||"UNKNOWN"))],["国家来源",prefs?.country_source],["用户声明国家",prefs?.stated_country_code],["Telegram手机号国家",prefs?.telegram_phone_country],["手机号国家查询完成",prefs?.telegram_phone_country_fetched],["语言",detail.user.language],["城市",prefs?.current_city],["设备系统",detail.user.device_os],["首次识别设备",detail.user.device_first_detected_at],["最近识别设备",detail.user.device_last_detected_at]]} /></section>
        <section>
          <h3 className="mb-3 font-medium text-cyan-300">4. 用户画像信息</h3>
          <Fields values={[
            ["年龄", prefs?.age],
            ["年龄来源", prefs?.age_source],
            ["兴趣", detail.user.interests],
            ...preferenceRows(prefs),
            ["聊天风格", detail.user.chat_style],
            ["关系阶段", detail.user.relationship_stage],
            ["用户等级", detail.user.user_level],
            ["聊天路由", detail.user.chat_route],
            ["VIP等级", detail.user.vip_level],
            ["孤独评分", detail.user.loneliness_score],
            ["情绪评分", detail.user.emotion_score],
            ["留存评分", detail.user.retention_score],
            ["依赖评分", detail.user.dependency_score],
            ["风险等级", detail.user.risk_level],
            ["疑似未成年", detail.user.is_minor_suspected],
            ["允许营销", !detail.user.opt_out_marketing],
            ["允许通知", detail.user.notification_opt_in],
          ]} />
        </section>
        <section>
          <h3 className="mb-3 font-medium text-cyan-300">5. 聊天与媒体记录</h3>
          <div className="mb-2 rounded-lg border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-200">{detail.reply_audit_gap}</div>
          <div className="mb-2 text-sm text-slate-400">全部聊天（已加载 {detail.messages.length}/{detail.message_total}）</div>
          <MessageThread items={detail.messages} />
          {detail.messages.length<detail.message_total && <button disabled={detailLoading} onClick={() => void openUser(String(detail.user.id), detail.messages.length, true)} className="mt-3 rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-300">继续加载100条</button>}
        </section>
        <section><h3 className="mb-3 font-medium text-cyan-300">6. 视频通话与固定话术</h3><div className="grid gap-3 lg:grid-cols-2"><Records title="视频通话任务" items={detail.calls} rowsFor={callRows} /><Records title="固定回复任务" items={detail.fixed_replies} rowsFor={replyRows} /></div></section>
      </div>
    </section>}
  </AdminFrame>;
}

export default function UserCollectionPage() {
  return <AuthGate>{(operator) => <UserCollectionContent operator={operator} />}</AuthGate>;
}
