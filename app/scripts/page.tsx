"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiFetch, clearAuth, LOGIN_PATH, Operator } from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型 ─────────────────────────────────────────────────────────

interface Script {
  id: string;
  character_id: string | null;
  language: string;
  relationship_stage: string | null;
  emotion_state: string | null;
  loneliness_score_min: number;
  loneliness_score_max: number;
  script_type: string | null;
  content: string;
  risk_level: string;
  conversion_goal: string | null;
  review_status: string;
  forbidden_scenarios: unknown[];
  created_at: string;
  updated_at: string;
}

interface SuggestItem extends Script {
  match_score: number;
}

interface ScriptListResp {
  items: Script[];
  limit: number;
  offset: number;
}

interface SuggestResp {
  items: SuggestItem[];
}

// ── 工具函数 ─────────────────────────────────────────────────────

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function statusColor(s: string): string {
  switch (s) {
    case "approved":
      return "bg-emerald-900/40 text-emerald-300 border-emerald-800";
    case "draft":
      return "bg-amber-900/40 text-amber-300 border-amber-800";
    case "archived":
      return "bg-slate-800 text-slate-400 border-slate-700";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

function riskColor(r: string): string {
  switch (r) {
    case "high":
      return "text-rose-400";
    case "medium":
      return "text-amber-400";
    default:
      return "text-emerald-400";
  }
}

// ── 空表单 ───────────────────────────────────────────────────────

const EMPTY_FORM = {
  language: "en",
  relationship_stage: "",
  emotion_state: "",
  loneliness_score_min: 0,
  loneliness_score_max: 100,
  script_type: "",
  content: "",
  risk_level: "low",
  conversion_goal: "",
  review_status: "draft",
};

// ── Nav header ───────────────────────────────────────────────────

function NavHeader({
  operator,
  onLogout,
}: {
  operator: Operator;
  onLogout: () => void;
}) {
  return (
    <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xl font-bold text-violet-400">ERIS</span>
        <span className="text-slate-400 text-sm">运营后台</span>
        <nav className="flex items-center gap-1 ml-4">
          <a
            href="/admin"
            className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
          >
            会话
          </a>
          <a
            href="/admin/memories"
            className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
          >
            记忆
          </a>
          <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
            话术库
          </span>
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm text-slate-300">
          {operator.display_name || operator.username}
          <span className="ml-2 text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
            {operator.role}
          </span>
        </span>
        <button
          onClick={onLogout}
          className="text-sm text-slate-400 hover:text-white transition"
        >
          退出
        </button>
      </div>
    </header>
  );
}

// ── 话术表单 Modal ───────────────────────────────────────────────

function ScriptModal({
  title,
  initial,
  onSave,
  onClose,
  saving,
}: {
  title: string;
  initial: typeof EMPTY_FORM;
  onSave: (data: typeof EMPTY_FORM) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState(initial);

  function set(k: keyof typeof EMPTY_FORM, v: string | number) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition text-xl"
          >
            ×
          </button>
        </div>
        <div className="p-6 space-y-4">
          {/* content */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">
              内容 <span className="text-rose-400">*</span>
            </label>
            <textarea
              rows={4}
              value={form.content}
              onChange={(e) => set("content", e.target.value)}
              placeholder="话术正文内容…"
              className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 resize-none"
            />
          </div>
          {/* language + script_type */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">语言</label>
              <input
                value={form.language}
                onChange={(e) => set("language", e.target.value)}
                placeholder="en"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                script_type
              </label>
              <input
                value={form.script_type}
                onChange={(e) => set("script_type", e.target.value)}
                placeholder="reply / proactive / …"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
          </div>
          {/* relationship_stage + emotion_state */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                relationship_stage
              </label>
              <input
                value={form.relationship_stage}
                onChange={(e) => set("relationship_stage", e.target.value)}
                placeholder="S1 / S2 / S3 / …"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                emotion_state
              </label>
              <input
                value={form.emotion_state}
                onChange={(e) => set("emotion_state", e.target.value)}
                placeholder="lonely / happy / …"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
          </div>
          {/* loneliness_score range */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                loneliness_score_min
              </label>
              <input
                type="number"
                min={0}
                max={100}
                value={form.loneliness_score_min}
                onChange={(e) =>
                  set("loneliness_score_min", Number(e.target.value))
                }
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                loneliness_score_max
              </label>
              <input
                type="number"
                min={0}
                max={100}
                value={form.loneliness_score_max}
                onChange={(e) =>
                  set("loneliness_score_max", Number(e.target.value))
                }
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
          </div>
          {/* risk_level + conversion_goal + review_status */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                risk_level
              </label>
              <select
                value={form.risk_level}
                onChange={(e) => set("risk_level", e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                conversion_goal
              </label>
              <input
                value={form.conversion_goal}
                onChange={(e) => set("conversion_goal", e.target.value)}
                placeholder="retain / upsell / …"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                review_status
              </label>
              <select
                value={form.review_status}
                onChange={(e) => set("review_status", e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              >
                <option value="draft">draft</option>
                <option value="approved">approved</option>
                <option value="archived">archived</option>
              </select>
            </div>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="text-sm text-slate-400 hover:text-white px-4 py-2 rounded-md border border-slate-700 hover:border-slate-500 transition"
          >
            取消
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={saving || !form.content.trim()}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Suggest Panel ────────────────────────────────────────────────

function SuggestPanel({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    language: "en",
    relationship_stage: "",
    emotion_state: "",
    loneliness_score: "",
    script_type: "",
    risk_level: "",
    conversion_goal: "",
    limit: 5,
  });
  const [results, setResults] = useState<SuggestItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { language: form.language, limit: form.limit };
      if (form.relationship_stage) body.relationship_stage = form.relationship_stage;
      if (form.emotion_state) body.emotion_state = form.emotion_state;
      if (form.loneliness_score !== "") body.loneliness_score = Number(form.loneliness_score);
      if (form.script_type) body.script_type = form.script_type;
      if (form.risk_level) body.risk_level = form.risk_level;
      if (form.conversion_goal) body.conversion_goal = form.conversion_goal;
      const data = await apiFetch<SuggestResp>("/scripts/suggest", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResults(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function setF(k: keyof typeof form, v: string | number) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Suggest Preview</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition text-xl"
          >
            ×
          </button>
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">语言</label>
              <input
                value={form.language}
                onChange={(e) => setF("language", e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                loneliness_score
              </label>
              <input
                type="number"
                min={0}
                max={100}
                value={form.loneliness_score}
                onChange={(e) => setF("loneliness_score", e.target.value)}
                placeholder="0–100（留空不限）"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                relationship_stage
              </label>
              <input
                value={form.relationship_stage}
                onChange={(e) => setF("relationship_stage", e.target.value)}
                placeholder="留空不限"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                emotion_state
              </label>
              <input
                value={form.emotion_state}
                onChange={(e) => setF("emotion_state", e.target.value)}
                placeholder="留空不限"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                script_type
              </label>
              <input
                value={form.script_type}
                onChange={(e) => setF("script_type", e.target.value)}
                placeholder="留空不限"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                risk_level
              </label>
              <select
                value={form.risk_level}
                onChange={(e) => setF("risk_level", e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              >
                <option value="">不限</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                conversion_goal
              </label>
              <input
                value={form.conversion_goal}
                onChange={(e) => setF("conversion_goal", e.target.value)}
                placeholder="留空不限"
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">limit</label>
              <input
                type="number"
                min={1}
                max={20}
                value={form.limit}
                onChange={(e) => setF("limit", Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
              />
            </div>
          </div>
          <button
            onClick={run}
            disabled={loading}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
          >
            {loading ? "查询中…" : "运行 Suggest"}
          </button>

          {error && (
            <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
              {error}
            </div>
          )}

          {results.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                返回 {results.length} 条（仅展示，不会插入运营回复框）
              </p>
              {results.map((item) => (
                <div
                  key={item.id}
                  className="bg-slate-900 rounded-lg border border-slate-700 p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`inline-block px-2 py-0.5 text-xs rounded-full border ${statusColor(item.review_status)}`}
                    >
                      {item.review_status}
                    </span>
                    <span className="text-xs text-slate-500">
                      match_score:{" "}
                      <span className="text-violet-300 font-mono font-semibold">
                        {item.match_score}
                      </span>
                    </span>
                    <span className="text-xs text-slate-600 font-mono">
                      {item.id.slice(0, 8)}
                    </span>
                  </div>
                  <p className="text-sm text-slate-200">{item.content}</p>
                </div>
              ))}
            </div>
          )}

          {!loading && results.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-4">
              点击「运行 Suggest」查看匹配话术
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 主内容 ───────────────────────────────────────────────────────

function ScriptsContent() {
  // 筛选状态
  const [filterLang, setFilterLang] = useState("");
  const [filterStage, setFilterStage] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  // 列表状态
  const [scripts, setScripts] = useState<Script[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const LIMIT = 50;

  // Modal 状态
  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<Script | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Script | null>(null);
  const [showSuggest, setShowSuggest] = useState(false);
  const [saving, setSaving] = useState(false);

  // 展开内容
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (filterLang) qs.set("language", filterLang);
      if (filterStage) qs.set("relationship_stage", filterStage);
      if (filterType) qs.set("script_type", filterType);
      if (filterStatus) qs.set("review_status", filterStatus);
      qs.set("limit", String(LIMIT));
      qs.set("offset", String(offset));
      const data = await apiFetch<ScriptListResp>(`/scripts?${qs}`);
      setScripts(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [filterLang, filterStage, filterType, filterStatus, offset]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate(form: typeof EMPTY_FORM) {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        language: form.language,
        content: form.content,
        risk_level: form.risk_level,
        review_status: form.review_status,
        loneliness_score_min: form.loneliness_score_min,
        loneliness_score_max: form.loneliness_score_max,
        forbidden_scenarios: [],
      };
      if (form.relationship_stage) body.relationship_stage = form.relationship_stage;
      if (form.emotion_state) body.emotion_state = form.emotion_state;
      if (form.script_type) body.script_type = form.script_type;
      if (form.conversion_goal) body.conversion_goal = form.conversion_goal;
      await apiFetch("/scripts", { method: "POST", body: JSON.stringify(body) });
      setShowCreate(false);
      setOffset(0);
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleEdit(form: typeof EMPTY_FORM) {
    if (!editTarget) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        language: form.language,
        content: form.content,
        risk_level: form.risk_level,
        review_status: form.review_status,
        loneliness_score_min: form.loneliness_score_min,
        loneliness_score_max: form.loneliness_score_max,
      };
      if (form.relationship_stage !== undefined) body.relationship_stage = form.relationship_stage || null;
      if (form.emotion_state !== undefined) body.emotion_state = form.emotion_state || null;
      if (form.script_type !== undefined) body.script_type = form.script_type || null;
      if (form.conversion_goal !== undefined) body.conversion_goal = form.conversion_goal || null;
      await apiFetch(`/scripts/${editTarget.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setEditTarget(null);
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setSaving(true);
    try {
      await apiFetch(`/scripts/${deleteTarget.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function editFormFromScript(s: Script): typeof EMPTY_FORM {
    return {
      language: s.language,
      relationship_stage: s.relationship_stage ?? "",
      emotion_state: s.emotion_state ?? "",
      loneliness_score_min: s.loneliness_score_min,
      loneliness_score_max: s.loneliness_score_max,
      script_type: s.script_type ?? "",
      content: s.content,
      risk_level: s.risk_level,
      conversion_goal: s.conversion_goal ?? "",
      review_status: s.review_status,
    };
  }

  return (
    <main className="p-8 max-w-7xl mx-auto">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold mb-1">话术库</h1>
          <p className="text-slate-400 text-sm">管理运营话术，支持筛选、新建、编辑、删除与 Suggest 预览</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSuggest(true)}
            className="text-sm text-violet-300 border border-violet-700 hover:bg-violet-900/30 px-4 py-2 rounded-md transition"
          >
            Suggest Preview
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
          >
            + 新建话术
          </button>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="text-xs text-slate-400 block mb-1">语言</label>
          <input
            value={filterLang}
            onChange={(e) => { setFilterLang(e.target.value); setOffset(0); }}
            placeholder="en / zh / …"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 w-28"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">阶段</label>
          <input
            value={filterStage}
            onChange={(e) => { setFilterStage(e.target.value); setOffset(0); }}
            placeholder="S1 / S2 / …"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 w-28"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">类型</label>
          <input
            value={filterType}
            onChange={(e) => { setFilterType(e.target.value); setOffset(0); }}
            placeholder="reply / …"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 w-28"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">状态</label>
          <select
            value={filterStatus}
            onChange={(e) => { setFilterStatus(e.target.value); setOffset(0); }}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 w-32"
          >
            <option value="">全部</option>
            <option value="draft">draft</option>
            <option value="approved">approved</option>
            <option value="archived">archived</option>
          </select>
        </div>
        <button
          onClick={() => { setFilterLang(""); setFilterStage(""); setFilterType(""); setFilterStatus(""); setOffset(0); }}
          className="text-sm text-slate-400 hover:text-white transition self-end pb-2"
        >
          重置
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
          加载失败：{error}
        </div>
      )}

      {/* 摘要 */}
      {!loading && !error && (
        <div className="text-xs text-slate-500 mb-3">
          显示 {scripts.length} 条（limit={LIMIT}, offset={offset}）
        </div>
      )}

      {/* 表格 */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3 font-medium">状态</th>
              <th className="text-left px-4 py-3 font-medium">语言 / 阶段 / 类型</th>
              <th className="text-left px-4 py-3 font-medium">内容</th>
              <th className="text-left px-4 py-3 font-medium whitespace-nowrap">risk</th>
              <th className="text-left px-4 py-3 font-medium whitespace-nowrap">更新时间</th>
              <th className="text-right px-4 py-3 font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/60">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                  加载中…
                </td>
              </tr>
            )}
            {!loading && scripts.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                  暂无话术记录
                </td>
              </tr>
            )}
            {!loading &&
              scripts.map((s) => {
                const isExpanded = expanded.has(s.id);
                const hasLong = s.content.length > 80;
                return (
                  <tr key={s.id} className="hover:bg-slate-700/30 transition">
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${statusColor(s.review_status)}`}
                      >
                        {s.review_status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        <span className="text-xs text-slate-300 font-mono">{s.language}</span>
                        {s.relationship_stage && (
                          <span className="text-xs text-slate-500">{s.relationship_stage}</span>
                        )}
                        {s.script_type && (
                          <span className="text-xs text-sky-400">{s.script_type}</span>
                        )}
                      </div>
                      {s.emotion_state && (
                        <div className="text-xs text-slate-600 mt-0.5">{s.emotion_state}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 max-w-sm">
                      <p className="text-slate-200 text-sm leading-relaxed">
                        {isExpanded ? s.content : s.content.slice(0, 80) + (hasLong ? "…" : "")}
                      </p>
                      {hasLong && (
                        <button
                          onClick={() => toggleExpand(s.id)}
                          className="text-xs text-violet-400 hover:text-violet-300 mt-1"
                        >
                          {isExpanded ? "收起" : "展开"}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-mono ${riskColor(s.risk_level)}`}>
                        {s.risk_level}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                      {fmtTime(s.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setEditTarget(s)}
                        className="text-xs text-slate-400 hover:text-white px-2 py-1 rounded hover:bg-slate-700 transition mr-1"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => setDeleteTarget(s)}
                        className="text-xs text-rose-400 hover:text-rose-300 px-2 py-1 rounded hover:bg-rose-900/30 transition"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div className="flex items-center justify-between mt-4">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          className="text-sm text-slate-400 hover:text-white border border-slate-700 px-3 py-1 rounded-md disabled:opacity-40 transition"
        >
          上一页
        </button>
        <span className="text-xs text-slate-500">offset={offset}</span>
        <button
          disabled={scripts.length < LIMIT}
          onClick={() => setOffset(offset + LIMIT)}
          className="text-sm text-slate-400 hover:text-white border border-slate-700 px-3 py-1 rounded-md disabled:opacity-40 transition"
        >
          下一页
        </button>
      </div>

      {/* 新建 Modal */}
      {showCreate && (
        <ScriptModal
          title="新建话术"
          initial={EMPTY_FORM}
          onSave={handleCreate}
          onClose={() => setShowCreate(false)}
          saving={saving}
        />
      )}

      {/* 编辑 Modal */}
      {editTarget && (
        <ScriptModal
          title="编辑话术"
          initial={editFormFromScript(editTarget)}
          onSave={handleEdit}
          onClose={() => setEditTarget(null)}
          saving={saving}
        />
      )}

      {/* 删除确认 */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-3">确认删除</h2>
            <p className="text-slate-300 text-sm mb-2">
              删除后无法恢复，确认删除以下话术？
            </p>
            <p className="text-slate-500 text-xs font-mono mb-6 bg-slate-900 rounded-md px-3 py-2">
              {deleteTarget.content.slice(0, 80)}
              {deleteTarget.content.length > 80 ? "…" : ""}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="text-sm text-slate-400 hover:text-white px-4 py-2 rounded-md border border-slate-700 hover:border-slate-500 transition"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={saving}
                className="bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
              >
                {saving ? "删除中…" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Suggest Panel */}
      {showSuggest && <SuggestPanel onClose={() => setShowSuggest(false)} />}
    </main>
  );
}

// ── 页面入口 ─────────────────────────────────────────────────────

export default function ScriptsPage() {
  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <AuthGate>
        {(operator) => {
          function logout() {
            clearAuth();
            window.location.href = LOGIN_PATH;
          }
          return (
            <>
              <NavHeader operator={operator} onLogout={logout} />
              <Suspense
                fallback={
                  <div className="p-8 text-slate-400 text-sm">加载中…</div>
                }
              >
                <ScriptsContent />
              </Suspense>
            </>
          );
        }}
      </AuthGate>
    </div>
  );
}
