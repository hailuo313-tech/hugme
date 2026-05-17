"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import {
  CHARACTER_PROFILE_FIELDS,
  CHARACTER_PROFILE_GROUPS,
  CharacterProfileField,
  CharacterProfileFieldKey,
} from "@/lib/characterProfileOptions";

interface CharacterRow {
  id: string;
  name: string;
  age_feel: string | null;
  region: string | null;
  occupation: string | null;
  background: string | null;
  relationship_position: string | null;
  profile_details: Record<string, unknown> | string | null;
  default_language: string | null;
  supported_languages: string[] | string | null;
  gentle_score: number | null;
  proactive_score: number | null;
  flirt_score: number | null;
  humor_score: number | null;
  emotional_depth_score: number | null;
  boundary_score: number | null;
  reply_length: string | null;
  tone: string | null;
  emoji_frequency: string | null;
  prompt_en: string | null;
  prompt_es: string | null;
  prompt_fr: string | null;
  prompt_de: string | null;
  status: string | null;
  updated_at: string | null;
}

type CharacterFormData = {
  name: string;
  status: string;
  default_language: string;
  supported_languages: string;
  age_feel: string;
  region: string;
  occupation: string;
  background: string;
  relationship_position: string;
  gentle_score: string;
  proactive_score: string;
  flirt_score: string;
  humor_score: string;
  emotional_depth_score: string;
  boundary_score: string;
  reply_length: string;
  tone: string;
  emoji_frequency: string;
  prompt_en: string;
  prompt_es: string;
  prompt_fr: string;
  prompt_de: string;
  profile_details: Record<CharacterProfileFieldKey, string>;
};

const EMPTY_PROFILE_DETAILS = Object.fromEntries(
  CHARACTER_PROFILE_FIELDS.map((field) => [field.key, ""])
) as Record<CharacterProfileFieldKey, string>;

const EMPTY_FORM: CharacterFormData = {
  name: "",
  status: "draft",
  default_language: "zh",
  supported_languages: "zh, en",
  age_feel: "",
  region: "",
  occupation: "",
  background: "",
  relationship_position: "",
  gentle_score: "70",
  proactive_score: "55",
  flirt_score: "20",
  humor_score: "45",
  emotional_depth_score: "70",
  boundary_score: "75",
  reply_length: "medium",
  tone: "warm",
  emoji_frequency: "low",
  prompt_en: "",
  prompt_es: "",
  prompt_fr: "",
  prompt_de: "",
  profile_details: EMPTY_PROFILE_DETAILS,
};

const STATUS_OPTIONS = ["draft", "active", "archived", "inactive"];
const REPLY_LENGTH_OPTIONS = ["short", "medium", "long"];
const EMOJI_OPTIONS = ["none", "low", "medium", "high"];

function normalizeJsonObject(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed
        : {};
    } catch {
      return {};
    }
  }
  return typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeLanguages(value: CharacterRow["supported_languages"]): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.join(", ");
    } catch {
      return value;
    }
  }
  return "zh, en";
}

function fmtTime(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function statusColor(status: string | null): string {
  switch (status) {
    case "active":
      return "bg-emerald-900/40 text-emerald-300 border-emerald-800";
    case "draft":
      return "bg-amber-900/40 text-amber-300 border-amber-800";
    case "archived":
    case "inactive":
      return "bg-slate-800 text-slate-400 border-slate-700";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

function rowToForm(row: CharacterRow): CharacterFormData {
  const details = normalizeJsonObject(row.profile_details);
  const profileDetails = { ...EMPTY_PROFILE_DETAILS };
  for (const field of CHARACTER_PROFILE_FIELDS) {
    const value = details[field.key];
    profileDetails[field.key] = value == null ? "" : String(value);
  }

  return {
    name: row.name ?? "",
    status: row.status ?? "draft",
    default_language: row.default_language ?? "zh",
    supported_languages: normalizeLanguages(row.supported_languages),
    age_feel: row.age_feel ?? "",
    region: row.region ?? "",
    occupation: row.occupation ?? "",
    background: row.background ?? "",
    relationship_position: row.relationship_position ?? "",
    gentle_score: String(row.gentle_score ?? 70),
    proactive_score: String(row.proactive_score ?? 55),
    flirt_score: String(row.flirt_score ?? 20),
    humor_score: String(row.humor_score ?? 45),
    emotional_depth_score: String(row.emotional_depth_score ?? 70),
    boundary_score: String(row.boundary_score ?? 75),
    reply_length: row.reply_length ?? "medium",
    tone: row.tone ?? "warm",
    emoji_frequency: row.emoji_frequency ?? "low",
    prompt_en: row.prompt_en ?? "",
    prompt_es: row.prompt_es ?? "",
    prompt_fr: row.prompt_fr ?? "",
    prompt_de: row.prompt_de ?? "",
    profile_details: profileDetails,
  };
}

function validateScore(value: string, label: string): string | null {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0 || n > 100) {
    return `${label} 必须是 0-100 的整数`;
  }
  return null;
}

function formToPayload(form: CharacterFormData): Record<string, unknown> {
  const languages = form.supported_languages
    .split(",")
    .map((lang) => lang.trim())
    .filter(Boolean);
  const profileDetails = Object.fromEntries(
    Object.entries(form.profile_details).filter(([, value]) => value.trim())
  );

  return {
    name: form.name.trim(),
    status: form.status,
    default_language: form.default_language.trim() || "zh",
    supported_languages: languages.length ? languages : ["zh"],
    age_feel: form.age_feel.trim() || undefined,
    region: form.region.trim() || undefined,
    occupation: form.occupation.trim() || undefined,
    background: form.background.trim() || undefined,
    relationship_position: form.relationship_position.trim() || undefined,
    gentle_score: Number(form.gentle_score),
    proactive_score: Number(form.proactive_score),
    flirt_score: Number(form.flirt_score),
    humor_score: Number(form.humor_score),
    emotional_depth_score: Number(form.emotional_depth_score),
    boundary_score: Number(form.boundary_score),
    reply_length: form.reply_length,
    tone: form.tone.trim() || "warm",
    emoji_frequency: form.emoji_frequency,
    prompt_en: form.prompt_en.trim() || undefined,
    prompt_es: form.prompt_es.trim() || undefined,
    prompt_fr: form.prompt_fr.trim() || undefined,
    prompt_de: form.prompt_de.trim() || undefined,
    profile_details: profileDetails,
  };
}

function validateForm(form: CharacterFormData): string | null {
  if (!form.name.trim()) return "角色名称不能为空";
  if (!STATUS_OPTIONS.includes(form.status)) return "状态不合法";
  if (!REPLY_LENGTH_OPTIONS.includes(form.reply_length)) return "回复长度不合法";
  if (!EMOJI_OPTIONS.includes(form.emoji_frequency)) return "Emoji 频率不合法";
  const scoreChecks = [
    ["gentle_score", "温柔度"],
    ["proactive_score", "主动度"],
    ["flirt_score", "调情度"],
    ["humor_score", "幽默度"],
    ["emotional_depth_score", "情感深度"],
    ["boundary_score", "边界感"],
  ] as const;
  for (const [key, label] of scoreChecks) {
    const error = validateScore(form[key], label);
    if (error) return error;
  }
  return null;
}

function FieldSelector({
  field,
  value,
  onChange,
}: {
  field: CharacterProfileField;
  value: string;
  onChange: (value: string) => void;
}) {
  const selectedValue = field.options.some((option) => option.value === value)
    ? value
    : "";

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <label className="block text-sm font-medium text-slate-200 mb-1">
        {field.label}
      </label>
      <p className="text-xs text-slate-500 mb-3">{field.hint}</p>
      <select
        value={selectedValue}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
      >
        <option value="">选择固定选项</option>
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="手动覆盖"
        className="mt-2 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
      />
    </div>
  );
}

function CharactersContent({ operator }: { operator: Operator }) {
  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [editing, setEditing] = useState<CharacterRow | null>(null);
  const [form, setForm] = useState<CharacterFormData>(EMPTY_FORM);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await apiFetch<CharacterRow[]>("/characters?include_inactive=true");
      setCharacters(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setCharacters([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 1800);
  }

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  function startCreate() {
    setEditing(null);
    setForm({ ...EMPTY_FORM, profile_details: { ...EMPTY_PROFILE_DETAILS } });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startEdit(row: CharacterRow) {
    setEditing(row);
    setForm(rowToForm(row));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateField<K extends keyof CharacterFormData>(
    key: K,
    value: CharacterFormData[K]
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function updateProfileField(key: CharacterProfileFieldKey, value: string) {
    setForm((prev) => ({
      ...prev,
      profile_details: { ...prev.profile_details, [key]: value },
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const validation = validateForm(form);
    if (validation) {
      setError(validation);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = formToPayload(form);
      if (editing) {
        await apiFetch<CharacterRow>(`/characters/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        showToast("角色已更新");
      } else {
        await apiFetch<CharacterRow>("/characters", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showToast("角色已创建");
      }
      await load();
      startCreate();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const selectedProfileCount = useMemo(
    () => Object.values(form.profile_details).filter((value) => value.trim()).length,
    [form.profile_details]
  );

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-500">/</span>
          <a href="/admin" className="text-slate-300 hover:text-white">
            会话
          </a>
          <a href="/admin/memories" className="text-slate-300 hover:text-white">
            记忆
          </a>
          <a href="/admin/scripts" className="text-slate-300 hover:text-white">
            话术库
          </a>
          <span className="text-violet-300 font-medium">角色</span>
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-300">
          <span>{operator.username}</span>
          <button onClick={handleLogout} className="text-slate-400 hover:text-white">
            退出
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold mb-1">角色管理</h1>
            <p className="text-slate-400 text-sm">
              用结构化选项创建角色档案，保存到 characters.profile_details 并进入 Prompt。
            </p>
          </div>
          <button
            onClick={startCreate}
            className="rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2 text-sm font-medium"
          >
            + 新建角色
          </button>
        </div>

        {toast && (
          <div className="rounded-lg border border-emerald-800 bg-emerald-950/60 px-4 py-3 text-sm text-emerald-200">
            {toast}
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/60 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-slate-700 bg-slate-800/60 p-6 space-y-6"
        >
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">
                {editing ? `编辑：${editing.name}` : "新建角色"}
              </h2>
              <p className="text-sm text-slate-500">
                已填写 {selectedProfileCount}/{CHARACTER_PROFILE_FIELDS.length} 个结构化字段
              </p>
            </div>
            {editing && (
              <button
                type="button"
                onClick={startCreate}
                className="text-sm text-slate-400 hover:text-white"
              >
                取消编辑
              </button>
            )}
          </div>

          <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input label="角色名称" value={form.name} onChange={(v) => updateField("name", v)} />
            <Select
              label="状态"
              value={form.status}
              options={STATUS_OPTIONS}
              onChange={(v) => updateField("status", v)}
            />
            <Input
              label="默认语言"
              value={form.default_language}
              onChange={(v) => updateField("default_language", v)}
            />
            <Input
              label="支持语言（逗号分隔）"
              value={form.supported_languages}
              onChange={(v) => updateField("supported_languages", v)}
            />
            <Input label="体感年龄" value={form.age_feel} onChange={(v) => updateField("age_feel", v)} />
            <Input label="地区" value={form.region} onChange={(v) => updateField("region", v)} />
            <Input label="职业" value={form.occupation} onChange={(v) => updateField("occupation", v)} />
            <Input
              label="关系定位"
              value={form.relationship_position}
              onChange={(v) => updateField("relationship_position", v)}
            />
            <Input label="语气" value={form.tone} onChange={(v) => updateField("tone", v)} />
          </section>

          <section className="grid grid-cols-2 md:grid-cols-6 gap-4">
            <Input label="温柔度" value={form.gentle_score} onChange={(v) => updateField("gentle_score", v)} />
            <Input label="主动度" value={form.proactive_score} onChange={(v) => updateField("proactive_score", v)} />
            <Input label="调情度" value={form.flirt_score} onChange={(v) => updateField("flirt_score", v)} />
            <Input label="幽默度" value={form.humor_score} onChange={(v) => updateField("humor_score", v)} />
            <Input
              label="情感深度"
              value={form.emotional_depth_score}
              onChange={(v) => updateField("emotional_depth_score", v)}
            />
            <Input label="边界感" value={form.boundary_score} onChange={(v) => updateField("boundary_score", v)} />
          </section>

          <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Select
              label="回复长度"
              value={form.reply_length}
              options={REPLY_LENGTH_OPTIONS}
              onChange={(v) => updateField("reply_length", v)}
            />
            <Select
              label="Emoji 频率"
              value={form.emoji_frequency}
              options={EMOJI_OPTIONS}
              onChange={(v) => updateField("emoji_frequency", v)}
            />
          </section>

          <section>
            <label className="block text-sm font-medium text-slate-200 mb-2">背景</label>
            <textarea
              value={form.background}
              onChange={(e) => updateField("background", e.target.value)}
              rows={3}
              className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
            />
          </section>

          <div className="space-y-6">
            {CHARACTER_PROFILE_GROUPS.map((group) => (
              <section key={group.title} className="space-y-3">
                <div>
                  <h3 className="text-base font-semibold text-slate-100">{group.title}</h3>
                  <p className="text-sm text-slate-500">{group.description}</p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {group.fields.map((field) => (
                    <FieldSelector
                      key={field.key}
                      field={field}
                      value={form.profile_details[field.key]}
                      onChange={(value) => updateProfileField(field.key, value)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>

          <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TextArea label="英文 Prompt 补充" value={form.prompt_en} onChange={(v) => updateField("prompt_en", v)} />
            <TextArea label="西语 Prompt 补充" value={form.prompt_es} onChange={(v) => updateField("prompt_es", v)} />
            <TextArea label="法语 Prompt 补充" value={form.prompt_fr} onChange={(v) => updateField("prompt_fr", v)} />
            <TextArea label="德语 Prompt 补充" value={form.prompt_de} onChange={(v) => updateField("prompt_de", v)} />
          </section>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={startCreate}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700"
            >
              重置
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
            >
              {saving ? "保存中…" : editing ? "保存修改" : "创建角色"}
            </button>
          </div>
        </form>

        <section className="rounded-2xl border border-slate-700 bg-slate-800/60 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-lg font-semibold">角色列表</h2>
            <span className="text-sm text-slate-500">
              {loading ? "加载中…" : `${characters.length} 个角色`}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">名称</th>
                  <th className="text-left px-4 py-3 font-medium">状态</th>
                  <th className="text-left px-4 py-3 font-medium">职业 / 地区</th>
                  <th className="text-left px-4 py-3 font-medium">结构化字段</th>
                  <th className="text-left px-4 py-3 font-medium">更新时间</th>
                  <th className="text-right px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {!loading && characters.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                      暂无角色
                    </td>
                  </tr>
                )}
                {characters.map((row) => {
                  const detailCount = Object.keys(
                    normalizeJsonObject(row.profile_details)
                  ).length;
                  return (
                    <tr key={row.id} className="border-t border-slate-800">
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-100">{row.name}</div>
                        <div className="text-xs text-slate-500">{row.id}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${statusColor(row.status)}`}>
                          {row.status ?? "unknown"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        <div>{row.occupation || "—"}</div>
                        <div className="text-xs text-slate-500">{row.region || "—"}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{detailCount}</td>
                      <td className="px-4 py-3 text-slate-400">{fmtTime(row.updated_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => startEdit(row)}
                          className="text-violet-300 hover:text-violet-200"
                        >
                          编辑
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-200 mb-1">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
      />
    </label>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-200 mb-1">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextArea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-200 mb-1">{label}</span>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100"
      />
    </label>
  );
}

export default function CharactersPage() {
  return <AuthGate>{(operator) => <CharactersContent operator={operator} />}</AuthGate>;
}
