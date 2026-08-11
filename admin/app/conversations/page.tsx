"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import OperatorRingControls from "@/components/OperatorRingControls";
import OperatorWsStatus from "@/components/OperatorWsStatus";
import { apiFetch, Operator } from "@/lib/auth";
import { formatBeijingDateTime, parseDbUtcTimestamp } from "@/lib/reportTime";
import { usePendingReviewRing } from "@/hooks/usePendingReviewRing";
import { useOperatorTaskWs } from "@/hooks/useOperatorTaskWs";
import { levelBadgeClass, vipToLevelTier, type LevelTier } from "@/lib/priorityDisplay";

type QueueTab = "all" | "handoff" | "released" | "premium" | "auto" | "risk";

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
  user_level: LevelTier | string | null;
  chat_route: string | null;
  relationship_stage: string | null;
  character_id: string | null;
  character_name: string | null;
  telegram_account_id: string | null;
  telegram_account_label: string | null;
  telegram_account_phone: string | null;
  telegram_account_username: string | null;
  country_code?: string | null;
  city?: string | null;
  age?: string | null;
  message_status?: string | null;
  first_system_message_at?: string | null;
  latest_message_at?: string | null;
  latest_message_sender?: string | null;
  latest_message_content?: string | null;
  post_inbound_video_expert_waived_at?: string | null;
  post_inbound_video_expert_release_eligible?: boolean | null;
  post_inbound_video_expert_relock_eligible?: boolean | null;
}

interface MessageRow {
  id: string;
  sender_type: string | null;
  content: string | null;
  content_type: string | null;
  is_operator_message: boolean | null;
  model_name: string | null;
  safety_result: unknown;
  operator_translation_zh?: string | null;
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
    post_inbound_video_expert_release_eligible?: boolean | null;
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
  translation_zh?: string | null;
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

interface TranslateResponse {
  translations: { id: string; text: string }[];
  model_used?: string | null;
  latency_ms?: number | null;
}

interface ConversationTranslateResponse extends TranslateResponse {
  saved_count: number;
  skipped_count: number;
}

const PAGE_SIZE = 50;
const CONVERSATION_POLL_MS = 30 * 1000;
const CONVERSATION_LIST_API_MARKER = "/admin/conversations?";
const TRANSLATION_PERSISTENCE_BUILD = "operator-translation-persist-20260624-v4";
const SCRIPT_HOOKS = ["入站", "消费", "探测", "分级", "回复", "坐席", "出站", "归档"];
const LEVELS: LevelTier[] = ["S", "A", "B", "C", "D"];
const COUNTRY_LABELS: Record<string, { zh: string; en: string }> = {
  US: { zh: "美国", en: "United States" },
  CA: { zh: "加拿大", en: "Canada" },
  GB: { zh: "英国", en: "United Kingdom" },
  DE: { zh: "德国", en: "Germany" },
  FR: { zh: "法国", en: "France" },
  IT: { zh: "意大利", en: "Italy" },
  ES: { zh: "西班牙", en: "Spain" },
  NL: { zh: "荷兰", en: "Netherlands" },
  BE: { zh: "比利时", en: "Belgium" },
  CH: { zh: "瑞士", en: "Switzerland" },
  AT: { zh: "奥地利", en: "Austria" },
  IE: { zh: "爱尔兰", en: "Ireland" },
  DK: { zh: "丹麦", en: "Denmark" },
  NO: { zh: "挪威", en: "Norway" },
  SE: { zh: "瑞典", en: "Sweden" },
  FI: { zh: "芬兰", en: "Finland" },
  IS: { zh: "冰岛", en: "Iceland" },
  LU: { zh: "卢森堡", en: "Luxembourg" },
  PT: { zh: "葡萄牙", en: "Portugal" },
  GR: { zh: "希腊", en: "Greece" },
  CZ: { zh: "捷克", en: "Czech Republic" },
  JP: { zh: "日本", en: "Japan" },
  AU: { zh: "澳大利亚", en: "Australia" },
  NZ: { zh: "新西兰", en: "New Zealand" },
  SG: { zh: "新加坡", en: "Singapore" },
  HK: { zh: "中国香港", en: "Hong Kong" },
};

function canRelockPostInboundVideoExpert(row: ConversationRow): boolean {
  return Boolean(
    row.post_inbound_video_expert_relock_eligible || row.post_inbound_video_expert_waived_at,
  );
}

function isReleasedExpert(row: ConversationRow): boolean {
  return Boolean(row.post_inbound_video_expert_waived_at);
}

function isExpertPendingRelease(row: ConversationRow): boolean {
  return Boolean(row.post_inbound_video_expert_release_eligible);
}

function isTakenOver(row: ConversationRow): boolean {
  return Boolean(row.assigned_operator_id) || row.state === "HUMAN_LOCKED";
}

function isAiFollowing(row: ConversationRow): boolean {
  return !isFrozen(row) && row.state === "AI_ACTIVE";
}

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
  return formatBeijingDateTime(value);
}

function sortTime(value: string | null | undefined): number {
  if (!value) return 0;
  return parseDbUtcTimestamp(value)?.getTime() ?? 0;
}

function shortText(value: string | null | undefined, max = 56): string {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function normalizeForTranslationCompare(value: string | null | undefined): string {
  return (value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function hasCjk(value: string | null | undefined): boolean {
  return /[\u3400-\u9fff]/.test(value || "");
}

function hasTranslatableText(value: string | null | undefined): boolean {
  const text = (value || "")
    .replace(/https?:\/\/\S+/gi, " ")
    .replace(/[@#]\w+/g, " ")
    .trim();
  return /[A-Za-z]{3,}|[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0370-\u03ff]/.test(text);
}

function isStaleSavedTranslation(message: MessageRow, translatedText: string | null | undefined): boolean {
  const translated = (translatedText || "").trim();
  const source = (message.content || "").trim();
  if (!translated || !hasTranslatableText(source) || hasCjk(source)) return false;
  return !hasCjk(translated) || normalizeForTranslationCompare(source) === normalizeForTranslationCompare(translated);
}

function usableSavedTranslation(message: MessageRow): string {
  const translated = (message.operator_translation_zh || "").trim();
  if (!translated || isStaleSavedTranslation(message, translated)) return "";
  return translated;
}

function telegramAccountDisplay(row: ConversationRow): string {
  return (
    row.telegram_account_label ||
    row.telegram_account_username ||
    row.telegram_account_phone ||
    row.telegram_account_id ||
    "—"
  );
}

function levelOf(row: ConversationRow): LevelTier {
  const explicitLevel = String(row.user_level || "").trim().toUpperCase();
  if (LEVELS.includes(explicitLevel as LevelTier)) return explicitLevel as LevelTier;
  return vipToLevelTier(row.vip_level ?? 0);
}

function isPremium(row: ConversationRow): boolean {
  return !isFrozen(row) && (levelOf(row) === "S" || levelOf(row) === "A");
}

function isReleasedTabRow(row: ConversationRow): boolean {
  if (isFrozen(row)) return false;
  if (isPremium(row)) return false;
  if (isAiFollowing(row)) return false;
  return isReleasedExpert(row) || isExpertPendingRelease(row);
}

function isWaiting(row: ConversationRow): boolean {
  return (
    !isFrozen(row)
    && row.state === "WAITING_OPERATOR"
    && !row.assigned_operator_id
    && !isExpertPendingRelease(row)
  );
}

function isRisk(row: ConversationRow): boolean {
  return isFrozen(row) || row.risk_level === "critical" || row.risk_level === "high" || row.risk_level === "elevated";
}

function isFrozen(row: ConversationRow): boolean {
  return row.user_status === "frozen" || row.state === "FROZEN";
}

function stateLabel(state: string | null): string {
  switch (state) {
    case "WAITING_OPERATOR":
      return "待接管";
    case "HUMAN_LOCKED":
      return "人工中";
    case "AI_ACTIVE":
      return "AI跟进";
    case "FROZEN":
      return "已冻结";
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
    case "FROZEN":
      return "border-rose-700/70 bg-rose-500/10 text-rose-200";
    default:
      return "border-slate-700 bg-slate-800 text-slate-300";
  }
}

function queueStateLabel(row: ConversationRow): string {
  if (isFrozen(row)) return "已冻结";
  if (row.assigned_operator_id || row.state === "HUMAN_LOCKED") return "已接管";
  if (row.state === "WAITING_OPERATOR") return "待接管";
  if (row.state === "AI_ACTIVE") return "AI跟进";
  if (row.state === "CLOSED") return "已关闭";
  return row.state || "-";
}

function queueStateClass(row: ConversationRow): string {
  if (isFrozen(row)) return "border-rose-700/70 bg-rose-500/10 text-rose-200";
  if (row.assigned_operator_id || row.state === "HUMAN_LOCKED") {
    return "border-violet-600/70 bg-violet-500/10 text-violet-200";
  }
  return stateClass(row.state);
}

function riskClass(risk: string | null): string {
  if (risk === "critical" || risk === "high") return "text-rose-300";
  if (risk === "elevated") return "text-amber-300";
  return "text-slate-400";
}

function countryDisplay(code: string | null | undefined): string {
  const normalized = (code || "").trim().toUpperCase();
  if (!normalized) return "";
  const label = COUNTRY_LABELS[normalized];
  if (!label) return normalized;
  return `${label.zh} / ${label.en}`;
}

function bilingualText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "";
  return `${text} / ${text}`;
}

function ageDisplay(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "";
  return `${text}岁 / ${text} years old`;
}

function messageStatusDisplay(status: string | null | undefined): { text: string; unread: boolean } {
  if (status === "unread") return { text: "未读 / Unread", unread: true };
  if (status === "read") return { text: "已读 / Read", unread: false };
  return { text: "", unread: false };
}

function messageSenderDisplay(sender: string | null | undefined): string {
  if (sender === "user") return "用户 / User";
  if (sender === "assistant") return "AI / AI";
  if (sender === "operator") return "人工 / Operator";
  return "";
}

function routeLabel(row: ConversationRow): string {
  if (row.chat_route === "manual_premium") return "S/A精聊";
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
    return sortTime(b.last_message_at || b.created_at) - sortTime(a.last_message_at || a.created_at);
  });
}

function ConversationsContent({ operator }: { operator: Operator }) {
  const [items, setItems] = useState<ConversationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
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
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [queueJoinPremiumId, setQueueJoinPremiumId] = useState<string | null>(null);
  const [queueFreezeId, setQueueFreezeId] = useState<string | null>(null);
  const [queueReleaseId, setQueueReleaseId] = useState<string | null>(null);
  const [humanReleaseId, setHumanReleaseId] = useState<string | null>(null);
  const [relockLoading, setRelockLoading] = useState(false);
  const [actionToast, setActionToast] = useState<string | null>(null);
  const [sendLoading, setSendLoading] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [messageTranslations, setMessageTranslations] = useState<Record<string, string>>({});
  const [translatingMessages, setTranslatingMessages] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
  const queuePanelRef = useRef<HTMLDivElement | null>(null);
  const listInFlightRef = useRef(false);
  const listRequestSeqRef = useRef(0);
  const detailRequestSeqRef = useRef(0);
  const detailRef = useRef<DetailResponse | null>(null);

  useEffect(() => {
    detailRef.current = detail;
  }, [detail]);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    if (options?.silent && listInFlightRef.current) return;
    const requestSeq = listRequestSeqRef.current + 1;
    listRequestSeqRef.current = requestSeq;
    listInFlightRef.current = true;
    if (!options?.silent) {
      setError(null);
      setListLoading(true);
    }
    try {
      const qs = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      qs.set("tab", tab);
      const backendState = tab === "auto" ? "AI_ACTIVE" : state;
      if (backendState) qs.set("state", backendState);
      if (channel) qs.set("channel", channel);
      if (appliedSearch.trim()) qs.set("search", appliedSearch.trim());
      const response = await apiFetch<ListResponse>(
        `${CONVERSATION_LIST_API_MARKER}${qs.toString()}`,
      );
      if (listRequestSeqRef.current !== requestSeq) return;
      setItems(sortQueue(response.items || []));
      setTotal(response.total || 0);
    } catch (err) {
      if (!options?.silent && listRequestSeqRef.current === requestSeq) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (listRequestSeqRef.current === requestSeq) {
        listInFlightRef.current = false;
        if (!options?.silent) setListLoading(false);
      }
    }
  }, [appliedSearch, channel, state, tab]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void load({ silent: true });
    }, CONVERSATION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const waitingConversationIds = useMemo(
    () => items.filter((row) => isWaiting(row) || isExpertPendingRelease(row)).map((item) => item.conversation_id),
    [items],
  );

  const {
    soundEnabled,
    setSoundEnabled,
    needsUnlock,
    unlockSound,
    testRing,
  } = usePendingReviewRing(waitingConversationIds);

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
      releaseReview: items.filter(isExpertPendingRelease).length,
      released: items.filter((row) => !isFrozen(row) && !isPremium(row) && !isAiFollowing(row) && isReleasedExpert(row)).length,
      premium: items.filter((row) => isPremium(row) && !isAiFollowing(row)).length,
      aiActive: items.filter(isAiFollowing).length,
      risk: items.filter(isRisk).length,
      levels,
    };
  }, [items]);

  const visibleItems = useMemo(() => {
    if (tab === "handoff") return items.filter(isWaiting);
    if (tab === "released") {
      return items
        .filter(isReleasedTabRow)
        .sort((a, b) => {
          const aPending = isExpertPendingRelease(a) || (isTakenOver(a) && !isReleasedExpert(a)) ? 0 : 1;
          const bPending = isExpertPendingRelease(b) || (isTakenOver(b) && !isReleasedExpert(b)) ? 0 : 1;
          if (aPending !== bPending) return aPending - bPending;
          return sortTime(b.last_message_at || b.created_at) - sortTime(a.last_message_at || a.created_at);
        });
    }
    if (tab === "premium") return items.filter((row) => isPremium(row) && !isAiFollowing(row));
    if (tab === "auto") return items.filter(isAiFollowing);
    if (tab === "risk") return items.filter(isRisk);
    return [...items].sort((a, b) => {
      const aWaiting = isWaiting(a);
      const bWaiting = isWaiting(b);
      if (aWaiting !== bWaiting) return aWaiting ? -1 : 1;
      return sortTime(b.last_message_at || b.created_at) - sortTime(a.last_message_at || a.created_at);
    });
  }, [items, tab]);

  const jumpToQueue = useCallback((nextTab: QueueTab) => {
    setTab(nextTab);
    window.setTimeout(() => {
      queuePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }, []);

  async function acceptConversation(row: ConversationRow) {
    if (!isWaiting(row) || row.assigned_operator_id) return;
    await apiFetch(`/admin/conversations/${row.conversation_id}/accept`, {
      method: "POST",
    });
    setItems((current) =>
      current.map((item) =>
        item.conversation_id === row.conversation_id
          ? { ...item, state: "HUMAN_LOCKED", assigned_operator_id: operator.operator_id }
          : item,
      ),
    );
  }

  async function processConversation(row: ConversationRow) {
    setError(null);
    try {
      await acceptConversation(row);
      await openDetail(row.conversation_id);
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function openDetail(conversationId: string) {
    const requestSeq = detailRequestSeqRef.current + 1;
    detailRequestSeqRef.current = requestSeq;
    setDetail(null);
    setDetailError(null);
    setDeleteError(null);
    setSendError(null);
    setSuggestions([]);
    setTrace(null);
    setTraceError(null);
    setAssist(null);
    setDraft("");
    setMessageTranslations({});
    setTranslationError(null);
    setDetailLoading(true);
    try {
      const response = await apiFetch<DetailResponse>(`/admin/conversations/${conversationId}`);
      if (detailRequestSeqRef.current !== requestSeq) return;
      setDetail(response);
      setMessageTranslations(savedMessageTranslations(response.messages));
      void loadSuggestions(response.conversation);
      if (isPremium(response.conversation)) {
        void loadTrace(conversationId);
      }
    } catch (err) {
      if (detailRequestSeqRef.current !== requestSeq) return;
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      if (detailRequestSeqRef.current === requestSeq) {
        setDetailLoading(false);
      }
    }
  }

  function savedMessageTranslations(messages: MessageRow[]) {
    const saved: Record<string, string> = {};
    for (const message of messages) {
      const translated = usableSavedTranslation(message);
      if (translated) {
        saved[message.id] = translated;
      }
    }
    return saved;
  }

  function filterTranslationsForMessageIds(
    translations: Record<string, string>,
    allowedMessageIds: Set<string>,
  ) {
    const filtered: Record<string, string> = {};
    for (const [id, text] of Object.entries(translations)) {
      if (allowedMessageIds.has(id) && text.trim()) {
        filtered[id] = text;
      }
    }
    return filtered;
  }

  async function deleteSingleMessage(messageId: string) {
    if (!detail || deleteLoading) return;
    const confirmed = window.confirm("确认删除这条聊天记录？删除后页面和 AI 上下文都不会再使用它。");
    if (!confirmed) return;

    const conversationId = detail.conversation.conversation_id;
    setDeleteLoading(true);
    setDeleteError(null);
    try {
      await apiFetch(`/admin/conversations/${conversationId}/messages/${messageId}`, {
        method: "DELETE",
      });
      await openDetail(conversationId);
      void load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleteLoading(false);
    }
  }

  async function deleteAllUserMessages() {
    if (!detail?.conversation.user_id || deleteLoading) return;
    const confirmed = window.confirm("确认删除这个用户的所有聊天记录？此操作不可恢复。");
    if (!confirmed) return;

    const conversationId = detail.conversation.conversation_id;
    setDeleteLoading(true);
    setDeleteError(null);
    try {
      await apiFetch(`/admin/users/${detail.conversation.user_id}/messages`, {
        method: "DELETE",
      });
      await openDetail(conversationId);
      void load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleteLoading(false);
    }
  }

  async function freezeConversation(row: ConversationRow) {
    if (!row.user_id || queueFreezeId || isFrozen(row)) return;
    const name = row.nickname || row.external_id || row.conversation_id;
    const confirmed = window.confirm(
      `确认冻结并停止回复？\n\n${name}\n\n冻结后：\n- 不再 AI 自动回复\n- 取消待发送 nurture / 通知\n- 会话标记为已冻结`,
    );
    if (!confirmed) return;

    setQueueFreezeId(row.conversation_id);
    setError(null);
    try {
      await apiFetch<{ status: string }>(`/users/${row.user_id}/freeze`, {
        method: "POST",
        body: JSON.stringify({ reason: "operator_freeze_from_queue" }),
      });
      if (detail?.conversation.conversation_id === row.conversation_id) {
        setDetail(null);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setQueueFreezeId(null);
    }
  }

  async function releasePostInboundVideoExpert(row: ConversationRow) {
    if (!row.post_inbound_video_expert_release_eligible || queueReleaseId) return;
    const name = row.nickname || row.external_id || row.conversation_id;
    const confirmed = window.confirm(
      `确认放行？\n\n${name}\n\n放行后该用户将恢复与普通用户一样：\n- AI 自动回复\n- 固定话术 / TikTok 引导等\n\n之后可在「已放行」标签或会话详情点击「收回人工」。`,
    );
    if (!confirmed) return;

    setQueueReleaseId(row.conversation_id);
    setError(null);
    try {
      await apiFetch<{ status: string; state: string }>(
        `/admin/conversations/${row.conversation_id}/post-inbound-video-release`,
        { method: "POST" },
      );
      setTab("released");
      setActionToast("已放行：该用户已恢复 AI/话术自动回复。可在此页或详情点击「收回人工」。");
      await openDetail(row.conversation_id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setQueueReleaseId(null);
    }
  }

  async function releaseHumanConversation(row: ConversationRow) {
    if (!isTakenOver(row) || row.post_inbound_video_expert_release_eligible || humanReleaseId) return;
    const name = row.nickname || row.external_id || row.conversation_id;
    const confirmed = window.confirm(
      `确认放回 AI？\n\n${name}\n\n放回后：\n- 清除人工接管状态\n- 用户后续消息由系统正常自动回复\n- 当前坐席不再占用这个会话`,
    );
    if (!confirmed) return;

    setHumanReleaseId(row.conversation_id);
    setError(null);
    try {
      await apiFetch<{ status: string; state: string }>(
        `/admin/conversations/${row.conversation_id}/release-human`,
        { method: "POST" },
      );
      setTab("auto");
      setActionToast("已放回 AI：该用户后续消息会由系统正常自动回复。");
      if (detail?.conversation.conversation_id === row.conversation_id) {
        await openDetail(row.conversation_id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setHumanReleaseId(null);
    }
  }

  async function relockPostInboundVideoExpert(row: ConversationRow) {
    if (!canRelockPostInboundVideoExpert(row) || relockLoading) return;
    const name = row.nickname || row.external_id || row.conversation_id;
    const confirmed = window.confirm(
      `确认收回人工？\n\n${name}\n\n收回后该用户将重新回到两段自动来电视频后的待人工专属模式，系统/AI 不再自动回复。`,
    );
    if (!confirmed) return;

    setRelockLoading(true);
    setError(null);
    try {
      await apiFetch<{ status: string; state: string }>(
        `/admin/conversations/${row.conversation_id}/post-inbound-video-relock`,
        { method: "POST" },
      );
      setTab("handoff");
      setActionToast("已收回人工：该用户重新回到两段自动来电视频后的待人工专属模式。");
      await openDetail(row.conversation_id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRelockLoading(false);
    }
  }

  async function joinPremiumChat(row: ConversationRow) {
    if (queueJoinPremiumId || !row.user_id || isPremium(row)) return;
    const name = row.nickname || row.external_id || row.conversation_id;
    const confirmed = window.confirm(
      `确认加入 S/A精聊？\n\n${name}\n\n加入后：\n- 该用户会进入「S/A精聊」列表\n- 不会删除会话和聊天记录\n- 不会再出现在「已放行」列表里`,
    );
    if (!confirmed) return;

    setQueueJoinPremiumId(row.conversation_id);
    setError(null);
    try {
      await apiFetch(`/admin/conversations/${row.conversation_id}/join-premium-chat`, {
        method: "POST",
      });
      setTab("premium");
      setActionToast("已加入 S/A精聊：该用户已从已放行队列移到 S/A精聊。");
      if (detail?.conversation.conversation_id === row.conversation_id) {
        await openDetail(row.conversation_id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setQueueJoinPremiumId(null);
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
      let response = await apiFetch<OpsAiAssistResponse>(
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
      const missingTranslations = (response.suggested_replies || []).filter((reply) => reply.text.trim() && !reply.translation_zh?.trim());
      if (missingTranslations.length > 0) {
        const translated = await translateTexts(
          missingTranslations.map((reply) => ({
            id: String(reply.rank),
            text: reply.text,
            sender_type: "assistant",
          })),
        );
        response = {
          ...response,
          suggested_replies: response.suggested_replies.map((reply) => ({
            ...reply,
            translation_zh: reply.translation_zh || translated[String(reply.rank)] || "",
          })),
        };
      }
      setAssist(response);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setAssistLoading(false);
    }
  }

  async function translateTexts(items: { id: string; text: string; sender_type?: string | null }[]) {
    const chunks: typeof items[] = [];
    for (let i = 0; i < items.length; i += 50) {
      chunks.push(items.slice(i, i + 50));
    }
    const merged: Record<string, string> = {};
    for (const chunk of chunks) {
      const response = await apiFetch<TranslateResponse>("/ops-ai/translate", {
        method: "POST",
        body: JSON.stringify({
          target_language: "zh-CN",
          preserve_terms: [detail?.conversation.nickname, detail?.conversation.external_id].filter(Boolean),
          items: chunk,
        }),
      });
      for (const item of response.translations || []) {
        const id = String(item.id || "").trim();
        if (id) {
          merged[id] = item.text;
        }
      }
    }
    return merged;
  }

  async function translateAllMessages() {
    if (!detail || translatingMessages) return;
    const activeDetail = detail;
    const activeConversationId = activeDetail.conversation.conversation_id;
    const activeMessages = activeDetail.messages;
    const currentMessageIds = new Set(activeMessages.map((message) => message.id).filter(Boolean));
    const savedTranslations = {
      ...savedMessageTranslations(activeMessages),
      ...filterTranslationsForMessageIds(messageTranslations, currentMessageIds),
    };
    const items = activeMessages
      .filter((message) => message.id && (message.content || "").trim() && !savedTranslations[message.id])
      .map((message) => ({
        id: message.id,
        text: message.content || "",
        sender_type: message.sender_type,
      }));
    if (items.length === 0) {
      setMessageTranslations(savedTranslations);
      return;
    }

    setTranslatingMessages(true);
    setTranslationError(null);
    try {
      const response = await apiFetch<ConversationTranslateResponse>(
        `/ops-ai/conversations/${activeConversationId}/translate-messages`,
        {
          method: "POST",
          body: JSON.stringify({
            target_language: "zh-CN",
            preserve_terms: [activeDetail.conversation.nickname, activeDetail.conversation.external_id].filter(Boolean),
            message_ids: items.map((item) => item.id),
          }),
        },
      );
      const translated: Record<string, string> = {};
      for (const item of response.translations || []) {
        const id = String(item.id || "").trim();
        if (id && item.text?.trim()) {
          translated[id] = item.text;
        }
      }
      const currentDetail = detailRef.current;
      if (!currentDetail || currentDetail.conversation.conversation_id !== activeConversationId) {
        return;
      }
      const translatedForCurrent = filterTranslationsForMessageIds(translated, currentMessageIds);
      if (Object.keys(translatedForCurrent).length === 0) {
        if (response.skipped_count > 0) {
          setMessageTranslations(savedTranslations);
          return;
        }
        setTranslationError("翻译结果没有匹配当前会话消息，请重新打开会话后再试。");
        return;
      }
      const mergedTranslations = { ...savedTranslations, ...translatedForCurrent };
      setMessageTranslations(mergedTranslations);
      setDetail((current) => {
        if (!current || current.conversation.conversation_id !== activeConversationId) {
          return current;
        }
        return {
          ...current,
          messages: current.messages.map((message) => ({
            ...message,
            operator_translation_zh: mergedTranslations[message.id] || usableSavedTranslation(message) || message.operator_translation_zh,
          })),
        };
      });
    } catch (err) {
      setTranslationError(err instanceof Error ? err.message : String(err));
    } finally {
      setTranslatingMessages(false);
    }
  }

  async function confirmSendDraft() {
    if (!detail || sendLoading) return;
    const content = draft.trim();
    if (!content) {
      setSendError("请先填写要发送的内容。");
      return;
    }

    setSendLoading(true);
    setSendError(null);
    try {
      await apiFetch(`/admin/conversations/${detail.conversation.conversation_id}/operator-reply`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      const conversationId = detail.conversation.conversation_id;
      setDraft("");
      await openDetail(conversationId);
      void load();
    } catch (err) {
      setSendError(err instanceof Error ? err.message : String(err));
    } finally {
      setSendLoading(false);
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

  function renderQueueActions(row: ConversationRow) {
    return (
      <div className="flex min-w-[220px] flex-wrap justify-end gap-2">
        <button onClick={() => void processConversation(row)} className="rounded-md bg-slate-800 px-3 py-2 text-xs font-medium text-sky-300 hover:bg-slate-700">
          处理
        </button>
        {row.post_inbound_video_expert_release_eligible ? (
          <button
            type="button"
            onClick={() => void releasePostInboundVideoExpert(row)}
            disabled={queueReleaseId === row.conversation_id}
            className="rounded-md border border-emerald-700 px-3 py-2 text-xs font-medium text-emerald-200 hover:bg-emerald-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {queueReleaseId === row.conversation_id ? "放行中..." : "放行"}
          </button>
        ) : null}
        {isTakenOver(row) && !row.post_inbound_video_expert_release_eligible ? (
          <button
            type="button"
            onClick={() => void releaseHumanConversation(row)}
            disabled={humanReleaseId === row.conversation_id}
            className="rounded-md border border-emerald-700 px-3 py-2 text-xs font-medium text-emerald-200 hover:bg-emerald-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {humanReleaseId === row.conversation_id ? "放回中..." : "放回 AI"}
          </button>
        ) : null}
        {canRelockPostInboundVideoExpert(row) ? (
          <button
            type="button"
            onClick={() => void relockPostInboundVideoExpert(row)}
            disabled={relockLoading}
            className="rounded-md border border-violet-700 px-3 py-2 text-xs font-medium text-violet-200 hover:bg-violet-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {relockLoading ? "收回中..." : "收回人工"}
          </button>
        ) : null}
        {!isFrozen(row) && row.user_id && (
          <button
            type="button"
            onClick={() => void freezeConversation(row)}
            disabled={queueFreezeId === row.conversation_id}
            className="rounded-md border border-amber-700 px-3 py-2 text-xs font-medium text-amber-200 hover:bg-amber-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {queueFreezeId === row.conversation_id ? "冻结中..." : "冻结并停止回复"}
          </button>
        )}
        {!isPremium(row) && row.user_id ? (
          <button
            type="button"
            onClick={() => void joinPremiumChat(row)}
            disabled={queueJoinPremiumId === row.conversation_id}
            className="rounded-md border border-violet-700 px-3 py-2 text-xs font-medium text-violet-200 hover:bg-violet-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {queueJoinPremiumId === row.conversation_id ? "加入中..." : "加入精聊"}
          </button>
        ) : null}
      </div>
    );
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

      <section
        className={`mb-5 rounded-lg border p-4 ${
          stats.waiting > 0
            ? "border-amber-600 bg-amber-950/30"
            : "border-slate-800 bg-slate-900"
        }`}
      >
        <OperatorRingControls
          soundEnabled={soundEnabled}
          onToggleSound={() => setSoundEnabled()}
          needsUnlock={needsUnlock}
          onUnlockSound={() => void unlockSound()}
          onTestRing={() => testRing()}
          description={
            stats.waiting > 0
              ? `当前有 ${stats.waiting} 条待人工接管会话，将播放叮铃-叮铃提醒（双频 440Hz+480Hz）。`
              : "有待人工接管会话时，将播放与视频通话页相同的叮铃-叮铃提醒。"
          }
        />
      </section>

      <section className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Metric title="待人工接管" value={stats.waiting} hint="S/A 挂起、超时、待坐席处理" tone="amber" onClick={() => jumpToQueue("handoff")} />
        <Metric title="待放行审核" value={stats.releaseReview} hint="累计第6次独立入站视频来电后审核是否放行" tone="violet" onClick={() => jumpToQueue("released")} />
        <Metric title="已恢复 AI" value={stats.released} hint="已放行、可收回人工" tone="emerald" />
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

      <div ref={queuePanelRef}>
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
          <TabButton active={tab === "released"} onClick={() => setTab("released")}>
            已放行{(stats.releaseReview + stats.released) > 0 ? ` (${stats.releaseReview + stats.released})` : ""}
          </TabButton>
          <TabButton active={tab === "premium"} onClick={() => setTab("premium")}>S/A精聊</TabButton>
          <TabButton active={tab === "auto"} onClick={() => setTab("auto")}>AI自动</TabButton>
          <TabButton active={tab === "risk"} onClick={() => setTab("risk")}>风险</TabButton>
        </div>

        {error && <div className="mb-4 rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}
        {actionToast && (
          <div className="mb-4 rounded-md border border-violet-800 bg-violet-950/40 px-4 py-3 text-sm text-violet-100">
            {actionToast}
            <button
              type="button"
              className="ml-3 text-violet-300 underline"
              onClick={() => setActionToast(null)}
            >
              关闭
            </button>
          </div>
        )}

        {tab === "premium" ? (
          <div className="overflow-x-auto rounded-md border border-slate-800">
            <table className="w-full min-w-[1120px] text-sm">
              <thead className="bg-slate-950 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">用户</th>
                  <th className="px-4 py-3 text-left font-medium">国家</th>
                  <th className="px-4 py-3 text-left font-medium">城市</th>
                  <th className="px-4 py-3 text-left font-medium">年龄</th>
                  <th className="px-4 py-3 text-left font-medium">消息状态</th>
                  <th className="px-4 py-3 text-left font-medium">开始消息</th>
                  <th className="px-4 py-3 text-left font-medium">最后消息</th>
                  <th className="sticky right-0 z-10 w-[260px] bg-slate-950 px-4 py-3 text-right font-medium shadow-[-12px_0_18px_rgba(2,6,23,0.75)]">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900/35">
                {listLoading && visibleItems.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">加载中...</td></tr>}
                {!listLoading && visibleItems.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">暂无符合条件的会话</td></tr>}
                {visibleItems.map((row) => {
                  const messageStatus = messageStatusDisplay(row.message_status);
                  return (
                    <tr key={row.conversation_id} className="transition hover:bg-slate-800/70">
                      <td className="px-4 py-4 align-top">
                        <div className="font-medium text-slate-100">{shortText(row.nickname || row.external_id, 42)}</div>
                        <div className="mt-1 font-mono text-xs text-slate-500">{row.external_id || row.user_id || ""}</div>
                      </td>
                      <td className="px-4 py-4 align-top text-slate-200">{countryDisplay(row.country_code)}</td>
                      <td className="px-4 py-4 align-top text-slate-200">{bilingualText(row.city)}</td>
                      <td className="px-4 py-4 align-top text-slate-200">{ageDisplay(row.age)}</td>
                      <td className="px-4 py-4 align-top">
                        {messageStatus.text ? (
                          <span
                            className={
                              messageStatus.unread
                                ? "inline-flex rounded-md bg-red-600 px-3 py-1.5 text-sm font-bold text-white shadow-sm shadow-red-950/40"
                                : "inline-flex rounded-md border border-slate-700 bg-slate-950/60 px-3 py-1.5 text-sm text-slate-300"
                            }
                          >
                            {messageStatus.text}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-4 align-top">
                        {row.first_system_message_at ? (
                          <>
                            <div className="text-xs text-slate-500">系统首条 / First system</div>
                            <div className="mt-1 text-slate-300">{fmtTime(row.first_system_message_at)}</div>
                          </>
                        ) : null}
                      </td>
                      <td className="px-4 py-4 align-top">
                        <div className="text-xs text-slate-500">{messageSenderDisplay(row.latest_message_sender)}</div>
                        {row.latest_message_at ? <div className="mt-1 text-slate-300">{fmtTime(row.latest_message_at)}</div> : null}
                        {row.latest_message_content ? <div className="mt-2 max-w-[300px] text-xs text-slate-400">{shortText(row.latest_message_content, 96)}</div> : null}
                      </td>
                      <td className="sticky right-0 bg-slate-900/95 px-4 py-4 align-top shadow-[-12px_0_18px_rgba(2,6,23,0.65)]">{renderQueueActions(row)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-slate-800">
            <table className="w-full min-w-[1180px] text-sm">
              <thead className="bg-slate-950 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">用户</th>
                  <th className="px-4 py-3 text-left font-medium">接听 TG 账号</th>
                  <th className="px-4 py-3 text-left font-medium">等级/路由</th>
                  <th className="px-4 py-3 text-left font-medium">状态</th>
                  <th className="px-4 py-3 text-left font-medium">话术链路</th>
                  <th className="px-4 py-3 text-left font-medium">画像</th>
                  <th className="px-4 py-3 text-left font-medium">风险</th>
                  <th className="px-4 py-3 text-left font-medium">最后消息</th>
                  <th className="sticky right-0 z-10 w-[240px] bg-slate-950 px-4 py-3 text-right font-medium shadow-[-12px_0_18px_rgba(2,6,23,0.75)]">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900/35">
                {listLoading && visibleItems.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-500">加载中...</td></tr>}
                {!listLoading && visibleItems.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-500">暂无符合条件的会话</td></tr>}
                {visibleItems.map((row) => (
                  <tr key={row.conversation_id} className="transition hover:bg-slate-800/70">
                    <td className="px-4 py-4 align-top">
                      <div className="font-medium text-slate-100">{shortText(row.nickname || row.external_id, 42)}</div>
                      <div className="mt-1 font-mono text-xs text-slate-500">{row.external_id || row.user_id || "-"}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="font-medium text-slate-200">{row.telegram_account_label || row.telegram_account_username || "-"}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.telegram_account_phone || row.telegram_account_id || ""}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs ${levelBadgeClass(levelOf(row))}`}>{levelOf(row)}</span>
                        <span className="text-slate-200">{routeLabel(row)}</span>
                      </div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <span className={`inline-flex rounded-full border px-3 py-1 text-xs ${queueStateClass(row)}`}>{queueStateLabel(row)}</span>
                      {isExpertPendingRelease(row) ? <div className="mt-2 text-xs text-amber-300">待审核放行</div> : null}
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">Top3 / script_hit 可追溯</div>
                      <div className="mt-1 text-xs text-slate-500">打开详情查看每步命中</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="text-slate-200">{row.character_name || "未绑定角色"}</div>
                      <div className="mt-1 text-xs text-slate-500">孤独感 {row.loneliness_score ?? "-"}</div>
                    </td>
                    <td className={`px-4 py-4 align-top ${riskClass(row.risk_level)}`}>{row.risk_level || "normal"}</td>
                    <td className="px-4 py-4 align-top text-slate-400">{fmtTime(row.last_message_at)}</td>
                    <td className="sticky right-0 bg-slate-900/95 px-4 py-4 align-top shadow-[-12px_0_18px_rgba(2,6,23,0.65)]">{renderQueueActions(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      </div>

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
          deleteLoading={deleteLoading}
          deleteError={deleteError}
          sendLoading={sendLoading}
          sendError={sendError}
          messageTranslations={messageTranslations}
          translatingMessages={translatingMessages}
          translationError={translationError}
          onDraftChange={setDraft}
          onClose={() => {
            detailRequestSeqRef.current += 1;
            setDetail(null);
            setDetailError(null);
            setMessageTranslations({});
            setTranslationError(null);
          }}
          onGenerateAssist={() => void generateAssist()}
          onConfirmSend={() => void confirmSendDraft()}
          onTranslateAllMessages={() => void translateAllMessages()}
          onDeleteMessage={(messageId) => void deleteSingleMessage(messageId)}
          onDeleteAllUserMessages={() => void deleteAllUserMessages()}
          onFreeze={() => detail && void freezeConversation(detail.conversation)}
          freezeLoading={queueFreezeId === detail?.conversation.conversation_id}
          onRelock={() => detail && void relockPostInboundVideoExpert(detail.conversation)}
          relockLoading={relockLoading}
          onRelease={() => detail && void releasePostInboundVideoExpert(detail.conversation)}
          releaseLoading={queueReleaseId === detail?.conversation.conversation_id}
          onReleaseHuman={() => detail && void releaseHumanConversation(detail.conversation)}
          humanReleaseLoading={humanReleaseId === detail?.conversation.conversation_id}
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

function Metric({ title, value, hint, tone, onClick }: { title: string; value: number; hint: string; tone: "amber" | "violet" | "emerald" | "rose"; onClick?: () => void }) {
  const toneClass = { amber: "text-amber-300", violet: "text-violet-300", emerald: "text-emerald-300", rose: "text-rose-300" }[tone];
  const clickableClass = onClick
    ? "cursor-pointer hover:border-sky-700 hover:bg-slate-800/70 focus:outline-none focus:ring-2 focus:ring-sky-600"
    : "";
  const content = (
    <>
      <div className="text-sm text-slate-400">{title}</div>
      <div className={`mt-2 text-3xl font-semibold ${toneClass}`}>{value}</div>
      <div className="mt-2 text-xs text-slate-500">{hint}</div>
      {onClick ? <div className="mt-2 text-xs text-sky-300">点击定位到用户列表</div> : null}
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={`w-full rounded-lg border border-slate-800 bg-slate-900 px-5 py-4 text-left transition ${clickableClass}`}>
        {content}
      </button>
    );
  }
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      {content}
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
  deleteLoading,
  deleteError,
  sendLoading,
  sendError,
  messageTranslations,
  translatingMessages,
  translationError,
  onDraftChange,
  onClose,
  onGenerateAssist,
  onConfirmSend,
  onTranslateAllMessages,
  onDeleteMessage,
  onDeleteAllUserMessages,
  onFreeze,
  freezeLoading,
  onRelock,
  relockLoading,
  onRelease,
  releaseLoading,
  onReleaseHuman,
  humanReleaseLoading,
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
  deleteLoading: boolean;
  deleteError: string | null;
  sendLoading: boolean;
  sendError: string | null;
  messageTranslations: Record<string, string>;
  translatingMessages: boolean;
  translationError: string | null;
  onDraftChange: (value: string) => void;
  onClose: () => void;
  onGenerateAssist: () => void;
  onConfirmSend: () => void;
  onTranslateAllMessages: () => void;
  onDeleteMessage: (messageId: string) => void;
  onDeleteAllUserMessages: () => void;
  onFreeze: () => void;
  freezeLoading: boolean;
  onRelock: () => void;
  relockLoading: boolean;
  onRelease: () => void;
  releaseLoading: boolean;
  onReleaseHuman: () => void;
  humanReleaseLoading: boolean;
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
          {deleteError && <div className="rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{deleteError}</div>}
          {sendError && <div className="rounded-md border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{sendError}</div>}
          {detail && (
            <>
              <Panel title="用户与路由">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <Meta label="用户" value={detail.conversation.nickname || detail.conversation.external_id} />
                  <Meta label="接听 TG 账号" value={telegramAccountDisplay(detail.conversation)} />
                  <Meta label="等级路由" value={`${levelOf(detail.conversation)} / ${routeLabel(detail.conversation)}`} />
                  <Meta label="状态" value={stateLabel(detail.conversation.state)} />
                  <Meta label="渠道" value={detail.conversation.channel || detail.conversation.user_channel} />
                  <Meta label="角色" value={detail.conversation.character_name} />
                  <Meta label="关系阶段" value={detail.conversation.relationship_stage} />
                  <Meta label="孤独感" value={detail.conversation.loneliness_score != null ? String(detail.conversation.loneliness_score) : null} />
                  <Meta label="风险" value={detail.conversation.risk_level || "normal"} />
                  <Meta label="用户状态" value={detail.conversation.user_status || "active"} />
                  {detail.conversation.post_inbound_video_expert_waived_at ? (
                    <Meta
                      label="专家放行"
                      value={`已放行（${formatBeijingDateTime(detail.conversation.post_inbound_video_expert_waived_at)}）`}
                    />
                  ) : null}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  {detail.conversation.user_id ? (
                    <>
                      <a href={`/admin/users/${detail.conversation.user_id}`} className="text-sm text-sky-300 hover:text-sky-200">查看画像</a>
                      <a href={`/admin/data?user_id=${detail.conversation.user_id}`} className="text-sm text-violet-300 hover:text-violet-200">查看归因</a>
                    </>
                  ) : null}
                  {!isFrozen(detail.conversation) && detail.conversation.user_id && (
                    <button
                      type="button"
                      onClick={onFreeze}
                      disabled={freezeLoading}
                      className="rounded-md border border-amber-700 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {freezeLoading ? "冻结中..." : "冻结并停止回复"}
                    </button>
                  )}
                  {detail.conversation.post_inbound_video_expert_release_eligible ? (
                    <button
                      type="button"
                      onClick={onRelease}
                      disabled={releaseLoading}
                      className="rounded-md border border-emerald-700 px-3 py-1.5 text-xs font-medium text-emerald-200 hover:bg-emerald-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {releaseLoading ? "放行中..." : "放行"}
                    </button>
                  ) : null}
                  {isTakenOver(detail.conversation) && !detail.conversation.post_inbound_video_expert_release_eligible ? (
                    <button
                      type="button"
                      onClick={onReleaseHuman}
                      disabled={humanReleaseLoading}
                      className="rounded-md border border-emerald-700 px-3 py-1.5 text-xs font-medium text-emerald-200 hover:bg-emerald-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {humanReleaseLoading ? "放回中..." : "放回 AI"}
                    </button>
                  ) : null}
                  {canRelockPostInboundVideoExpert(detail.conversation) ? (
                    <button
                      type="button"
                      onClick={onRelock}
                      disabled={relockLoading}
                      className="rounded-md border border-violet-700 px-3 py-1.5 text-xs font-medium text-violet-200 hover:bg-violet-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {relockLoading ? "收回中..." : "收回人工"}
                    </button>
                  ) : null}
                  {detail.conversation.user_id ? (
                    <button
                      type="button"
                      onClick={onDeleteAllUserMessages}
                      disabled={deleteLoading}
                      className="rounded-md border border-rose-800 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {deleteLoading ? "删除中..." : "删除该用户全部聊天记录"}
                    </button>
                  ) : null}
                </div>
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
                        <div className="whitespace-pre-wrap break-words">{reply.text}</div>
                        {reply.translation_zh && (
                          <div className="mt-3 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs leading-6 text-amber-100">
                            <div className="mb-1 font-medium text-amber-300">中文参考</div>
                            <div className="whitespace-pre-wrap break-words">{reply.translation_zh}</div>
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                <textarea value={draft} onChange={(event) => onDraftChange(event.target.value)} rows={5} placeholder="选择推荐话术或 AI 建议后，在这里人工修改确认。" className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-3 text-sm text-slate-200 placeholder:text-slate-600" />
                <div className="mt-3 flex justify-end gap-3">
                  <button className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">保存草稿</button>
                  <button
                    type="button"
                    onClick={onConfirmSend}
                    disabled={sendLoading || !draft.trim()}
                    className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {sendLoading ? "发送中..." : "确认发送"}
                  </button>
                </div>
              </Panel>
              <Panel
                title="最近消息"
                action={
                  <button
                    type="button"
                    onClick={onTranslateAllMessages}
                    title={TRANSLATION_PERSISTENCE_BUILD}
                    disabled={translatingMessages || detail.messages.length === 0}
                    className="rounded-md border border-sky-700 px-3 py-2 text-xs font-medium text-sky-200 hover:bg-sky-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {translatingMessages ? "翻译中..." : "翻译全部信息"}
                  </button>
                }
              >
                {translationError && <div className="mb-3 rounded-md border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">{translationError}</div>}
                <div className="space-y-3">
                  {detail.messages.length === 0 && <div className="text-sm text-slate-500">暂无消息</div>}
                  {[...detail.messages].reverse().map((message) => (
                    <MessageBubble
                      key={message.id}
                      message={message}
                      translatedText={messageTranslations[message.id] || usableSavedTranslation(message) || undefined}
                      deleteLoading={deleteLoading}
                      onDelete={() => onDeleteMessage(message.id)}
                    />
                  ))}
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

function MessageBubble({ message, translatedText, deleteLoading, onDelete }: { message: MessageRow; translatedText?: string; deleteLoading: boolean; onDelete: () => void }) {
  const isUser = message.sender_type === "user";
  const isOperator = message.is_operator_message || message.sender_type === "operator";
  const cls = isUser ? "border-slate-700 bg-slate-900" : isOperator ? "border-amber-800 bg-amber-950/30" : "border-violet-800 bg-violet-950/25";
  const label = isUser ? "用户" : isOperator ? "坐席" : "AI";
  return (
    <div className={`rounded-md border px-4 py-3 ${cls}`}>
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>{label}</span>
        <div className="flex items-center gap-3">
          <span>{fmtTime(message.created_at)}</span>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleteLoading}
            className="rounded border border-rose-900 px-2 py-1 text-rose-300 hover:bg-rose-950/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            删除
          </button>
        </div>
      </div>
      <div className="whitespace-pre-wrap break-words text-sm text-slate-100">{message.content || "（空）"}</div>
      {translatedText && (
        <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs leading-6 text-amber-100">
          <div className="mb-1 font-medium text-amber-300">中文参考</div>
          <div className="whitespace-pre-wrap break-words">{translatedText}</div>
        </div>
      )}
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
