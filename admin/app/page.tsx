"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import AuthGate from "@/components/AuthGate";
import OperatorWsStatus from "@/components/OperatorWsStatus";
import { useOperatorTaskWs, type WsUserAlert } from "@/hooks/useOperatorTaskWs";
import { levelBadgeClass, rowPriorityClass, vipToLevelTier } from "@/lib/priorityDisplay";

// ── 类型 ──────────────────────────────────────────────────────────

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

interface ScriptSuggestion {
  id?: string;
  content: string;
  match_score?: number;
  script_type?: string;
}

interface ScriptSuggestionContext {
  language?: string | null;
  loneliness_score?: number | null;
  risk_level?: string | null;
  character_id?: string | null;
  relationship_stage?: string | null;
}

type AudioWindow = typeof window & {
  webkitAudioContext?: typeof AudioContext;
  operatorWs?: WebSocket;
};

interface ListResponse {
  items: ConversationRow[];
  total: number;
  page: number;
  page_size: number;
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

interface DetailResponse {
  conversation: ConversationRow & {
    ai_model_used?: string | null;
    language?: string | null;
    timezone?: string | null;
    chat_style?: string | null;
    interests?: unknown;
    forbidden_topics?: unknown;
  };
  messages: MessageRow[];
}

interface OpsAiSummary {
  user_state: string;
  key_facts: string[];
  risk_flags: string[];
  recommended_strategy: string;
}

interface OpsAiReply {
  rank: number;
  text: string;
  reason: string;
}

interface OpsAiAssistResponse {
  conversation_id: string;
  handoff_task_id: string | null;
  summary: OpsAiSummary;
  suggested_replies: OpsAiReply[];
  model_used?: string | null;
  latency_ms?: number | null;
}

interface TranslationResponse {
  translations: Array<{
    id: string;
    text: string;
  }>;
  model_used?: string | null;
  latency_ms?: number | null;
}

const STATE_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "AI_ACTIVE", label: "AI 活跃" },
  { value: "WAITING_OPERATOR", label: "等待接管" },
  { value: "HUMAN_LOCKED", label: "人工锁定" },
  { value: "CLOSED", label: "已关闭" },
];

// P4-04: SAB 级别排序权重
const LEVEL_PRIORITY: Record<string, number> = {
  "S": 0,
  "A": 1,
  "B": 2,
  "C": 3,
  "D": 4,
};

// P4-04: 状态排序权重
const STATE_PRIORITY: Record<string, number> = {
  "WAITING_OPERATOR": 0,
  "HUMAN_LOCKED": 1,
  "AI_ACTIVE": 2,
  "CLOSED": 3,
};

const CHANNEL_OPTIONS = [
  { value: "", label: "全部渠道" },
  { value: "telegram", label: "Telegram" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "web", label: "Web" },
  { value: "discord", label: "Discord" },
];

const PAGE_SIZE = 20;

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function stateColor(s: string | null): string {
  switch (s) {
    case "AI_ACTIVE":
      return "bg-emerald-900/40 text-emerald-300 border-emerald-800";
    case "WAITING_OPERATOR":
      return "bg-amber-900/40 text-amber-300 border-amber-800";
    case "HUMAN_LOCKED":
      return "bg-violet-900/40 text-violet-300 border-violet-800";
    case "CLOSED":
      return "bg-slate-800 text-slate-400 border-slate-700";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

function riskColor(r: string | null): string {
  switch (r) {
    case "high":
      return "text-rose-400";
    case "elevated":
      return "text-amber-400";
    case "normal":
    default:
      return "text-slate-400";
  }
}

// P4-04: SAB 级别排序函数
function sortConversationsByLevelAndState(
  items: ConversationRow[],
  priorityUserIds?: Set<string>
): ConversationRow[] {
  return [...items].sort((a, b) => {
    // P4-04: 优先处理置顶的 S 级用户
    if (priorityUserIds) {
      const aIsPriority = priorityUserIds.has(a.user_id || "");
      const bIsPriority = priorityUserIds.has(b.user_id || "");
      if (aIsPriority && !bIsPriority) return -1;
      if (!aIsPriority && bIsPriority) return 1;
    }
    
    // 获取等级优先级
    const getLevelPriority = (row: ConversationRow) => {
      const vip = row.vip_level || 0;
      if (vip >= 3) return LEVEL_PRIORITY["S"];
      if (vip >= 2) return LEVEL_PRIORITY["A"];
      if (vip >= 1) return LEVEL_PRIORITY["B"];
      return LEVEL_PRIORITY["C"];
    };
    
    // 获取状态优先级
    const getStatePriority = (row: ConversationRow) => {
      return STATE_PRIORITY[row.state || ""] || 99;
    };
    
    // 1. 按等级排序 (S→A→B→C→D)
    const levelDiff = getLevelPriority(a) - getLevelPriority(b);
    if (levelDiff !== 0) return levelDiff;
    
    // 2. 按状态排序 (WAITING_OPERATOR→HUMAN_LOCKED→AI_ACTIVE→CLOSED)
    const stateDiff = getStatePriority(a) - getStatePriority(b);
    if (stateDiff !== 0) return stateDiff;
    
    // 3. 按 handoff_count 降序
    const handoffDiff = (b.handoff_count || 0) - (a.handoff_count || 0);
    if (handoffDiff !== 0) return handoffDiff;
    
    // 4. 按最后消息时间降序
    const timeA = new Date(a.last_message_at || a.created_at || 0).getTime();
    const timeB = new Date(b.last_message_at || b.created_at || 0).getTime();
    return timeB - timeA;
  });
}

// ── 主页面（内部组件，由 AuthGate 传入 operator） ─────────────────

function DashboardContent({ operator }: { operator: Operator }) {
  // 列表状态
  const [items, setItems] = useState<ConversationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [state, setState] = useState("");
  const [channel, setChannel] = useState("");
  const [search, setSearch] = useState("");
  // 已应用的搜索词；仅在用户点击 [搜索] / [重置] 时更新，避免每个键击都请求
  const [appliedSearch, setAppliedSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 详情抽屉
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [assist, setAssist] = useState<OpsAiAssistResponse | null>(null);
  const [assistLoading, setAssistLoading] = useState(false);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [copiedReplyRank, setCopiedReplyRank] = useState<number | null>(null);
  const [draftReply, setDraftReply] = useState("");
  const [messageTranslations, setMessageTranslations] = useState<Record<string, string>>({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);

  // P4-05: 话术库推荐话术
  const [scriptSuggestions, setScriptSuggestions] = useState<ScriptSuggestion[] | null>(null);
  const [scriptLoading, setScriptLoading] = useState(false);
  const [scriptError, setScriptError] = useState<string | null>(null);

  // P4-04: S 级用户置顶机制
  const [priorityUserIds, setPriorityUserIds] = useState<Set<string>>(new Set());
  const [priorityTimer, setPriorityTimer] = useState<NodeJS.Timeout | null>(null);

  // P4-06: S/A 全屏弹窗 + 声音提醒
  const [alertModal, setAlertModal] = useState<WsUserAlert | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(true);

  // P4-04: 处理 S 级用户置顶
  const handlePriorityUser = useCallback((userId: string) => {
    setPriorityUserIds((prev) => {
      const newSet = new Set(prev);
      newSet.add(userId);
      return newSet;
    });

    // 3 秒后移除置顶状态
    if (priorityTimer) {
      clearTimeout(priorityTimer);
    }
    const timer = setTimeout(() => {
      setPriorityUserIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    }, 3000);
    setPriorityTimer(timer);
  }, [priorityTimer]);

  // P4-06: 播放提醒声音
  const playAlertSound = useCallback(() => {
    if (!audioEnabled) return;
    
    try {
      // 使用 Web Audio API 生成提示音
      const audioCtor = window.AudioContext || (window as AudioWindow).webkitAudioContext;
      if (!audioCtor) return;
      const audioContext = new audioCtor();
      const oscillator = audioContext.createOscillator();
      const gainNode = audioContext.createGain();
      
      oscillator.connect(gainNode);
      gainNode.connect(audioContext.destination);
      
      oscillator.frequency.value = 800; // 频率 800Hz
      oscillator.type = 'sine';
      gainNode.gain.value = 0.3; // 音量
      
      oscillator.start();
      
      // 播放 0.5 秒
      setTimeout(() => {
        oscillator.stop();
        audioContext.close();
      }, 500);
    } catch (e) {
      console.error('Failed to play alert sound:', e);
    }
  }, [audioEnabled]);

  // P4-06: 处理 S/A 级用户弹窗
  const handleUserAlert = useCallback((alert: WsUserAlert) => {
    // 只对 S 和 A 级用户显示弹窗
    if (alert.level !== 'S' && alert.level !== 'A') return;
    
    setAlertModal(alert);
    playAlertSound();
  }, [playAlertSound]);

  // P4-06: 确认弹窗并发送 ACK
  const handleAlertConfirm = useCallback(async () => {
    if (!alertModal) return;
    
    try {
      // 发送 ACK 确认
      const ws = (window as AudioWindow).operatorWs;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'message.ack',
          message_id: alertModal.messageId
        }));
      }
      
      // 查找对应的会话并打开详情
      const targetConversation = items.find(item => item.user_id === alertModal.userId);
      if (targetConversation) {
        await openDetail(targetConversation.conversation_id);
      }
    } catch (e) {
      console.error('Failed to send ACK:', e);
    }
    
    setAlertModal(null);
  }, [alertModal, items, openDetail]);

  // P4-06: 忽略弹窗
  const handleAlertDismiss = useCallback(() => {
    setAlertModal(null);
  }, []);

  // P4-05: 获取话术库推荐话术
  const loadScriptSuggestions = useCallback(async (conversationData: ScriptSuggestionContext | null) => {
    if (!conversationData) return;
    
    setScriptLoading(true);
    setScriptError(null);
    try {
      const body: Record<string, unknown> = {
        language: conversationData.language || "en",
        loneliness_score: conversationData.loneliness_score || 50,
        risk_level: conversationData.risk_level || "low",
        limit: 5,
      };
      
      if (conversationData.character_id) {
        body.character_id = conversationData.character_id;
      }
      if (conversationData.relationship_stage) {
        body.relationship_stage = conversationData.relationship_stage;
      }
      
      const resp = await apiFetch<{ items: ScriptSuggestion[] }>("/scripts/suggest", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setScriptSuggestions(resp.items || []);
    } catch (e) {
      setScriptError(e instanceof Error ? e.message : String(e));
      setScriptSuggestions([]);
    } finally {
      setScriptLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (state) qs.set("state", state);
      if (channel) qs.set("channel", channel);
      if (appliedSearch.trim()) qs.set("search", appliedSearch.trim());
      const resp = await apiFetch<ListResponse>(
        `/admin/conversations?${qs.toString()}`
      );
      // P4-04: 应用 SAB 级别排序，包含置顶用户处理
      const sortedItems = sortConversationsByLevelAndState(resp.items, priorityUserIds);
      setItems(sortedItems);
      setTotal(resp.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, state, channel, appliedSearch, priorityUserIds]);

  useEffect(() => {
    load();
  }, [load]);

  const { connState, lastAlert, dismissAlert, reconnect, lastUpgrade, dismissUpgrade, lastAlertModal, dismissAlertModal } = useOperatorTaskWs({
    operatorId: operator.operator_id,
    onTaskUpsert: (task) => {
      if (task.priority === "P0" || task.priority === "P1") {
        setState("WAITING_OPERATOR");
        setPage(1);
      }
    },
    // P4-04: 处理用户升级事件，S 级用户 3 秒置顶
    onUserUpgraded: (upgrade) => {
      if (upgrade.newLevel === "S") {
        handlePriorityUser(upgrade.userId);
        // 重新加载列表以应用新的排序
        load();
      }
    },
    // P4-06: 处理 S/A 级用户提醒事件
    onUserAlert: (alert) => {
      handleUserAlert(alert);
    },
  });

  function closeDetail() {
    if (draftReply.trim()) {
      const ok = window.confirm("有未发送的回复草稿，确定关闭详情？");
      if (!ok) return;
    }
    setDetail(null);
    setDetailError(null);
    setAssist(null);
    setAssistError(null);
    setDraftReply("");
    setMessageTranslations({});
    setTranslationError(null);
  }

  async function openDetail(cid: string) {
    setDetail(null);
    setDetailError(null);
    setAssist(null);
    setAssistError(null);
    setDraftReply("");
    setMessageTranslations({});
    setTranslationError(null);
    setDetailLoading(true);
    setScriptSuggestions(null); // P4-05: 重置话术推荐
    try {
      const resp = await apiFetch<DetailResponse>(
        `/admin/conversations/${cid}`
      );
      setDetail(resp);
      void translateMessages(resp);
      // P4-05: 加载话术库推荐话术
      void loadScriptSuggestions(resp.conversation);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  }

  async function translateMessages(resp: DetailResponse) {
    const items = resp.messages
      .filter((m) => (m.content || "").trim())
      .map((m) => ({
        id: m.id,
        text: m.content || "",
        sender_type: m.sender_type,
      }));
    if (items.length === 0) {
      setMessageTranslations({});
      return;
    }

    setTranslationLoading(true);
    setTranslationError(null);
    try {
      const preserveTerms = [
        resp.conversation.nickname,
        resp.conversation.external_id,
      ].filter((v): v is string => !!v && v.trim().length > 0);
      const translated = await apiFetch<TranslationResponse>("/ops-ai/translate", {
        method: "POST",
        body: JSON.stringify({
          target_language: "zh-CN",
          preserve_terms: preserveTerms,
          items,
        }),
      });
      setMessageTranslations(
        Object.fromEntries(
          translated.translations.map((item) => [item.id, item.text])
        )
      );
    } catch (e) {
      setTranslationError(e instanceof Error ? e.message : String(e));
      setMessageTranslations({});
    } finally {
      setTranslationLoading(false);
    }
  }

  async function generateAssist() {
    if (!detail) return;
    setAssistLoading(true);
    setAssistError(null);
    try {
      const resp = await apiFetch<OpsAiAssistResponse>(
        `/ops-ai/conversations/${detail.conversation.conversation_id}/assist`,
        {
          method: "POST",
          body: JSON.stringify({
            language: detail.conversation.language || "zh-CN",
            tone: "warm",
            max_context_messages: 30,
          }),
        }
      );
      setAssist(resp);
    } catch (e) {
      setAssistError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssistLoading(false);
    }
  }

  async function copyReply(reply: OpsAiReply) {
    await navigator.clipboard.writeText(reply.text);
    setCopiedReplyRank(reply.rank);
    window.setTimeout(() => setCopiedReplyRank(null), 1500);
  }

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setAppliedSearch(search);
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-400 text-sm">运营后台</span>
          <nav className="flex items-center gap-1 ml-4">
            <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
              会话
            </span>
            <a
              href="/admin/memories"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              记忆
            </a>
            <a
              href="/admin/scripts"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              话术库
            </a>
            <a
              href="/admin/characters"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              角色
            </a>
            <a
              href="/admin/push"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              推送
            </a>
            <a
              href="/admin/telegram-accounts"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              TG账号
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-4 flex-wrap justify-end">
          <OperatorWsStatus
            connState={connState}
            lastAlert={lastAlert}
            onDismissAlert={dismissAlert}
            onReconnect={reconnect}
          />
          {/* P4-06: 声音提醒开关 */}
          <button
            onClick={() => setAudioEnabled(!audioEnabled)}
            className={`text-sm transition ${audioEnabled ? 'text-violet-300' : 'text-slate-500'}`}
            title={audioEnabled ? "声音提醒已开启" : "声音提醒已关闭"}
          >
            {audioEnabled ? '🔊' : '🔇'}
          </button>
          <span className="text-sm text-slate-300">
            {operator.display_name || operator.username}
            <span className="ml-2 text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
              {operator.role}
            </span>
          </span>
          <button
            onClick={handleLogout}
            className="text-sm text-slate-400 hover:text-white transition"
          >
            退出
          </button>
        </div>
      </header>

      {/* P4-04: S 级用户升级通知横幅 */}
      {lastUpgrade && lastUpgrade.newLevel === "S" && (
        <div className="bg-rose-900/40 border border-rose-700 text-rose-200 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🎉</span>
            <div>
              <div className="font-semibold">用户升级为 S 级</div>
              <div className="text-sm text-rose-300">
                用户从 {lastUpgrade.previousLevel} 级升级到 S 级，已自动置顶 3 秒
              </div>
            </div>
          </div>
          <button
            onClick={dismissUpgrade}
            className="text-rose-300 hover:text-white transition"
          >
            ✕
          </button>
        </div>
      )}

      {/* P4-06: S/A 全屏弹窗 */}
      {alertModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-slate-800 border-2 border-violet-500 rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl">
            <div className="text-center">
              <div className="text-6xl mb-4">
                {alertModal.level === 'S' ? '⭐' : '🔔'}
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">
                {alertModal.level === 'S' ? 'S 级用户提醒' : 'A 级用户提醒'}
              </h2>
              <div className="bg-slate-900 rounded-lg p-4 mb-6">
                <div className="text-slate-300 mb-2">
                  <span className="text-slate-500">用户：</span>
                  <span className="text-white font-medium">
                    {alertModal.nickname || alertModal.externalId || '未知'}
                  </span>
                </div>
                <div className="text-slate-300 mb-2">
                  <span className="text-slate-500">等级：</span>
                  <span className={`font-bold ${alertModal.level === 'S' ? 'text-yellow-400' : 'text-violet-400'}`}>
                    {alertModal.level} 级
                  </span>
                </div>
                <div className="text-slate-300">
                  <span className="text-slate-500">原因：</span>
                  <span className="text-slate-200">{alertModal.reason}</span>
                </div>
              </div>
              <div className="flex gap-3 justify-center">
                <button
                  onClick={handleAlertDismiss}
                  className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition font-medium"
                >
                  稍后处理
                </button>
                <button
                  onClick={handleAlertConfirm}
                  className="px-6 py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition font-medium"
                >
                  立即查看
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main */}
      <main className="p-8 max-w-7xl mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold mb-1">会话总览</h1>
            <p className="text-slate-400 text-sm">
              共 {total} 条会话 · 第 {page} / {totalPages} 页
            </p>
          </div>
          <div>
            <a
              href="/admin/operator-dashboard"
              className="px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium transition"
            >
              坐席看板
            </a>
          </div>
        </div>

        {/* Filters */}
        <form
          onSubmit={handleSearchSubmit}
          className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex flex-wrap items-center gap-3"
        >
          <select
            value={state}
            onChange={(e) => {
              setPage(1);
              setState(e.target.value);
            }}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {STATE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            value={channel}
            onChange={(e) => {
              setPage(1);
              setChannel(e.target.value);
            }}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {CHANNEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索昵称 / external_id"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 flex-1 min-w-[200px]"
          />
          <button
            type="submit"
            className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
          >
            搜索
          </button>
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setAppliedSearch("");
              setState("");
              setChannel("");
              setPage(1);
            }}
            className="text-slate-400 hover:text-white text-sm transition"
          >
            重置
          </button>
          <button
            type="button"
            onClick={() => {
              setPage(1);
              setState("WAITING_OPERATOR");
            }}
            className="text-amber-300 hover:text-amber-100 text-sm border border-amber-800 px-3 py-2 rounded-md"
          >
            待接管
          </button>
        </form>

        {/* Error */}
        {error && (
          <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4 flex items-center justify-between gap-3">
            <span>加载失败：{error}</span>
            <button
              type="button"
              onClick={() => load()}
              className="text-xs underline whitespace-nowrap"
            >
              重试
            </button>
          </div>
        )}

        {/* Table */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3 font-medium">用户</th>
                <th className="text-left px-4 py-3 font-medium">等级</th>
                <th className="text-left px-4 py-3 font-medium">渠道</th>
                <th className="text-left px-4 py-3 font-medium">状态</th>
                <th className="text-left px-4 py-3 font-medium">角色</th>
                <th className="text-right px-4 py-3 font-medium">孤独感分</th>
                <th className="text-left px-4 py-3 font-medium">风险</th>
                <th className="text-left px-4 py-3 font-medium">最后消息</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60">
              {loading && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-4 py-8 text-center text-slate-500"
                  >
                    加载中…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-4 py-12 text-center text-slate-500"
                  >
                    暂无会话
                  </td>
                </tr>
              )}
              {!loading &&
                items.map((row) => {
                  const tier = vipToLevelTier(row.vip_level);
                  return (
                  <tr
                    key={row.conversation_id}
                    className={`hover:bg-slate-700/30 transition ${rowPriorityClass(row.state, row.vip_level)}`}
                  >
                    <td className="px-4 py-3">
                      <div className="text-slate-100">
                        {row.nickname || (
                          <span className="text-slate-500 italic">未命名</span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 font-mono">
                        {row.external_id || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${levelBadgeClass(tier)}`}
                      >
                        {tier}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {row.channel || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${stateColor(
                          row.state
                        )}`}
                      >
                        {row.state || "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {row.character_name || "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                      {row.loneliness_score != null
                        ? row.loneliness_score.toFixed(1)
                        : "—"}
                    </td>
                    <td className={`px-4 py-3 ${riskColor(row.risk_level)}`}>
                      {row.risk_level || "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {fmtTime(row.last_message_at || row.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                      {row.user_id && (
                        <a
                          href={`/admin/users/${row.user_id}`}
                          className="text-sky-400 hover:text-sky-300 text-xs"
                          title="用户画像"
                        >
                          画像
                        </a>
                      )}
                      <button
                        onClick={() => openDetail(row.conversation_id)}
                        className="text-violet-400 hover:text-violet-300 text-xs"
                      >
                        详情
                      </button>
                    </td>
                  </tr>
                  );
                })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-4 text-sm">
          <span className="text-slate-500">
            第 {page} / {totalPages} 页
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="px-3 py-1.5 border border-slate-700 rounded-md text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              上一页
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="px-3 py-1.5 border border-slate-700 rounded-md text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              下一页
            </button>
          </div>
        </div>
      </main>

      {/* 详情抽屉 */}
      {(detail || detailLoading || detailError) && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex justify-end"
          onClick={closeDetail}
        >
          <div
            className="w-full max-w-2xl bg-slate-900 h-full border-l border-slate-700 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">会话详情</h2>
              <button
                onClick={closeDetail}
                className="text-slate-400 hover:text-white"
                title="关闭（有草稿时会确认）"
              >
                ✕
              </button>
            </div>

            <div className="p-6 space-y-6">
              {detailLoading && (
                <p className="text-slate-500 text-sm">加载中…</p>
              )}
              {detailError && (
                <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
                  {detailError}
                </div>
              )}
              {detail && (
                <>
                  {/* 元信息 */}
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <Meta label="昵称" value={detail.conversation.nickname} />
                    <Meta
                      label="外部 ID"
                      value={detail.conversation.external_id}
                      mono
                    />
                    <Meta label="渠道" value={detail.conversation.channel} />
                    <Meta label="状态" value={detail.conversation.state} />
                    <Meta
                      label="角色"
                      value={detail.conversation.character_name}
                    />
                    <Meta
                      label="AI 模型"
                      value={detail.conversation.ai_model_used}
                    />
                    <Meta
                      label="孤独感分"
                      value={
                        detail.conversation.loneliness_score != null
                          ? detail.conversation.loneliness_score.toFixed(1)
                          : null
                      }
                    />
                    <Meta
                      label="风险等级"
                      value={detail.conversation.risk_level}
                    />
                    <Meta
                      label="关系阶段"
                      value={detail.conversation.relationship_stage}
                    />
                    <Meta
                      label="VIP 等级"
                      value={
                        detail.conversation.vip_level != null
                          ? String(detail.conversation.vip_level)
                          : null
                      }
                    />
                    <Meta
                      label="创建时间"
                      value={fmtTime(detail.conversation.created_at)}
                    />
                    <Meta
                      label="最后消息"
                      value={fmtTime(detail.conversation.last_message_at)}
                    />
                  </div>

                  {/* 快捷导航 */}
                  {detail.conversation.user_id && (
                    <div className="flex gap-3">
                      <a
                        href={`/admin/users/${detail.conversation.user_id}`}
                        className="text-sm text-sky-400 hover:text-sky-300 transition"
                      >
                        查看画像
                      </a>
                      <a
                        href={`/admin/memories?user_id=${detail.conversation.user_id}`}
                        className="text-sm text-violet-400 hover:text-violet-300 transition"
                      >
                        查看记忆
                      </a>
                    </div>
                  )}

                  {/* AI 辅助 */}
                  <div className="border border-violet-800/70 bg-violet-950/20 rounded-xl p-4 space-y-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-sm font-medium text-violet-200">
                          AI 辅助：摘要 + 3 条推荐回复
                        </h3>
                        <p className="text-xs text-slate-400 mt-1">
                          仅供人工参考，不会自动发送消息。
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={generateAssist}
                        disabled={assistLoading}
                        className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium px-3 py-2 rounded-md transition whitespace-nowrap"
                      >
                        {assistLoading ? "生成中…" : assist ? "重新生成" : "生成建议"}
                      </button>
                    </div>

                    {assistError && (
                      <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-3 py-2 flex items-center justify-between gap-3">
                        <span>生成失败：{assistError}</span>
                        <button
                          type="button"
                          onClick={generateAssist}
                          disabled={assistLoading}
                          className="text-xs text-rose-100 hover:text-white underline"
                        >
                          重试
                        </button>
                      </div>
                    )}

                    {assist && (
                      <>
                        <div className="grid gap-3 text-sm">
                          <AssistBlock
                            label="用户当前状态"
                            value={assist.summary.user_state}
                          />
                          <AssistList
                            label="关键事实"
                            items={assist.summary.key_facts}
                          />
                          <AssistList
                            label="风险 flags"
                            items={assist.summary.risk_flags}
                            empty="暂无明显风险"
                          />
                          <AssistBlock
                            label="推荐处理策略"
                            value={assist.summary.recommended_strategy}
                          />
                        </div>

                        <div className="space-y-3">
                          {assist.suggested_replies.map((reply) => (
                            <div
                              key={reply.rank}
                              className="border border-slate-700 bg-slate-900/70 rounded-lg p-3"
                            >
                              <div className="flex items-center justify-between gap-3 mb-2">
                                <span className="text-xs text-violet-300">
                                  推荐回复 {reply.rank}
                                </span>
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    onClick={() => copyReply(reply)}
                                    className="text-xs text-sky-400 hover:text-sky-300"
                                  >
                                    {copiedReplyRank === reply.rank ? "已复制" : "复制"}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setDraftReply(reply.text)}
                                    className="text-xs text-violet-400 hover:text-violet-300"
                                  >
                                    填入草稿
                                  </button>
                                </div>
                              </div>
                              <p className="text-sm text-slate-100 whitespace-pre-wrap">
                                {reply.text}
                              </p>
                              {reply.reason && (
                                <p className="text-xs text-slate-500 mt-2">
                                  理由：{reply.reason}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>

                        <div>
                          <label className="block text-xs text-slate-400 mb-2">
                            运营回复草稿（需人工确认后再发送）
                          </label>
                          <textarea
                            value={draftReply}
                            onChange={(e) => setDraftReply(e.target.value)}
                            rows={4}
                            placeholder="点击“填入草稿”后可在这里编辑；当前页面不会自动发送。"
                            className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-100 placeholder-slate-600"
                          />
                          {/* P4-05: 发送按钮 */}
                          {draftReply.trim() && (
                            <div className="mt-2 flex justify-end">
                              <button
                                onClick={async () => {
                                  // TODO: 实现发送功能
                                  alert("发送功能待实现 - 需要集成 handoff API");
                                }}
                                className="bg-green-600 hover:bg-green-500 text-white text-xs font-medium px-4 py-2 rounded-md transition"
                              >
                                发送
                              </button>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </div>

                  {/* P4-05: 话术库推荐话术 */}
                  <div className="border border-sky-800/70 bg-sky-950/20 rounded-xl p-4 space-y-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-sm font-medium text-sky-200">
                          话术库推荐话术
                        </h3>
                        <p className="text-xs text-slate-400 mt-1">
                          基于当前用户画像匹配的推荐话术，可一键插入或编辑后发送。
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          if (detail) void loadScriptSuggestions(detail.conversation);
                        }}
                        disabled={scriptLoading}
                        className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium px-3 py-2 rounded-md transition whitespace-nowrap"
                      >
                        {scriptLoading ? "加载中…" : "刷新推荐"}
                      </button>
                    </div>

                    {scriptError && (
                      <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-3 py-2">
                        加载失败：{scriptError}
                      </div>
                    )}

                    {scriptSuggestions && scriptSuggestions.length > 0 ? (
                      <div className="space-y-3">
                        {scriptSuggestions.map((script, index) => (
                          <div
                            key={script.id || index}
                            className="border border-slate-700 bg-slate-900/70 rounded-lg p-3"
                          >
                            <div className="flex items-center justify-between gap-3 mb-2">
                              <span className="text-xs text-sky-300">
                                推荐话术 {index + 1}
                                {script.match_score && (
                                  <span className="ml-2 text-slate-500">
                                    (匹配度: {Math.round(script.match_score * 100)}%)
                                  </span>
                                )}
                              </span>
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => setDraftReply(script.content || "")}
                                  className="text-xs text-sky-400 hover:text-sky-300"
                                >
                                  填入草稿
                                </button>
                              </div>
                            </div>
                            <p className="text-sm text-slate-100 whitespace-pre-wrap">
                              {script.content}
                            </p>
                            {script.script_type && (
                              <p className="text-xs text-slate-500 mt-2">
                                类型: {script.script_type}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-sm text-slate-500 text-center py-4">
                        {scriptLoading ? "加载中..." : "暂无推荐话术"}
                      </div>
                    )}
                  </div>

                  {/* 消息流 */}
                  <div>
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <h3 className="text-sm font-medium text-slate-300">
                        最近消息（中文展示，最多 50 条）
                      </h3>
                      {translationLoading && (
                        <span className="text-xs text-slate-500">正在翻译…</span>
                      )}
                    </div>
                    {translationError && (
                      <div className="bg-amber-900/20 border border-amber-800 text-amber-200 text-xs rounded-md px-3 py-2 mb-3">
                        翻译失败，当前显示原文：{translationError}
                      </div>
                    )}
                    {detail.messages.length === 0 ? (
                      <p className="text-slate-500 text-sm">暂无消息</p>
                    ) : (
                      <div className="space-y-3">
                        {[...detail.messages].reverse().map((m) => (
                          <MessageBubble
                            key={m.id}
                            msg={m}
                            translatedContent={messageTranslations[m.id]}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 页面入口（AuthGate 包裹，守卫由 AuthGate 统一处理） ───────────

export default function DashboardPage() {
  return (
    <AuthGate>
      {(operator) => <DashboardContent operator={operator} />}
    </AuthGate>
  );
}

// ── 小组件 ────────────────────────────────────────────────────────

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div
        className={`text-slate-200 ${mono ? "font-mono text-xs" : ""}`}
      >
        {value || <span className="text-slate-600">—</span>}
      </div>
    </div>
  );
}

function AssistBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className="text-slate-200">{value || "—"}</div>
    </div>
  );
}

function AssistList({
  label,
  items,
  empty = "—",
}: {
  label: string;
  items: string[];
  empty?: string;
}) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      {items.length === 0 ? (
        <div className="text-slate-500">{empty}</div>
      ) : (
        <ul className="list-disc list-inside text-slate-200 space-y-1">
          {items.map((item, idx) => (
            <li key={`${item}-${idx}`}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MessageBubble({
  msg,
  translatedContent,
}: {
  msg: MessageRow;
  translatedContent?: string;
}) {
  const isUser = msg.sender_type === "user";
  const isAssistant = msg.sender_type === "assistant" || msg.sender_type === "ai";
  const isOperator =
    msg.is_operator_message || msg.sender_type === "operator";
  const originalContent = msg.content || "";
  const displayContent = translatedContent || originalContent;
  const hasTranslated =
    !!translatedContent && translatedContent.trim() !== originalContent.trim();

  let bg = "bg-slate-800 border-slate-700";
  let label = msg.sender_type || "unknown";

  if (isUser) {
    bg = "bg-slate-800 border-slate-700";
    label = "用户";
  } else if (isOperator) {
    bg = "bg-amber-900/30 border-amber-800";
    label = "运营";
  } else if (isAssistant) {
    bg = "bg-violet-900/30 border-violet-800";
    label = msg.model_name ? `AI · ${msg.model_name}` : "AI";
  }

  return (
    <div className={`border rounded-lg px-4 py-3 ${bg}`}>
      <div className="flex items-center justify-between text-xs mb-2">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-500">{fmtTime(msg.created_at)}</span>
      </div>
      <div className="text-slate-100 text-sm whitespace-pre-wrap break-words">
        {displayContent || <span className="text-slate-500 italic">（空）</span>}
      </div>
      {hasTranslated && (
        <details className="mt-2 text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">
            查看原文
          </summary>
          <div className="mt-1 whitespace-pre-wrap break-words text-slate-400">
            {originalContent}
          </div>
        </details>
      )}
    </div>
  );
}
