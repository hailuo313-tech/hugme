"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型 ──────────────────────────────────────────────────────────

interface ScriptRow {
  id: string;
  character_id: string | null;
  language: string | null;
  relationship_stage: string | null;
  emotion_state: string | null;
  loneliness_score_min: number | null;
  loneliness_score_max: number | null;
  script_type: string | null;
  content: string | null;
  risk_level: string | null;
  conversion_goal: string | null;
  review_status: string | null;
  forbidden_scenarios: string[] | null;
  created_at: string | null;
  updated_at: string | null;
}

interface ScriptListResponse {
  items: ScriptRow[];
  limit: number;
  offset: number;
}

interface SuggestItem extends ScriptRow {
  match_score: number | null;
}

interface SuggestResponse {
  items: SuggestItem[];
}

// ── 枚举选项 ──────────────────────────────────────────────────────

const REVIEW_STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "approved", label: "已通过" },
  { value: "archived", label: "已归档" },
];

const LANGUAGE_OPTIONS = [
  { value: "", label: "全部语言" },
  { value: "en", label: "英语" },
  { value: "zh", label: "中文" },
  { value: "ja", label: "日语" },
  { value: "ko", label: "韩语" },
];

const STAGE_OPTIONS = [
  { value: "", label: "全部阶段" },
  { value: "S0", label: "S0" },
  { value: "S1", label: "S1" },
  { value: "S2", label: "S2" },
  { value: "S3", label: "S3" },
  { value: "S4", label: "S4" },
  { value: "S5", label: "S5" },
];

const SCRIPT_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "reply", label: "回复" },
  { value: "opener", label: "开场" },
  { value: "upsell", label: "转化" },
  { value: "callback", label: "召回" },
];

const RISK_LEVEL_OPTIONS = [
  { value: "low", label: "低" },
  { value: "elevated", label: "升高" },
  { value: "high", label: "高" },
];

const PAGE_LIMIT = 50;

// ── 工具函数 ──────────────────────────────────────────────────────

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function truncate(s: string | null, maxLen = 80): string {
  if (!s) return "—";
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
}

function optionLabel(
  options: Array<{ value: string; label: string }>,
  value: string | null,
): string {
  if (!value) return "—";
  return options.find((option) => option.value === value)?.label || value;
}

function reviewStatusColor(s: string | null): string {
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

function riskColor(r: string | null): string {
  switch (r) {
    case "high":
      return "text-rose-400";
    case "elevated":
      return "text-amber-400";
    default:
      return "text-slate-400";
  }
}

function isValidUUID(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
}

// ── 表单默认值 ────────────────────────────────────────────────────

type ScriptFormData = {
  character_id: string;
  language: string;
  relationship_stage: string;
  emotion_state: string;
  loneliness_score_min: string;
  loneliness_score_max: string;
  script_type: string;
  content: string;
  risk_level: string;
  conversion_goal: string;
  review_status: string;
  forbidden_scenarios: string; // 逗号分隔
};

const EMPTY_FORM: ScriptFormData = {
  character_id: "",
  language: "en",
  relationship_stage: "",
  emotion_state: "",
  loneliness_score_min: "0",
  loneliness_score_max: "100",
  script_type: "",
  content: "",
  risk_level: "low",
  conversion_goal: "",
  review_status: "draft",
  forbidden_scenarios: "",
};

function rowToForm(row: ScriptRow): ScriptFormData {
  return {
    character_id: row.character_id ?? "",
    language: row.language ?? "en",
    relationship_stage: row.relationship_stage ?? "",
    emotion_state: row.emotion_state ?? "",
    loneliness_score_min: String(row.loneliness_score_min ?? 0),
    loneliness_score_max: String(row.loneliness_score_max ?? 100),
    script_type: row.script_type ?? "",
    content: row.content ?? "",
    risk_level: row.risk_level ?? "low",
    conversion_goal: row.conversion_goal ?? "",
    review_status: row.review_status ?? "draft",
    forbidden_scenarios: (row.forbidden_scenarios ?? []).join(", "),
  };
}

function formToPayload(f: ScriptFormData): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    language: f.language || "en",
    risk_level: f.risk_level || "low",
    review_status: f.review_status || "draft",
    content: f.content,
    loneliness_score_min: Number(f.loneliness_score_min),
    loneliness_score_max: Number(f.loneliness_score_max),
    forbidden_scenarios: f.forbidden_scenarios
      ? f.forbidden_scenarios
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : [],
  };
  if (f.character_id.trim()) payload.character_id = f.character_id.trim();
  if (f.relationship_stage) payload.relationship_stage = f.relationship_stage;
  if (f.emotion_state.trim()) payload.emotion_state = f.emotion_state.trim();
  if (f.script_type) payload.script_type = f.script_type;
  if (f.conversion_goal.trim()) payload.conversion_goal = f.conversion_goal.trim();
  return payload;
}

function validateForm(f: ScriptFormData): string | null {
  if (!f.content.trim()) return "话术内容不能为空";
  const min = Number(f.loneliness_score_min);
  const max = Number(f.loneliness_score_max);
  if (Number.isNaN(min) || min < 0 || min > 100)
    return "孤独感分下限必须在 0–100";
  if (Number.isNaN(max) || max < 0 || max > 100)
    return "孤独感分上限必须在 0–100";
  if (min > max)
    return "孤独感分下限不能大于上限";
  if (!["draft", "approved", "archived"].includes(f.review_status))
    return "审核状态只能是草稿、已通过或已归档";
  if (f.character_id.trim() && !isValidUUID(f.character_id.trim()))
    return "角色 ID 格式不正确（请输入有效 UUID）";
  return null;
}

// ── 表单组件 ──────────────────────────────────────────────────────

function ScriptForm({
  initial,
  onSubmit,
  onCancel,
  loading,
  error,
}: {
  initial: ScriptFormData;
  onSubmit: (data: ScriptFormData) => void;
  onCancel: () => void;
  loading: boolean;
  error: string | null;
}) {
  const [form, setForm] = useState<ScriptFormData>(initial);
  const [validationError, setValidationError] = useState<string | null>(null);

  function setField(key: keyof ScriptFormData, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const err = validateForm(form);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    onSubmit(form);
  }

  const inputCls =
    "w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500";
  const labelCls = "block text-xs text-slate-400 mb-1";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {(validationError || error) && (
        <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
          {validationError || error}
        </div>
      )}

      {/* 话术内容 */}
      <div>
        <label className={labelCls}>
          话术内容 <span className="text-rose-400">*</span>
        </label>
        <textarea
          value={form.content}
          onChange={(e) => setField("content", e.target.value)}
          rows={5}
          placeholder="话术正文内容…"
          className={inputCls + " resize-y"}
          required
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* 语言 */}
        <div>
          <label className={labelCls}>语言</label>
          <select
            value={form.language}
            onChange={(e) => setField("language", e.target.value)}
            className={inputCls}
          >
            {LANGUAGE_OPTIONS.filter((o) => o.value).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {/* 审核状态 */}
        <div>
          <label className={labelCls}>审核状态</label>
          <select
            value={form.review_status}
            onChange={(e) => setField("review_status", e.target.value)}
            className={inputCls}
          >
            {REVIEW_STATUS_OPTIONS.filter((o) => o.value).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {/* 关系阶段 */}
        <div>
          <label className={labelCls}>关系阶段</label>
          <select
            value={form.relationship_stage}
            onChange={(e) => setField("relationship_stage", e.target.value)}
            className={inputCls}
          >
            {STAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label || "—（不限）"}
              </option>
            ))}
          </select>
        </div>

        {/* 话术类型 */}
        <div>
          <label className={labelCls}>话术类型</label>
          <select
            value={form.script_type}
            onChange={(e) => setField("script_type", e.target.value)}
            className={inputCls}
          >
            {SCRIPT_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label || "—（不限）"}
              </option>
            ))}
          </select>
        </div>

        {/* 情绪状态 */}
        <div>
          <label className={labelCls}>情绪状态</label>
          <input
            type="text"
            value={form.emotion_state}
            onChange={(e) => setField("emotion_state", e.target.value)}
            placeholder="如 lonely / happy…（可留英文标签）"
            className={inputCls}
          />
        </div>

        {/* 风险等级 */}
        <div>
          <label className={labelCls}>风险等级</label>
          <select
            value={form.risk_level}
            onChange={(e) => setField("risk_level", e.target.value)}
            className={inputCls}
          >
            {RISK_LEVEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {/* 孤独感分下限 */}
        <div>
          <label className={labelCls}>孤独感分下限（0–100）</label>
          <input
            type="number"
            min={0}
            max={100}
            value={form.loneliness_score_min}
            onChange={(e) => setField("loneliness_score_min", e.target.value)}
            className={inputCls}
          />
        </div>

        {/* 孤独感分上限 */}
        <div>
          <label className={labelCls}>孤独感分上限（0–100）</label>
          <input
            type="number"
            min={0}
            max={100}
            value={form.loneliness_score_max}
            onChange={(e) => setField("loneliness_score_max", e.target.value)}
            className={inputCls}
          />
        </div>

        {/* 转化目标 */}
        <div>
          <label className={labelCls}>转化目标</label>
          <input
            type="text"
            value={form.conversion_goal}
            onChange={(e) => setField("conversion_goal", e.target.value)}
            placeholder="如 retain / upsell…（可留英文标签）"
            className={inputCls}
          />
        </div>

        {/* 角色 ID */}
        <div>
          <label className={labelCls}>角色 ID（UUID，选填）</label>
          <input
            type="text"
            value={form.character_id}
            onChange={(e) => setField("character_id", e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className={inputCls + " font-mono text-xs"}
          />
        </div>
      </div>

      {/* 禁用场景 */}
      <div>
        <label className={labelCls}>
          禁用场景（逗号分隔，选填）
        </label>
        <input
          type="text"
          value={form.forbidden_scenarios}
          onChange={(e) => setField("forbidden_scenarios", e.target.value)}
          placeholder="suicide, self-harm, …（可留英文标签）"
          className={inputCls}
        />
      </div>

      {/* 按钮 */}
      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={loading}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
        >
          {loading ? "保存中…" : "保存"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-slate-400 hover:text-white text-sm transition px-4 py-2"
        >
          取消
        </button>
      </div>
    </form>
  );
}

// ── 推荐预览面板 ───────────────────────────────────────────────────

type SuggestFormData = {
  character_id: string;
  language: string;
  relationship_stage: string;
  emotion_state: string;
  loneliness_score: string;
  script_type: string;
  risk_level: string;
  conversion_goal: string;
  limit: string;
};

const EMPTY_SUGGEST: SuggestFormData = {
  character_id: "",
  language: "en",
  relationship_stage: "",
  emotion_state: "",
  loneliness_score: "50",
  script_type: "",
  risk_level: "low",
  conversion_goal: "",
  limit: "5",
};

function SuggestPanel() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<SuggestFormData>(EMPTY_SUGGEST);
  const [results, setResults] = useState<SuggestItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setField(key: keyof SuggestFormData, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handlePreview(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const body: Record<string, unknown> = {
        language: form.language || "en",
        loneliness_score: Number(form.loneliness_score),
        risk_level: form.risk_level || "low",
        limit: Number(form.limit) || 5,
      };
      if (form.character_id.trim()) body.character_id = form.character_id.trim();
      if (form.relationship_stage) body.relationship_stage = form.relationship_stage;
      if (form.emotion_state.trim()) body.emotion_state = form.emotion_state.trim();
      if (form.script_type) body.script_type = form.script_type;
      if (form.conversion_goal.trim()) body.conversion_goal = form.conversion_goal.trim();

      const resp = await apiFetch<SuggestResponse>("/scripts/suggest", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResults(resp.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const inputCls =
    "w-full bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500";
  const labelCls = "block text-xs text-slate-400 mb-1";

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden mb-6">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-sm font-medium text-slate-200 hover:bg-slate-700/40 transition"
      >
        <span>推荐预览 - 测试话术匹配逻辑</span>
        <span className="text-slate-500 text-xs">{open ? "收起 ▲" : "展开 ▼"}</span>
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-slate-700">
          <form onSubmit={handlePreview} className="mt-4 space-y-4">
            {error && (
              <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
                {error}
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className={labelCls}>语言</label>
                <select
                  value={form.language}
                  onChange={(e) => setField("language", e.target.value)}
                  className={inputCls}
                >
                  {LANGUAGE_OPTIONS.filter((o) => o.value).map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>关系阶段</label>
                <select
                  value={form.relationship_stage}
                  onChange={(e) => setField("relationship_stage", e.target.value)}
                  className={inputCls}
                >
                  {STAGE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label || "—（不限）"}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>话术类型</label>
                <select
                  value={form.script_type}
                  onChange={(e) => setField("script_type", e.target.value)}
                  className={inputCls}
                >
                  {SCRIPT_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label || "—（不限）"}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>情绪状态</label>
                <input
                  type="text"
                  value={form.emotion_state}
                  onChange={(e) => setField("emotion_state", e.target.value)}
                  placeholder="如 lonely…（可留英文标签）"
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>孤独感分</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={form.loneliness_score}
                  onChange={(e) => setField("loneliness_score", e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>风险等级</label>
                <select
                  value={form.risk_level}
                  onChange={(e) => setField("risk_level", e.target.value)}
                  className={inputCls}
                >
                  {RISK_LEVEL_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>转化目标</label>
                <input
                  type="text"
                  value={form.conversion_goal}
                  onChange={(e) => setField("conversion_goal", e.target.value)}
                  placeholder="retain / upsell…（可留英文标签）"
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>角色 ID（选填）</label>
                <input
                  type="text"
                  value={form.character_id}
                  onChange={(e) => setField("character_id", e.target.value)}
                  placeholder="UUID…"
                  className={inputCls + " font-mono text-xs"}
                />
              </div>
              <div>
                <label className={labelCls}>返回数量</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={form.limit}
                  onChange={(e) => setField("limit", e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="bg-sky-700 hover:bg-sky-600 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
            >
              {loading ? "请求中…" : "预览推荐话术"}
            </button>
          </form>

          {/* 结果展示 */}
          {results !== null && (
            <div className="mt-5">
              <div className="text-xs text-slate-500 mb-3">
                返回 {results.length} 条（仅 approved 话术）
              </div>
              {results.length === 0 ? (
                <p className="text-slate-500 text-sm">无匹配话术</p>
              ) : (
                <div className="space-y-3">
                  {results.map((item) => (
                    <div
                      key={item.id}
                      className="bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm"
                    >
                      <div className="flex items-center gap-3 mb-2">
                        <span className="font-mono text-xs text-slate-500">
                          {item.id.slice(0, 8)}…
                        </span>
                        <span
                          className={`inline-block px-2 py-0.5 text-xs rounded-full border ${reviewStatusColor(
                            item.review_status
                          )}`}
                        >
                          {optionLabel(REVIEW_STATUS_OPTIONS, item.review_status)}
                        </span>
                        {item.match_score != null && (
                          <span className="text-xs text-sky-400 font-mono">
                            匹配分：{item.match_score.toFixed(3)}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-200 leading-relaxed break-words">
                        {item.content || "—"}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 主页面内容 ────────────────────────────────────────────────────

function ScriptsContent({ operator }: { operator: Operator }) {
  // 列表状态
  const [items, setItems] = useState<ScriptRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 筛选
  const [filterLanguage, setFilterLanguage] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterStage, setFilterStage] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterCharacterId, setFilterCharacterId] = useState("");
  const [appliedCharacterId, setAppliedCharacterId] = useState("");

  // 展开内容
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // 编辑/新建 modal
  const [modalMode, setModalMode] = useState<"create" | "edit" | null>(null);
  const [editingRow, setEditingRow] = useState<ScriptRow | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // toast
  const [toast, setToast] = useState<string | null>(null);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<ScriptRow | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }

  const load = useCallback(
    async (newOffset = 0, reset = false) => {
      setLoading(true);
      setError(null);
      try {
        const qs = new URLSearchParams({
          limit: String(PAGE_LIMIT),
          offset: String(newOffset),
        });
        if (filterLanguage) qs.set("language", filterLanguage);
        if (filterStatus) qs.set("review_status", filterStatus);
        if (filterStage) qs.set("relationship_stage", filterStage);
        if (filterType) qs.set("script_type", filterType);
        if (appliedCharacterId.trim())
          qs.set("character_id", appliedCharacterId.trim());

        const resp = await apiFetch<ScriptListResponse>(
          `/scripts?${qs.toString()}`
        );
        setItems(reset ? resp.items : (prev) => [...prev, ...resp.items]);
        setOffset(newOffset + resp.items.length);
        setHasMore(resp.items.length === PAGE_LIMIT);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [filterLanguage, filterStatus, filterStage, filterType, appliedCharacterId]
  );

  useEffect(() => {
    setOffset(0);
    setItems([]);
    load(0, true);
  }, [load]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openCreate() {
    setEditingRow(null);
    setFormError(null);
    setModalMode("create");
  }

  function openEdit(row: ScriptRow) {
    setEditingRow(row);
    setFormError(null);
    setModalMode("edit");
  }

  function closeModal() {
    setModalMode(null);
    setEditingRow(null);
    setFormError(null);
  }

  async function handleFormSubmit(data: ScriptFormData) {
    setFormLoading(true);
    setFormError(null);
    try {
      const payload = formToPayload(data);
      if (modalMode === "create") {
        await apiFetch<ScriptRow>("/scripts", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showToast("话术已创建");
      } else if (modalMode === "edit" && editingRow) {
        await apiFetch<ScriptRow>(`/scripts/${editingRow.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        showToast("话术已更新");
      }
      closeModal();
      setOffset(0);
      setItems([]);
      load(0, true);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setFormLoading(false);
    }
  }

  async function handleDelete(row: ScriptRow) {
    setDeleteLoading(true);
    try {
      await apiFetch(`/scripts/${row.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      showToast("话术已删除");
      setOffset(0);
      setItems([]);
      load(0, true);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleteLoading(false);
    }
  }

  function handleResetFilter() {
    setFilterLanguage("");
    setFilterStatus("");
    setFilterStage("");
    setFilterType("");
    setFilterCharacterId("");
    setAppliedCharacterId("");
  }

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
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
            <a
              href="/admin/characters"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              角色
            </a>
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
            onClick={handleLogout}
            className="text-sm text-slate-400 hover:text-white transition"
          >
            退出
          </button>
        </div>
      </header>

      <main className="p-8 max-w-7xl mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold mb-1">话术库</h1>
            <p className="text-slate-400 text-sm">
              管理运营话术：浏览、新建、编辑、归档
            </p>
          </div>
          <button
            onClick={openCreate}
            className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
          >
            + 新建话术
          </button>
        </div>

        {/* 推荐预览 */}
        <SuggestPanel />

        {/* 筛选栏 */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedCharacterId(filterCharacterId);
            setOffset(0);
            setItems([]);
            load(0, true);
          }}
          className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex flex-wrap items-center gap-3"
        >
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {REVIEW_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={filterLanguage}
            onChange={(e) => setFilterLanguage(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={filterStage}
            onChange={(e) => setFilterStage(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {STAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
          >
            {SCRIPT_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <input
            type="text"
            value={filterCharacterId}
            onChange={(e) => setFilterCharacterId(e.target.value)}
            placeholder="角色 ID（UUID）"
            className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-500 font-mono min-w-[220px]"
          />
          <button
            type="submit"
            className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
          >
            筛选
          </button>
          <button
            type="button"
            onClick={handleResetFilter}
            className="text-slate-400 hover:text-white text-sm transition"
          >
            重置
          </button>
        </form>

        {/* 错误 */}
        {error && (
          <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
            加载失败：{error}
          </div>
        )}

        {/* 表格 */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3 font-medium">审核状态</th>
                <th className="text-left px-4 py-3 font-medium">类型</th>
                <th className="text-left px-4 py-3 font-medium">语言</th>
                <th className="text-left px-4 py-3 font-medium">阶段</th>
                <th className="text-left px-4 py-3 font-medium">情绪</th>
                <th className="text-left px-4 py-3 font-medium">孤独感分</th>
                <th className="text-left px-4 py-3 font-medium">风险</th>
                <th className="text-left px-4 py-3 font-medium">目标</th>
                <th className="text-left px-4 py-3 font-medium">内容</th>
                <th className="text-left px-4 py-3 font-medium whitespace-nowrap">更新时间</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60">
              {loading && items.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-8 text-center text-slate-500">
                    加载中…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-12 text-center text-slate-500">
                    暂无话术记录
                  </td>
                </tr>
              )}
              {items.map((row) => {
                const isExpanded = expanded.has(row.id);
                const hasLong = row.content !== null && row.content.length > 80;
                return (
                  <tr key={row.id} className="hover:bg-slate-700/30 transition align-top">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${reviewStatusColor(row.review_status)}`}
                      >
                        {optionLabel(REVIEW_STATUS_OPTIONS, row.review_status)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {optionLabel(SCRIPT_TYPE_OPTIONS, row.script_type)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {optionLabel(LANGUAGE_OPTIONS, row.language)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{row.relationship_stage || "—"}</td>
                    <td className="px-4 py-3 text-slate-300">{row.emotion_state || "—"}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs tabular-nums whitespace-nowrap">
                      {row.loneliness_score_min ?? "—"} – {row.loneliness_score_max ?? "—"}
                    </td>
                    <td className={`px-4 py-3 ${riskColor(row.risk_level)}`}>
                      {optionLabel(RISK_LEVEL_OPTIONS, row.risk_level)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{row.conversion_goal || "—"}</td>
                    <td className="px-4 py-3 text-slate-200 max-w-[300px]">
                      <span className="break-words">
                        {isExpanded ? (row.content ?? "—") : truncate(row.content)}
                      </span>
                      {hasLong && (
                        <button
                          onClick={() => toggleExpand(row.id)}
                          className="ml-2 text-xs text-violet-400 hover:text-violet-300 whitespace-nowrap"
                        >
                          {isExpanded ? "收起" : "展开"}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                      {fmtTime(row.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                      <button
                        onClick={() => openEdit(row)}
                        className="text-violet-400 hover:text-violet-300 text-xs"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => setDeleteTarget(row)}
                        className="text-rose-400 hover:text-rose-300 text-xs"
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

        {/* 加载更多 */}
        {hasMore && (
          <div className="flex justify-center mt-4">
            <button
              onClick={() => load(offset)}
              disabled={loading}
              className="px-5 py-2 border border-slate-700 rounded-md text-slate-300 hover:bg-slate-800 disabled:opacity-40 text-sm transition"
            >
              {loading ? "加载中…" : "加载更多"}
            </button>
          </div>
        )}
      </main>

      {/* 新建/编辑 Modal */}
      {modalMode && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto py-10"
          onClick={closeModal}
        >
          <div
            className="w-full max-w-2xl bg-slate-900 rounded-xl border border-slate-700 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
              <h2 className="text-lg font-semibold">
                {modalMode === "create" ? "新建话术" : "编辑话术"}
              </h2>
              <button
                onClick={closeModal}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>
            <div className="px-6 py-5">
              <ScriptForm
                initial={
                  modalMode === "edit" && editingRow
                    ? rowToForm(editingRow)
                    : EMPTY_FORM
                }
                onSubmit={handleFormSubmit}
                onCancel={closeModal}
                loading={formLoading}
                error={formError}
              />
            </div>
          </div>
        </div>
      )}

      {/* 删除确认对话框 */}
      {deleteTarget && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center"
          onClick={() => !deleteLoading && setDeleteTarget(null)}
        >
          <div
            className="w-full max-w-md bg-slate-900 rounded-xl border border-slate-700 shadow-2xl p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold mb-3">确认删除</h3>
            <p className="text-slate-400 text-sm mb-2">
              即将永久删除以下话术（此操作不可撤销）：
            </p>
            <p className="bg-slate-800 rounded-md px-3 py-2 text-sm text-slate-200 mb-5 break-words">
              {truncate(deleteTarget.content, 120)}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => handleDelete(deleteTarget)}
                disabled={deleteLoading}
                className="bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md transition"
              >
                {deleteLoading ? "删除中…" : "确认删除"}
              </button>
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleteLoading}
                className="text-slate-400 hover:text-white text-sm transition px-4 py-2"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-emerald-800 border border-emerald-700 text-emerald-100 text-sm px-5 py-3 rounded-xl shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

// ── 页面入口 ──────────────────────────────────────────────────────

export default function ScriptsPage() {
  return (
    <AuthGate>
      {(operator) => <ScriptsContent operator={operator} />}
    </AuthGate>
  );
}
