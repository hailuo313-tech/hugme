"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import OperatorWsStatus from "@/components/OperatorWsStatus";
import { apiFetch, Operator } from "@/lib/auth";
import { useOperatorTaskWs } from "@/hooks/useOperatorTaskWs";
import { levelBadgeClass, vipToLevelTier, type LevelTier } from "@/lib/priorityDisplay";

type QueueTab = "all" | "handoff" | "premium" | "auto" | "risk";

interface ConversationRow {
  conversation_id: string;
  state: string | null;
  handoff_count: number | null;
  channel: string | null;
  last_message_at: string | null;
  created_at: string | null;
  assigned_operator_id: string | null;
  user_id: string | null;
  nickname: string | null;
  external_id: string | null;
  user_channel: string | null;
  risk_level: string | null;
  user_status: string | null;
  loneliness_score: number | null;
  vip_level: number | null;
  relationship_stage: string | null;
  character_id: string | null;
  character_name: string | null;
}

interface MessageRow {
  id: string;
  sender_type: string | null;
  content: string | null;
  content_type: string | null;
  is_operator_message: boolean | null;
  model_name: string | null;
  safety_result: unknown;
  created_at: string | null;
}

interface ListResponse {
  items: ConversationRow[];
  total: number;
  page: number;
  page_size: number;
}

interface DetailResponse {
  conversation: ConversationRow & {
    ai_model_used?: string | null;
    language?: string | null;
    timezone?: string | null;
    chat_style?: string | null;
  };
  messages: MessageRow[];
}

interface ScriptSuggestion {
  id?: string;
  content: string;
  match_score?: number;
  script_type?: string;
}

interface ScriptTraceHit {
  hook?: string;
  script_hit_id?: string;
  matched?: boolean;
  degradation?: string | null;
  user_level?: string | null;
  platform?: string | null;
  created_at?: string | null;
}

interface ScriptTraceResponse {
  eligible?: boolean;
  reason?: string | null;
  script_hits?: ScriptTraceHit[];
}

interface OpsAiReply {
  rank: number;
  text: string;
  reason: string;
}

interface OpsAiAssistResponse {
  summary: {
    user_state: string;
    key_facts: string[];
    risk_flags: string[];
    recommended_strategy: string;
  };
  suggested_replies: OpsAiReply[];
  model_used?: string | null;
  latency_ms?: number | null;
}

const PAGE_SIZE = 50;
const CONVERSATION_LIST_API_MARKER = "/admin/conversations?";
const SCRIPT_HOOKS = ["入站", "消费", "探测", "分级", "回复", "坐席", "出站", "归档"];
const LEVELS: LevelTier[] = ["S", "A", "B", "C", "D"];

const STATE_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "WAITING_OPERATOR", label: "待人工接管" },
  { value: "HUMAN_LOCKED", label: "人工处理中" },
  { value: "AI_ACTIVE", label: "AI 自动跟进" },
  { value: "CLOSED", label: "已关闭" },
];

const CHANNEL_OPTIONS = [
  { value: "", label: "全部渠道" },
  { value: "telegram", label: "Telegram" },
  { value: "telegram_real_user", label: "TG 真人号" },
  { value: "web", label: "H5" },
  { value: "app", label: "App" },
  { value: "whatsapp", label: "WhatsApp" },
];

function fmtTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortText(value: string | null | undefined, max = 56): string {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function levelOf(row: ConversationRow): LevelTier {
  return vipToLevelTier(row.vip_level ?? 0);
}

function isPremium(row: ConversationRow): boolean {
  return levelOf(row) === "S" || levelOf(row) === "A";
}

function isWaiting(row: ConversationRow): boolean {
  return row.state === "WAITING_OPERATOR" || row.state === "HUMAN_LOCKED";
}

function isRisk(row: ConversationRow): boolean {
  return row.risk_level === "critical" || row.risk_level === "high" || row.risk_level === "elevated";
}

function stateLabel(state: string | null): string {
  switch (state) {
    case "WAITING_OPERATOR":
      return "待接管";
    case "HUMAN_LOCKED":
      return "人工中";
    case "AI_ACTIVE":
      return "AI跟进";
    case "CLOSED":
      return "已关闭";
    default:
      return state || "-";
  }
}

function stateClass(state: string | null): string {
  switch (state) {
    case "WAITING_OPERATOR":
      return "border-amber-600/70 bg-amber-500/10 text-amber-200";
    case "HUMAN_LOCKED":
      return "border-violet-600/70 bg-violet-500/10 text-violet-200";
    case "AI_ACTIVE":
      return "border-emerald-600/70 bg-emerald-500/10 text-emerald-200";
    default:
      return "border-slate-700 bg-slate-800 text-slate-300";
  }
}

function riskClass(risk: string | null): string {
  if (risk === "critical" || risk === "high") return "text-rose-300";
  if (risk === "elevated") return "text-amber-300";
  return "text-slate-400";
}

function routeLabel(row: ConversationRow): string {
  const level = levelOf(row);
  if (level === "S") return "专家精聊";
  if (level === "A") return "重点转化";
  if (level === "B") return "AI+坐席辅助";
  if (level === "C") return "AI自动";
  return "探测补全";
}

function sortQueue(items: ConversationRow[]): ConversationRow[] {
  const levelScore: Record<LevelTier, number> = { S: 0, A: 1, B: 2, C: 3, D: 4 };
  const stateScore: Record<string, number> = { WAITING_OPERATOR: 0, HUMAN_LOCKED: 1, AI_ACTIVE: 2, CLOSED: 3 };
  return [...items].sort((a, b) => {
    const levelDiff = levelScore[levelOf(a)] - levelScore[levelOf(b)];
    if (levelDiff !== 0) return levelDiff;
    const stateDiff = (stateScore[a.state || ""] ?? 9) - (stateScore[b.state || ""] ?? 9);
    if (stateDiff !== 0) return stateDiff;
    return new Date(b.last_message_at || b.created_at || 0).getTime() - new Date(a.last_message_at || a.created_at || 0).getTime();
  });
}

function ConversationsContent({ operator }: { operator: Operator }) {
  const [items, setItems] = useState<ConversationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<QueueTab>("all");
  const [state, setState] = useState("");
  const [channel, setChannel] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ScriptSuggestion[]>([]);
  const [trace, setTrace] = useState<ScriptTraceResponse | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [assist, setAssist] = useState<OpsAiAssistResponse | null>(null);
  const [assistLoading, setAssistLoading] = useState(false);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      if (state) qs.set("state", state);
      if (channel) qs.set("channel", channel);
      if (appliedSearch.trim()) qs.set("search", appliedSearch.trim());
      const response = await apiFetch<ListResponse>(
        `${CONVERSATION_LIST_API_MARKER}${qs.toString()}`,
      );
      setItems(sortQueue(response.items || []));
      setTotal(response.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, channel, state]);

  useEffect(() => {
    void load();
  }, [load]);

  const { connState, lastAlert, dismissAlert, reconnect } = useOperatorTaskWs({
    operatorId: operator.operator_id,
    onTaskUpsert: () => void load(),
    onUserUpgraded: () => void load(),
  });

  const stats = useMemo(() => {
    const levels = items.reduce<Record<string, number>>((acc, item) => {
      const level = levelOf(item);
      acc[level] = (acc[level] || 0) + 1;
      return acc;
    }, {});
    return {
      waiting: items.filter(isWaiting).length,
      premium: items.filter(isPremium).length,
      aiActive: items.filter((item) => item.state === "AI_ACTIVE").length,
      risk: items.filter(isRisk).length,
      levels,
    };
  }, [items]);

  const visibleItems = useMemo(() => {
    if (tab === "handoff") return items.filter(isWaiting);
    if (tab === "premium") return items.filter(isPremium);
    if (tab === "auto") return items.filter((item) => item.state === "AI_ACTIVE");
    if (tab === "risk") return items.filter(isRisk);
    return items;
  }, [items, tab]);

  async function openDetail(conversationId: string) {
    setDetail(null);
    setDetailError(null);
    setSuggestions([]);
    setTrace(null);
    setTraceError(null);
    setAssist(null);
    setDraft("");
    setDetailLoading(true);
    try {
      const response = await apiFetch<DetailResponse>(`/admin/conversations/${conversationId}`);
      setDetail(response);
      void loadSuggestions(response.conversation);
      if (isPremium(response.conversation)) {
        void loadTrace(conversationId);
      }
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadSuggestions(conversation: DetailResponse["conversation"]) {
    try {
      const response = await apiFetch<{ items: ScriptSuggestion[] }>("/scripts/suggest", {
        method: "POST",
        body: JSON.stringify({
          language: conversation.language || "en",
          loneliness_score: conversation.loneliness_score ?? 50,
          risk_level: conversation.risk_level || "low",
          character_id: conversation.character_id || undefined,
          relationship_stage: conversation.relationship_stage || undefined,
          limit: 3,
        }),
      });
      setSuggestions(response.items || []);
    } catch {
      setSuggestions([]);
    }
  }

  async function loadTrace(conversationId: string) {
    try {
      const response = await apiFetch<ScriptTraceResponse>(`/archive/premium-chat/${conversationId}/trace`);
      setTrace(response);
      setTraceError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("user_level_not_s_or_a")) {
        setTrace(null);
        setTraceError(null);
        return;
      }
      setTraceError(message);
    }
  }

  async function generateAssist() {
    if (!detail) return;
    setAssistLoading(true);
    try {
      const response = await apiFetch<OpsAiAssistResponse>(
        `/ops-ai/conversations/${detail.conversation.conversation_id}/assist`,
        {
          method: "POST",
          body: JSON.stringify({
            language: detail.conversation.language || "zh-CN",
            tone: "warm",
            max_context_messages: 30,
          }),
        },
      );
      setAssist(response);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setAssistLoading(false);
    }
  }

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    setAppliedSearch(search);
  }

  function resetFilters() {
    setSearch("");
    setAppliedSearch("");
    setState("");
    setChannel("");
    setTab("all");
  }

  return (
    <AdminFrame
      operator={operator}
      active="conversations"
      title="会话流控"
      subtitle="会话总览已升级为业务工作台：按入站、分级、话术命中、S/A 接管、出站归档和链接转化处理。"
    >
      <section className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <OperatorWsStatus connState={connState} lastAlert={lastAlert} onDismissAlert={dismissAlert} onReconnect={reconnect} />
        <div className="flex flex-wrap gap-2">
          <a href="/admin" className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            总后台
          </a>
          <a href="/admin/telegram-accounts" className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500">
            接入TG账号
          </a>
          <a href="/admin/ai-ops" className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500">
            维护AI话术
          </a>
          <a href="/admin/data" className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            数据总览
          </a>
          <a href="/admin/approvals" className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            运营审批
          </a>
          <a href="/admin/delivery" className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            推送监控
          </a>
        </div>
      </section>

      <section className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric title="待人工接管" value={stats.waiting} hint="S/A 挂起、超时、待坐席处理" tone="amber" />
        <Metric title="S/A 精聊用户" value={stats.premium} hint="高价值用户优先处理" tone="violet" />
        <Metric title="AI 自动跟进" value={stats.aiActive} hint="B/C/D 自动投递链路" tone="emerald" />
        <Metric title="风险会话" value={stats.risk} hint="高风险或升高风险复核" tone="rose" />
      </section>

      <section className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr_0.8fr]">
        <Panel title="业务链路状态">
          <div className="grid grid-cols-4 gap-2">
            {SCRIPT_HOOKS.map((hook, index) => (
              <div key={hook} className="rounded-md border border-slate-800 bg-slate-950 px-3 py-3">
                <div className="text-xs text-slate-500">0{index + 1}</div>
                <div className="mt-1 text-sm font-medium text-slate-200">{hook}</div>
                <div className="mt-2 h-1.5 rounded-full bg-emerald-500/70" />
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="分级分布">
          <div className="space-y-3">
            {LEVELS.map((level) => (
              <div key={level} className="flex items-center gap-3">
                <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold ${levelBadgeClass(level)}`}>
                  {level}
                </span>
                <div className="h-2 flex-1 rounded-full bg-slate-800">
                  <div className="h-2 rounded-full bg-sky-400" style={{ width: `${Math.min(100, ((stats.levels[level] || 0) / Math.max(1, items.length)) * 100)}%` }} />
                </div>
                <span className="w-8 text-right text-sm text-slate-300">{stats.levels[level] || 0}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="链接转化归因">
          <div className="grid grid-cols-2 gap-3">
            <Kpi label="今日点击" value="看数据页" />
            <Kpi label="下载转化" value="看数据页" />
            <Kpi label="注册转化" value="看数据页" />
            <Kpi label="付费转化" value="看数据页" />
          </div>
          <a href="/admin/data" className="mt-4 inline-flex text-sm text-sky-300 hover:text-sky-200">
            查看每天数据与话术归因
          </a>
        </Panel>
      </section>

      <Panel title="会话工作队列" action={<span className="text-xs text-slate-500">共 {total} 条，当前展示 {visibleItems.length} 条</span>}>
        <form onSubmit={submitSearch} className="mb-4 grid gap-3 lg:grid-cols-[170px_170px_1fr_auto_auto]">
          <select value={state} onChange={(event) => setState(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            {STATE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            {CHANNEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索昵称 / external_id" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600" />
          <button type="submit" className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500">搜索</button>
          <button type="button" onClick={resetFilters} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">重置</button>
        </form>

        <div className="mb-4 flex flex-wrap gap-2">
          <TabButton active={tab === "all"} onClick={() => setTab("all")}>全部</TabButton>
          <TabButton active={tab === "handoff"} onClick={() => setTab("handoff")}>待人工</TabButton>
          <TabButton active={tab === "premium"} onClick={() => setTab("premium")}>S/A精聊</TabButton>
          <TabButton active={tab === "auto"} onClick={() => setTab("auto")}>AI自动</TabButton>
          <TabButton active={tab === "risk"} onClick={() => setTab("risk")}>风险</TabButton>
        </div>

        {error && <div className="mb-4 rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}

        <div className="overflow-hidden rounded-md border border-slate-800">
          <table className="w-full min-w-[1040px] text-sm">
            <thead className="bg-slate-950 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-medium">用户</th>
                <th className="px-4 py-3 text-left font-medium">等级/路由</th>
                <th className="px-4 py-3 text-left font-medium">状态</th>
                <th className="px-4 py-3 text-left font-medium">话术链路</th>
                <th className="px-4 py-3 text-left font-medium">画像</th>
                <th className="px-4 py-3 text-left font-medium">风险</th>
                <th className="px-4 py-3 text-left font-medium">最后消息</th>
                <th className="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 bg-slate-900/35">
              {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">加载中...</td></tr>}
              {!loading && visibleItems.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">暂无符合条件的会话</td></tr>}
              {!loading && visibleItems.map((row) => (
                <tr key={row.conversation_id} className="transition hover:bg-slate-800/70">
                  <td className="px-4 py-4">
                    <div className="font-medium text-slate-100">{shortText(row.nickname || row.external_id, 42)}</div>
                    <div className="mt-1 font-mono text-xs text-slate-500">{row.external_id || row.user_id || "-"}</div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold ${levelBadgeClass(levelOf(row))}`}>{levelOf(row)}</span>
                      <span className="text-sm text-slate-300">{routeLabel(row)}</span>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs ${stateClass(row.state)}`}>{stateLabel(row.state)}</span>
                    <div className="mt-1 text-xs text-slate-500">{row.channel || row.user_channel || "-"}</div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="text-xs text-slate-300">Top3 / script_hit 可追溯</div>
                    <div className="mt-1 text-xs text-slate-500">打开详情查看每步命中</div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="text-slate-300">{row.character_name || "未绑定角色"}</div>
                    <div className="mt-1 text-xs text-slate-500">孤独感 {row.loneliness_score ?? "-"}</div>
                  </td>
                  <td className={`px-4 py-4 ${riskClass(row.risk_level)}`}>{row.risk_level || "normal"}</td>
                  <td className="px-4 py-4 text-slate-400">{fmtTime(row.last_message_at)}</td>
                  <td className="px-4 py-4 text-right">
                    <button onClick={() => void openDetail(row.conversation_id)} className="rounded-md bg-slate-800 px-3 py-2 text-xs font-medium text-sky-300 hover:bg-slate-700">
                      处理
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {(detail || detailLoading || detailError) && (
        <DetailDrawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          suggestions={suggestions}
          trace={trace}
          traceError={traceError}
          assist={assist}
          assistLoading={assistLoading}
          draft={draft}
          onDraftChange={setDraft}
          onClose={() => setDetail(null)}
          onGenerateAssist={() => void generateAssist()}
        />
      )}
    </AdminFrame>
  );
}

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-base font-semibold text-white">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Metric({ title, value, hint, tone }: { title: string; value: number; hint: string; tone: "amber" | "violet" | "emerald" | "rose" }) {
  const toneClass = { amber: "text-amber-300", violet: "text-violet-300", emerald: "text-emerald-300", rose: "text-rose-300" }[tone];
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-400">{title}</div>
      <div className={`mt-2 text-3xl font-semibold ${toneClass}`}>{value}</div>
      <div className="mt-2 text-xs text-slate-500">{hint}</div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-200">{value}</div>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={`rounded-md px-3 py-2 text-sm transition ${active ? "bg-violet-600 text-white" : "border border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-white"}`}>
      {children}
    </button>
  );
}

function DetailDrawer({
  detail,
  loading,
  error,
  suggestions,
  trace,
  traceError,
  assist,
  assistLoading,
  draft,
  onDraftChange,
  onClose,
  onGenerateAssist,
}: {
  detail: DetailResponse | null;
  loading: boolean;
  error: string | null;
  suggestions: ScriptSuggestion[];
  trace: ScriptTraceResponse | null;
  traceError: string | null;
  assist: OpsAiAssistResponse | null;
  assistLoading: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onClose: () => void;
  onGenerateAssist: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <aside className="h-full w-full max-w-3xl overflow-y-auto border-l border-slate-800 bg-slate-950 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-white">会话处理台</h2>
            <p className="text-xs text-slate-500">画像、话术命中、AI建议、人工草稿</p>
          </div>
          <button onClick={onClose} className="rounded-md border border-slate-800 px-3 py-2 text-sm text-slate-400 hover:bg-slate-800 hover:text-white">关闭</button>
        </div>
        <div className="space-y-5 p-6">
          {loading && <div className="text-sm text-slate-500">加载中...</div>}
          {error && <div className="rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}
          {detail && (
            <>
              <Panel title="用户与路由">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <Meta label="用户" value={detail.conversation.nickname || detail.conversation.external_id} />
                  <Meta label="等级路由" value={`${levelOf(detail.conversation)} / ${routeLabel(detail.conversation)}`} />
                  <Meta label="状态" value={stateLabel(detail.conversation.state)} />
                  <Meta label="渠道" value={detail.conversation.channel || detail.conversation.user_channel} />
                  <Meta label="角色" value={detail.conversation.character_name} />
                  <Meta label="关系阶段" value={detail.conversation.relationship_stage} />
                  <Meta label="孤独感" value={detail.conversation.loneliness_score != null ? String(detail.conversation.loneliness_score) : null} />
                  <Meta label="风险" value={detail.conversation.risk_level || "normal"} />
                </div>
                {detail.conversation.user_id && (
                  <div className="mt-4 flex gap-3">
                    <a href={`/admin/users/${detail.conversation.user_id}`} className="text-sm text-sky-300 hover:text-sky-200">查看画像</a>
                    <a href={`/admin/data?user_id=${detail.conversation.user_id}`} className="text-sm text-violet-300 hover:text-violet-200">查看归因</a>
                  </div>
                )}
              </Panel>
              <Panel title="话术命中轨迹">
                {traceError && <div className="mb-3 text-sm text-amber-300">{traceError}</div>}
                {!isPremium(detail.conversation) ? (
                  <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-3 text-sm text-slate-400">
                    当前用户为 {levelOf(detail.conversation)} 级，精聊话术轨迹仅对 S/A 用户启用。
                  </div>
                ) : (
                  <div className="grid grid-cols-4 gap-2">
                    {SCRIPT_HOOKS.map((hook) => {
                      const hit = trace?.script_hits?.find((item) => item.hook?.includes(hook) || item.hook === hook);
                      return (
                        <div key={hook} className={`rounded-md border px-3 py-3 ${hit ? "border-emerald-700 bg-emerald-500/10" : "border-slate-800 bg-slate-950"}`}>
                          <div className="text-sm font-medium text-slate-200">{hook}</div>
                          <div className="mt-1 truncate text-xs text-slate-500">{hit?.script_hit_id || hit?.degradation || "待记录"}</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Panel>
              <Panel title="推荐话术 Top3">
                <div className="space-y-3">
                  {suggestions.length === 0 && <div className="text-sm text-slate-500">暂无推荐话术</div>}
                  {suggestions.map((item, index) => (
                    <button key={item.id || index} type="button" onClick={() => onDraftChange(item.content)} className="w-full rounded-md border border-slate-800 bg-slate-950 p-3 text-left text-sm text-slate-200 hover:border-sky-700">
                      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                        <span>推荐 {index + 1} {item.script_type ? ` / ${item.script_type}` : ""}</span>
                        <span>{item.match_score != null ? `${Math.round(item.match_score * 100)}%` : "命中"}</span>
                      </div>
                      <div className="line-clamp-3">{item.content}</div>
                    </button>
                  ))}
                </div>
              </Panel>
              <Panel title="AI辅助与人工草稿">
                <div className="mb-4 flex justify-between gap-3">
                  <p className="text-sm text-slate-400">AI 只基于已命中话术做包装，最终发送由坐席确认。</p>
                  <button onClick={onGenerateAssist} disabled={assistLoading} className="rounded-md bg-violet-600 px-3 py-2 text-xs font-medium text-white hover:bg-violet-500 disabled:opacity-50">
                    {assistLoading ? "生成中..." : assist ? "重新生成" : "生成建议"}
                  </button>
                </div>
                {assist && (
                  <div className="mb-4 space-y-3 rounded-md border border-slate-800 bg-slate-950 p-4 text-sm">
                    <Meta label="用户状态" value={assist.summary.user_state} />
                    <Meta label="推荐策略" value={assist.summary.recommended_strategy} />
                    {assist.suggested_replies.map((reply) => (
                      <button key={reply.rank} onClick={() => onDraftChange(reply.text)} className="w-full rounded-md border border-slate-800 p-3 text-left text-slate-200 hover:border-violet-700">
                        <div className="mb-1 text-xs text-violet-300">建议回复 {reply.rank}</div>
                        {reply.text}
                      </button>
                    ))}
                  </div>
                )}
                <textarea value={draft} onChange={(event) => onDraftChange(event.target.value)} rows={5} placeholder="选择推荐话术或 AI 建议后，在这里人工修改确认。" className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-3 text-sm text-slate-200 placeholder:text-slate-600" />
                <div className="mt-3 flex justify-end gap-3">
                  <button className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">保存草稿</button>
                  <button className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500">确认发送</button>
                </div>
              </Panel>
              <Panel title="最近消息">
                <div className="space-y-3">
                  {detail.messages.length === 0 && <div className="text-sm text-slate-500">暂无消息</div>}
                  {[...detail.messages].reverse().map((message) => <MessageBubble key={message.id} message={message} />)}
                </div>
              </Panel>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="mb-1 text-xs text-slate-500">{label}</div>
      <div className="break-words text-sm text-slate-200">{value || "-"}</div>
    </div>
  );
}

function MessageBubble({ message }: { message: MessageRow }) {
  const isUser = message.sender_type === "user";
  const isOperator = message.is_operator_message || message.sender_type === "operator";
  const cls = isUser ? "border-slate-700 bg-slate-900" : isOperator ? "border-amber-800 bg-amber-950/30" : "border-violet-800 bg-violet-950/25";
  const label = isUser ? "用户" : isOperator ? "坐席" : "AI";
  return (
    <div className={`rounded-md border px-4 py-3 ${cls}`}>
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>{label}</span>
        <span>{fmtTime(message.created_at)}</span>
      </div>
      <div className="whitespace-pre-wrap break-words text-sm text-slate-100">{message.content || "（空）"}</div>
    </div>
  );
}

export default function ConversationsPage() {
  return (
    <AuthGate>
      {(operator) => <ConversationsContent operator={operator} />}
    </AuthGate>
  );
}
