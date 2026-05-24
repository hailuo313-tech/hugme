"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

type ScriptTemplate = {
  id: string;
  category_key: string;
  title: string;
  language: string;
  channel: string;
  platform: string | null;
  user_level: string | null;
  chat_route: string | null;
  persona_slug: string | null;
  hook: string | null;
  content: string;
  variables: unknown[] | string | null;
  safety_tags: unknown[] | string | null;
  status: string;
  updated_at: string | null;
};

type ScriptForm = {
  id?: string;
  category_key: string;
  title: string;
  language: string;
  channel: string;
  platform: string;
  user_level: string;
  chat_route: string;
  persona_slug: string;
  hook: string;
  content: string;
  variables: string;
  safety_tags: string;
  status: string;
};

const scriptEmpty: ScriptForm = {
  category_key: "app_download_first_push",
  title: "",
  language: "zh",
  channel: "telegram_real_user",
  platform: "telegram_real_user",
  user_level: "",
  chat_route: "ai_auto",
  persona_slug: "",
  hook: "reply",
  content: "",
  variables: "app_download_url",
  safety_tags: "app_download_conversion",
  status: "draft",
};

const SCRIPT_CATEGORY_OPTIONS = [
  "app_download_first_push",
  "app_download_after_warmup",
  "app_download_direct_cta",
  "app_download_objection",
  "trust_reassurance",
  "app_link_clicked_followup",
  "operator_app_conversion",
  "greeting",
  "conversion",
  "refusal",
  "probe",
  "fallback",
];

const APP_DOWNLOAD_CATEGORY_KEYS = new Set([
  "app_download_first_push",
  "app_download_after_warmup",
  "app_download_direct_cta",
  "app_download_objection",
  "trust_reassurance",
  "app_link_clicked_followup",
  "operator_app_conversion",
]);

const SCRIPT_CATEGORY_LABELS: Record<string, string> = {
  app_download_first_push: "App下载-首次引导",
  app_download_after_warmup: "App下载-升温后引导",
  app_download_direct_cta: "App下载-直接要链接",
  app_download_objection: "App下载-异议处理",
  trust_reassurance: "App下载-信任解释",
  app_link_clicked_followup: "App下载-已点击未下载",
  operator_app_conversion: "App下载-人工/高价值转化",
  greeting: "开场问候",
  conversion: "普通转化",
  refusal: "拒绝/安全",
  probe: "探测话术",
  fallback: "兜底回复",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  approved: "启用",
  archived: "归档",
};

export default function AiOpsPage() {
  return (
    <AuthGate>
      {(operator) => <AiOpsContent operator={operator} />}
    </AuthGate>
  );
}

function AiOpsContent({ operator }: { operator: Operator }) {
  const [scripts, setScripts] = useState<ScriptTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("app");
  const [statusFilter, setStatusFilter] = useState("active");
  const [scriptForm, setScriptForm] = useState<ScriptForm>(scriptEmpty);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch<{ items: ScriptTemplate[] }>("/ai-ops/admin/script-templates?limit=500");
      setScripts(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visibleScripts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return scripts.filter((row) => {
      const isAppDownload = APP_DOWNLOAD_CATEGORY_KEYS.has(row.category_key);
      if (categoryFilter === "app" && !isAppDownload) return false;
      if (categoryFilter !== "all" && categoryFilter !== "app" && row.category_key !== categoryFilter) return false;
      if (statusFilter === "active" && row.status === "archived") return false;
      if (statusFilter !== "all" && statusFilter !== "active" && row.status !== statusFilter) return false;
      if (!needle) return true;
      return [row.title, row.content, row.category_key, categoryLabel(row.category_key), row.language]
        .some((value) => String(value || "").toLowerCase().includes(needle));
    });
  }, [categoryFilter, query, scripts, statusFilter]);

  const appDownloadCount = scripts.filter((row) => APP_DOWNLOAD_CATEGORY_KEYS.has(row.category_key) && row.status !== "archived").length;
  const approvedCount = visibleScripts.filter((row) => row.status === "approved").length;
  const draftCount = visibleScripts.filter((row) => row.status === "draft").length;

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 2200);
  }

  async function saveScript(event: FormEvent) {
    event.preventDefault();
    if (!scriptForm.title.trim() || !scriptForm.content.trim()) {
      setError("标题和话术内容不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        category_key: scriptForm.category_key,
        title: scriptForm.title.trim(),
        language: scriptForm.language.trim() || "zh",
        channel: scriptForm.channel.trim() || "telegram_real_user",
        platform: scriptForm.platform.trim() || "telegram_real_user",
        user_level: scriptForm.user_level || null,
        chat_route: scriptForm.chat_route || null,
        persona_slug: scriptForm.persona_slug.trim() || null,
        hook: scriptForm.hook.trim() || null,
        content: scriptForm.content.trim(),
        variables: splitList(scriptForm.variables),
        safety_tags: splitList(scriptForm.safety_tags),
        status: scriptForm.status,
      };
      if (scriptForm.id) {
        await apiFetch(`/ai-ops/admin/script-templates/${scriptForm.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify("话术已保存");
      } else {
        await apiFetch("/ai-ops/admin/script-templates", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        notify("话术已新增");
      }
      setScriptForm(scriptEmpty);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleScript(row: ScriptTemplate) {
    const nextStatus = row.status === "approved" ? "draft" : "approved";
    await apiFetch(`/ai-ops/admin/script-templates/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus }),
    });
    notify(nextStatus === "approved" ? "话术已启用" : "话术已停用");
    await load();
  }

  async function archiveScript(row: ScriptTemplate) {
    if (!window.confirm(`确认归档「${row.title}」？`)) return;
    await apiFetch(`/ai-ops/admin/script-templates/${row.id}`, { method: "DELETE" });
    notify("话术已归档");
    await load();
  }

  return (
    <AdminFrame
      operator={operator}
      active="ai"
      title="话术库管理"
      subtitle="只管理用户进入到点击下载之间的话术。人设、禁用词、意图规则等高级配置已从此页面隐藏，避免误操作。"
    >
      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Metric label="下载引导话术" value={`${appDownloadCount}`} hint="未归档的 App 下载类目话术" />
        <Metric label="当前列表启用" value={`${approvedCount}`} hint="会被系统自动匹配使用" />
        <Metric label="当前列表草稿" value={`${draftCount}`} hint="保存但不会自动发送" />
      </section>

      {error && <div className="mb-4 rounded-md border border-rose-800 bg-rose-950/50 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {toast && <div className="fixed bottom-6 right-6 z-50 rounded-md border border-emerald-700 bg-emerald-950 px-5 py-3 text-sm text-emerald-100 shadow-xl">{toast}</div>}

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-[360px_1fr]">
        <ScriptEditor
          form={scriptForm}
          saving={saving}
          onChange={setScriptForm}
          onSubmit={saveScript}
          onCancel={() => setScriptForm(scriptEmpty)}
        />

        <Panel title="话术列表">
          <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px_160px]">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索标题、内容或类目"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500"
            />
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500">
              <option value="app">只看下载引导</option>
              <option value="all">全部类目</option>
              {SCRIPT_CATEGORY_OPTIONS.map((key) => (
                <option key={key} value={key}>{categoryLabel(key)}</option>
              ))}
            </select>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500">
              <option value="active">未归档</option>
              <option value="approved">启用</option>
              <option value="draft">草稿</option>
              <option value="archived">归档</option>
              <option value="all">全部状态</option>
            </select>
          </div>

          {loading ? (
            <div className="py-12 text-center text-sm text-slate-500">加载中...</div>
          ) : visibleScripts.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-500">没有符合条件的话术</div>
          ) : (
            <div className="divide-y divide-slate-800">
              {visibleScripts.map((row) => (
                <ScriptRow
                  key={row.id}
                  row={row}
                  onEdit={() => setScriptForm(scriptToForm(row))}
                  onToggle={() => toggleScript(row)}
                  onArchive={() => archiveScript(row)}
                />
              ))}
            </div>
          )}
        </Panel>
      </section>
    </AdminFrame>
  );
}

function ScriptEditor({ form, saving, onChange, onSubmit, onCancel }: { form: ScriptForm; saving: boolean; onChange: (form: ScriptForm) => void; onSubmit: (event: FormEvent) => void; onCancel: () => void }) {
  return (
    <Panel title={form.id ? "编辑话术" : "新增话术"}>
      <form onSubmit={onSubmit} className="space-y-3">
        <Input label="标题" value={form.title} onChange={(value) => onChange({ ...form, title: value })} />
        <Select label="类目" value={form.category_key} options={SCRIPT_CATEGORY_OPTIONS} onChange={(value) => onChange({ ...form, category_key: value })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="语言" value={form.language} onChange={(value) => onChange({ ...form, language: value })} />
          <Select label="状态" value={form.status} options={["draft", "approved", "archived"]} labels={STATUS_LABELS} onChange={(value) => onChange({ ...form, status: value })} />
        </div>
        <TextArea label="话术内容" rows={7} value={form.content} onChange={(value) => onChange({ ...form, content: value })} />

        <details className="rounded-md border border-slate-800 bg-slate-950 p-3">
          <summary className="cursor-pointer text-sm text-slate-300">高级设置</summary>
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Input label="平台" value={form.platform} onChange={(value) => onChange({ ...form, platform: value })} />
              <Input label="hook" value={form.hook} onChange={(value) => onChange({ ...form, hook: value })} />
              <Select label="等级" value={form.user_level} options={["", "S", "A", "B", "C", "D"]} onChange={(value) => onChange({ ...form, user_level: value })} />
              <Select label="路由" value={form.chat_route} options={["", "manual_premium", "ai_assisted", "ai_auto"]} onChange={(value) => onChange({ ...form, chat_route: value })} />
            </div>
            <Input label="persona" value={form.persona_slug} onChange={(value) => onChange({ ...form, persona_slug: value })} />
            <Input label="变量，逗号分隔" value={form.variables} onChange={(value) => onChange({ ...form, variables: value })} />
            <Input label="安全标签，逗号分隔" value={form.safety_tags} onChange={(value) => onChange({ ...form, safety_tags: value })} />
          </div>
        </details>

        <div className="flex gap-3 pt-2">
          <button disabled={saving} className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50">
            {saving ? "保存中..." : form.id ? "保存修改" : "新增话术"}
          </button>
          <button type="button" onClick={onCancel} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
            清空
          </button>
        </div>
      </form>
    </Panel>
  );
}

function ScriptRow({ row, onEdit, onToggle, onArchive }: { row: ScriptTemplate; onEdit: () => void; onToggle: () => void; onArchive: () => void }) {
  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium text-slate-100">{row.title}</div>
          <div className="mt-1 text-xs text-slate-500">
            {categoryLabel(row.category_key)} / {row.language || "-"} / {row.hook || "-"} / {row.user_level || "不限等级"}
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${badgeClass(row.status)}`}>{STATUS_LABELS[row.status] || row.status}</span>
      </div>
      <p className="mb-3 line-clamp-3 whitespace-pre-wrap text-sm text-slate-400">{row.content}</p>
      <div className="flex flex-wrap gap-2">
        <button onClick={onEdit} className="rounded-md bg-slate-800 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-700">编辑</button>
        <button onClick={onToggle} className="rounded-md border border-amber-700 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-950">{row.status === "approved" ? "停用" : "启用"}</button>
        {row.status !== "archived" && <button onClick={onArchive} className="rounded-md border border-rose-800 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-950">归档</button>}
      </div>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{hint}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-5 py-4 text-lg font-semibold text-slate-100">{title}</h2>
      <div className="p-5">{children}</div>
    </div>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate-300">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500" />
    </label>
  );
}

function Select({ label, value, options, labels, onChange }: { label: string; value: string; options: string[]; labels?: Record<string, string>; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate-300">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500">
        {options.map((option) => (
          <option key={option || "empty"} value={option}>
            {option ? (labels?.[option] || categoryLabel(option)) : "不限"}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextArea({ label, value, rows, onChange }: { label: string; value: string; rows: number; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate-300">{label}</span>
      <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} className="w-full resize-y rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500" />
    </label>
  );
}

function badgeClass(status: string) {
  if (status === "approved") return "bg-emerald-500/10 text-emerald-300";
  if (status === "draft") return "bg-amber-500/10 text-amber-300";
  return "bg-slate-800 text-slate-400";
}

function categoryLabel(categoryKey: string): string {
  return SCRIPT_CATEGORY_LABELS[categoryKey] || categoryKey;
}

function scriptToForm(row: ScriptTemplate): ScriptForm {
  return {
    id: row.id,
    category_key: row.category_key,
    title: row.title,
    language: row.language || "zh",
    channel: row.channel || "telegram_real_user",
    platform: row.platform || row.channel || "telegram_real_user",
    user_level: row.user_level || "",
    chat_route: row.chat_route || "",
    persona_slug: row.persona_slug || "",
    hook: row.hook || "",
    content: row.content || "",
    variables: listToText(row.variables),
    safety_tags: listToText(row.safety_tags),
    status: row.status || "draft",
  };
}

function splitList(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function listToText(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map(String).join(", ");
    } catch {
      return value;
    }
  }
  return "";
}
