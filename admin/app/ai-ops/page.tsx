"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

type TabKey = "scripts" | "personas" | "redlines" | "intents";

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

type PersonaPrompt = {
  id: string;
  slug: string;
  display_name: string;
  language: string;
  tone_family: string;
  prompt_text: string;
  safety_notes: string[] | string | null;
  status: string;
  updated_at: string | null;
};

type IntentRule = {
  id: string;
  intent: string;
  priority: number;
  confidence: number;
  keywords: string[];
  patterns: string[];
  excludes?: string[];
  enabled?: boolean;
};

type Redline = {
  id: string;
  category: string;
  reason: string;
  patterns: string[];
  enabled?: boolean;
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

type PersonaForm = {
  id?: string;
  slug: string;
  display_name: string;
  language: string;
  tone_family: string;
  prompt_text: string;
  safety_notes: string;
  status: string;
};

type IntentForm = {
  originalId?: string;
  id: string;
  intent: string;
  priority: string;
  confidence: string;
  keywords: string;
  patterns: string;
  excludes: string;
  enabled: boolean;
};

type RedlineForm = {
  originalId?: string;
  id: string;
  category: string;
  reason: string;
  patterns: string;
  enabled: boolean;
};

const tabs: Array<{ key: TabKey; label: string; desc: string }> = [
  { key: "scripts", label: "话术底料审核", desc: "script_templates 五类底料，支持审核、归档、启停" },
  { key: "personas", label: "AI 人设", desc: "persona_prompts 语气、人设 Prompt 和安全注记" },
  { key: "redlines", label: "禁用词", desc: "安全红线 regex，停用后热加载不再拦截" },
  { key: "intents", label: "意图 taxonomy", desc: "关键词规则、置信度、优先级和启停" },
];

const scriptEmpty: ScriptForm = {
  category_key: "greeting",
  title: "",
  language: "zh",
  channel: "telegram_real_user",
  platform: "telegram_real_user",
  user_level: "",
  chat_route: "ai_auto",
  persona_slug: "",
  hook: "reply",
  content: "",
  variables: "",
  safety_tags: "safe",
  status: "draft",
};

const SCRIPT_CATEGORY_OPTIONS = [
  "greeting",
  "conversion",
  "refusal",
  "probe",
  "fallback",
  "app_download_first_push",
  "app_download_after_warmup",
  "app_download_direct_cta",
  "app_download_objection",
  "trust_reassurance",
  "app_link_clicked_followup",
  "app_downloaded_not_registered",
  "app_registered_not_paid",
  "operator_app_conversion",
];

const SCRIPT_CATEGORY_LABELS: Record<string, string> = {
  greeting: "开场问候",
  conversion: "转化话术",
  refusal: "拒绝/安全",
  probe: "探测话术",
  fallback: "兜底回复",
  app_download_first_push: "App下载-首次引导",
  app_download_after_warmup: "App下载-升温后引导",
  app_download_direct_cta: "App下载-直接要链接",
  app_download_objection: "App下载-异议处理",
  trust_reassurance: "App下载-信任解释",
  app_link_clicked_followup: "App下载-已点击未下载",
  app_downloaded_not_registered: "App下载-已下载未注册",
  app_registered_not_paid: "App下载-已注册未付费",
  operator_app_conversion: "App下载-人工/高价值转化",
};

const personaEmpty: PersonaForm = {
  slug: "",
  display_name: "",
  language: "zh",
  tone_family: "warm",
  prompt_text: "",
  safety_notes: "",
  status: "active",
};

const intentEmpty: IntentForm = {
  id: "",
  intent: "",
  priority: "80",
  confidence: "0.82",
  keywords: "",
  patterns: "",
  excludes: "",
  enabled: true,
};

const redlineEmpty: RedlineForm = {
  id: "",
  category: "",
  reason: "redline:",
  patterns: "",
  enabled: true,
};

export default function AiOpsPage() {
  return (
    <AuthGate>
      {(operator) => <AiOpsContent operator={operator} />}
    </AuthGate>
  );
}

function AiOpsContent({ operator }: { operator: Operator }) {
  const [tab, setTab] = useState<TabKey>("scripts");
  const [scripts, setScripts] = useState<ScriptTemplate[]>([]);
  const [personas, setPersonas] = useState<PersonaPrompt[]>([]);
  const [intentRules, setIntentRules] = useState<IntentRule[]>([]);
  const [redlines, setRedlines] = useState<Redline[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [scriptForm, setScriptForm] = useState<ScriptForm>(scriptEmpty);
  const [personaForm, setPersonaForm] = useState<PersonaForm>(personaEmpty);
  const [intentForm, setIntentForm] = useState<IntentForm>(intentEmpty);
  const [redlineForm, setRedlineForm] = useState<RedlineForm>(redlineEmpty);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [scriptResp, personaResp, intentResp, redlineResp] = await Promise.all([
        apiFetch<{ items: ScriptTemplate[] }>("/ai-ops/admin/script-templates?limit=300"),
        apiFetch<{ items: PersonaPrompt[] }>("/ai-ops/admin/persona-prompts"),
        apiFetch<{ items: IntentRule[] }>("/ai-ops/admin/intent-rules"),
        apiFetch<{ items: Redline[] }>("/ai-ops/admin/redlines"),
      ]);
      setScripts(scriptResp.items);
      setPersonas(personaResp.items);
      setIntentRules(intentResp.items);
      setRedlines(redlineResp.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const scriptCounts = useMemo(() => countBy(scripts, (row) => row.status || "unknown"), [scripts]);
  const personaCounts = useMemo(() => countBy(personas, (row) => row.status || "unknown"), [personas]);
  const activeIntentCount = intentRules.filter((row) => row.enabled !== false).length;
  const activeRedlineCount = redlines.filter((row) => row.enabled !== false).length;

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 2200);
  }

  async function saveScript(event: React.FormEvent) {
    event.preventDefault();
    if (!scriptForm.title.trim() || !scriptForm.content.trim()) {
      setError("话术标题和内容不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        category_key: scriptForm.category_key,
        title: scriptForm.title.trim(),
        language: scriptForm.language,
        channel: scriptForm.channel,
        platform: scriptForm.platform,
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
        notify("话术已更新");
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

  async function savePersona(event: React.FormEvent) {
    event.preventDefault();
    if (!personaForm.slug.trim() || !personaForm.display_name.trim() || !personaForm.prompt_text.trim()) {
      setError("人设 slug、名称和 Prompt 不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        slug: personaForm.slug.trim(),
        display_name: personaForm.display_name.trim(),
        language: personaForm.language,
        tone_family: personaForm.tone_family.trim(),
        prompt_text: personaForm.prompt_text.trim(),
        safety_notes: splitList(personaForm.safety_notes),
        status: personaForm.status,
      };
      if (personaForm.id) {
        await apiFetch(`/ai-ops/admin/persona-prompts/${personaForm.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify("人设已更新");
      } else {
        await apiFetch("/ai-ops/admin/persona-prompts", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        notify("人设已新增");
      }
      setPersonaForm(personaEmpty);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function saveIntent(event: React.FormEvent) {
    event.preventDefault();
    if (!intentForm.id.trim() || !intentForm.intent.trim()) {
      setError("意图规则 ID 和 intent 不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        id: intentForm.id.trim(),
        intent: intentForm.intent.trim(),
        priority: Number(intentForm.priority),
        confidence: Number(intentForm.confidence),
        keywords: splitList(intentForm.keywords),
        patterns: splitLines(intentForm.patterns),
        excludes: splitList(intentForm.excludes),
        enabled: intentForm.enabled,
      };
      if (intentForm.originalId) {
        await apiFetch(`/ai-ops/admin/intent-rules/${encodeURIComponent(intentForm.originalId)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify("意图规则已更新");
      } else {
        await apiFetch("/ai-ops/admin/intent-rules", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        notify("意图规则已新增");
      }
      setIntentForm(intentEmpty);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function saveRedline(event: React.FormEvent) {
    event.preventDefault();
    if (!redlineForm.id.trim() || !redlineForm.category.trim() || !redlineForm.reason.trim()) {
      setError("禁用词 ID、类别和原因不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        id: redlineForm.id.trim(),
        category: redlineForm.category.trim(),
        reason: redlineForm.reason.trim(),
        patterns: splitLines(redlineForm.patterns),
        enabled: redlineForm.enabled,
      };
      if (redlineForm.originalId) {
        await apiFetch(`/ai-ops/admin/redlines/${encodeURIComponent(redlineForm.originalId)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify("禁用词规则已更新");
      } else {
        await apiFetch("/ai-ops/admin/redlines", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        notify("禁用词规则已新增");
      }
      setRedlineForm(redlineEmpty);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function archiveScript(row: ScriptTemplate) {
    if (!window.confirm(`确认归档话术：${row.title}？`)) return;
    await apiFetch(`/ai-ops/admin/script-templates/${row.id}`, { method: "DELETE" });
    notify("话术已归档");
    await load();
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

  async function archivePersona(row: PersonaPrompt) {
    if (!window.confirm(`确认归档人设：${row.display_name}？`)) return;
    await apiFetch(`/ai-ops/admin/persona-prompts/${row.id}`, { method: "DELETE" });
    notify("人设已归档");
    await load();
  }

  async function togglePersona(row: PersonaPrompt) {
    const nextStatus = row.status === "active" ? "inactive" : "active";
    await apiFetch(`/ai-ops/admin/persona-prompts/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus }),
    });
    notify(nextStatus === "active" ? "人设已启用" : "人设已停用");
    await load();
  }

  async function deleteIntent(row: IntentRule) {
    if (!window.confirm(`确认删除意图规则：${row.id}？`)) return;
    await apiFetch(`/ai-ops/admin/intent-rules/${encodeURIComponent(row.id)}`, { method: "DELETE" });
    notify("意图规则已删除");
    await load();
  }

  async function toggleIntent(row: IntentRule) {
    await apiFetch(`/ai-ops/admin/intent-rules/${encodeURIComponent(row.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ ...row, enabled: row.enabled === false }),
    });
    notify(row.enabled === false ? "意图规则已启用" : "意图规则已停用");
    await load();
  }

  async function deleteRedline(row: Redline) {
    if (!window.confirm(`确认删除禁用词规则：${row.id}？`)) return;
    await apiFetch(`/ai-ops/admin/redlines/${encodeURIComponent(row.id)}`, { method: "DELETE" });
    notify("禁用词规则已删除");
    await load();
  }

  async function toggleRedline(row: Redline) {
    await apiFetch(`/ai-ops/admin/redlines/${encodeURIComponent(row.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ ...row, enabled: row.enabled === false }),
    });
    notify(row.enabled === false ? "禁用词规则已启用" : "禁用词规则已停用");
    await load();
  }

  return (
    <AdminFrame
      operator={operator}
      active="ai"
      title="AI话术与人设"
      subtitle="统一管理 H-03 话术底料审核、H-04 AI 人设与禁用词、P3-05 意图 taxonomy，并服务 P3-21 script_match 命中审计。支持新增、编辑、删除、启用停用和审核归档。"
    >
      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="H-03 已批准话术" value={`${scriptCounts.approved || 0}`} hint={`草稿 ${scriptCounts.draft || 0} / 归档 ${scriptCounts.archived || 0}`} />
        <Metric label="H-04 启用人设" value={`${personaCounts.active || 0}`} hint={`停用 ${personaCounts.inactive || 0} / 归档 ${personaCounts.archived || 0}`} />
        <Metric label="禁用词生效规则" value={`${activeRedlineCount}`} hint={`总计 ${redlines.length}`} />
        <Metric label="意图规则生效" value={`${activeIntentCount}`} hint={`总计 ${intentRules.length}`} />
      </section>

      {error && <div className="mb-4 rounded-lg border border-rose-800 bg-rose-950/50 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {toast && <div className="fixed bottom-6 right-6 z-50 rounded-lg border border-emerald-700 bg-emerald-950 px-5 py-3 text-sm text-emerald-100 shadow-xl">{toast}</div>}

      <div className="mb-5 flex flex-wrap gap-2">
        {tabs.map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`rounded-md px-4 py-2 text-sm transition ${tab === item.key ? "bg-violet-600 text-white" : "border border-slate-800 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mb-4 rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
        <div className="text-sm font-medium text-slate-100">{tabs.find((item) => item.key === tab)?.label}</div>
        <div className="mt-1 text-sm text-slate-500">{tabs.find((item) => item.key === tab)?.desc}</div>
      </div>

      {loading && <div className="rounded-lg border border-slate-800 bg-slate-900 p-5 text-sm text-slate-400">加载中...</div>}

      {!loading && tab === "scripts" && (
        <TwoColumn
          form={
            <ScriptEditor
              form={scriptForm}
              personas={personas}
              saving={saving}
              onChange={setScriptForm}
              onSubmit={saveScript}
              onCancel={() => setScriptForm(scriptEmpty)}
            />
          }
          list={<ScriptList rows={scripts} onEdit={(row) => setScriptForm(scriptToForm(row))} onArchive={archiveScript} onToggle={toggleScript} />}
        />
      )}

      {!loading && tab === "personas" && (
        <TwoColumn
          form={
            <PersonaEditor
              form={personaForm}
              saving={saving}
              onChange={setPersonaForm}
              onSubmit={savePersona}
              onCancel={() => setPersonaForm(personaEmpty)}
            />
          }
          list={<PersonaList rows={personas} onEdit={(row) => setPersonaForm(personaToForm(row))} onArchive={archivePersona} onToggle={togglePersona} />}
        />
      )}

      {!loading && tab === "redlines" && (
        <TwoColumn
          form={
            <RedlineEditor
              form={redlineForm}
              saving={saving}
              onChange={setRedlineForm}
              onSubmit={saveRedline}
              onCancel={() => setRedlineForm(redlineEmpty)}
            />
          }
          list={<RedlineList rows={redlines} onEdit={(row) => setRedlineForm(redlineToForm(row))} onDelete={deleteRedline} onToggle={toggleRedline} />}
        />
      )}

      {!loading && tab === "intents" && (
        <TwoColumn
          form={
            <IntentEditor
              form={intentForm}
              saving={saving}
              onChange={setIntentForm}
              onSubmit={saveIntent}
              onCancel={() => setIntentForm(intentEmpty)}
            />
          }
          list={<IntentList rows={intentRules} onEdit={(row) => setIntentForm(intentToForm(row))} onDelete={deleteIntent} onToggle={toggleIntent} />}
        />
      )}
    </AdminFrame>
  );
}

function TwoColumn({ form, list }: { form: React.ReactNode; list: React.ReactNode }) {
  return (
    <section className="grid grid-cols-1 gap-5 xl:grid-cols-[420px_1fr]">
      <div>{form}</div>
      <div>{list}</div>
    </section>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{hint}</div>
    </div>
  );
}

function ScriptEditor({ form, personas, saving, onChange, onSubmit, onCancel }: { form: ScriptForm; personas: PersonaPrompt[]; saving: boolean; onChange: (form: ScriptForm) => void; onSubmit: (event: React.FormEvent) => void; onCancel: () => void }) {
  return (
    <Panel title={form.id ? "编辑话术底料" : "新增话术底料"}>
      <form onSubmit={onSubmit} className="space-y-3">
        <Input label="标题" value={form.title} onChange={(v) => onChange({ ...form, title: v })} />
        <Select label="类目" value={form.category_key} options={SCRIPT_CATEGORY_OPTIONS} labels={SCRIPT_CATEGORY_LABELS} onChange={(v) => onChange({ ...form, category_key: v })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="语言" value={form.language} onChange={(v) => onChange({ ...form, language: v })} />
          <Select label="审核状态" value={form.status} options={["draft", "approved", "archived"]} onChange={(v) => onChange({ ...form, status: v })} />
          <Select label="等级" value={form.user_level} options={["", "S", "A", "B", "C", "D"]} onChange={(v) => onChange({ ...form, user_level: v })} />
          <Select label="路由" value={form.chat_route} options={["", "manual_premium", "ai_assisted", "ai_auto"]} onChange={(v) => onChange({ ...form, chat_route: v })} />
          <Input label="hook" value={form.hook} onChange={(v) => onChange({ ...form, hook: v })} />
          <Input label="平台" value={form.platform} onChange={(v) => onChange({ ...form, platform: v })} />
        </div>
        <Select label="persona" value={form.persona_slug} options={["", ...personas.map((item) => item.slug)]} onChange={(v) => onChange({ ...form, persona_slug: v })} />
        <TextArea label="话术内容" rows={5} value={form.content} onChange={(v) => onChange({ ...form, content: v })} />
        <Input label="变量，逗号分隔" value={form.variables} onChange={(v) => onChange({ ...form, variables: v })} />
        <Input label="安全标签，逗号分隔" value={form.safety_tags} onChange={(v) => onChange({ ...form, safety_tags: v })} />
        <FormActions saving={saving} primary={form.id ? "保存修改" : "新增话术"} onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function PersonaEditor({ form, saving, onChange, onSubmit, onCancel }: { form: PersonaForm; saving: boolean; onChange: (form: PersonaForm) => void; onSubmit: (event: React.FormEvent) => void; onCancel: () => void }) {
  return (
    <Panel title={form.id ? "编辑 AI 人设" : "新增 AI 人设"}>
      <form onSubmit={onSubmit} className="space-y-3">
        <Input label="slug" value={form.slug} onChange={(v) => onChange({ ...form, slug: v })} />
        <Input label="显示名称" value={form.display_name} onChange={(v) => onChange({ ...form, display_name: v })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="语言" value={form.language} onChange={(v) => onChange({ ...form, language: v })} />
          <Select label="状态" value={form.status} options={["draft", "active", "inactive", "archived"]} onChange={(v) => onChange({ ...form, status: v })} />
        </div>
        <Input label="语气族" value={form.tone_family} onChange={(v) => onChange({ ...form, tone_family: v })} />
        <TextArea label="Persona Prompt" rows={7} value={form.prompt_text} onChange={(v) => onChange({ ...form, prompt_text: v })} />
        <TextArea label="安全注记，每行一条" rows={4} value={form.safety_notes} onChange={(v) => onChange({ ...form, safety_notes: v })} />
        <FormActions saving={saving} primary={form.id ? "保存修改" : "新增人设"} onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function IntentEditor({ form, saving, onChange, onSubmit, onCancel }: { form: IntentForm; saving: boolean; onChange: (form: IntentForm) => void; onSubmit: (event: React.FormEvent) => void; onCancel: () => void }) {
  return (
    <Panel title={form.originalId ? "编辑意图规则" : "新增意图规则"}>
      <form onSubmit={onSubmit} className="space-y-3">
        <Input label="规则 ID" value={form.id} onChange={(v) => onChange({ ...form, id: v })} />
        <Input label="intent taxonomy ID" value={form.intent} onChange={(v) => onChange({ ...form, intent: v })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="优先级" value={form.priority} onChange={(v) => onChange({ ...form, priority: v })} />
          <Input label="置信度" value={form.confidence} onChange={(v) => onChange({ ...form, confidence: v })} />
        </div>
        <TextArea label="关键词，逗号或换行分隔" rows={4} value={form.keywords} onChange={(v) => onChange({ ...form, keywords: v })} />
        <TextArea label="正则 pattern，每行一条" rows={4} value={form.patterns} onChange={(v) => onChange({ ...form, patterns: v })} />
        <TextArea label="排除词，逗号或换行分隔" rows={3} value={form.excludes} onChange={(v) => onChange({ ...form, excludes: v })} />
        <Toggle label="启用该意图规则" checked={form.enabled} onChange={(v) => onChange({ ...form, enabled: v })} />
        <FormActions saving={saving} primary={form.originalId ? "保存修改" : "新增规则"} onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function RedlineEditor({ form, saving, onChange, onSubmit, onCancel }: { form: RedlineForm; saving: boolean; onChange: (form: RedlineForm) => void; onSubmit: (event: React.FormEvent) => void; onCancel: () => void }) {
  return (
    <Panel title={form.originalId ? "编辑禁用词" : "新增禁用词"}>
      <form onSubmit={onSubmit} className="space-y-3">
        <Input label="规则 ID" value={form.id} onChange={(v) => onChange({ ...form, id: v })} />
        <Input label="类别" value={form.category} onChange={(v) => onChange({ ...form, category: v })} />
        <Input label="拦截原因" value={form.reason} onChange={(v) => onChange({ ...form, reason: v })} />
        <TextArea label="正则 pattern，每行一条" rows={6} value={form.patterns} onChange={(v) => onChange({ ...form, patterns: v })} />
        <Toggle label="启用该禁用词规则" checked={form.enabled} onChange={(v) => onChange({ ...form, enabled: v })} />
        <FormActions saving={saving} primary={form.originalId ? "保存修改" : "新增禁用词"} onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function ScriptList({ rows, onEdit, onArchive, onToggle }: { rows: ScriptTemplate[]; onEdit: (row: ScriptTemplate) => void; onArchive: (row: ScriptTemplate) => void; onToggle: (row: ScriptTemplate) => void }) {
  return (
    <Panel title="话术底料列表">
      <div className="divide-y divide-slate-800">
        {rows.map((row) => (
          <ListRow key={row.id} title={row.title} subtitle={`${scriptCategoryLabel(row.category_key)} / ${row.category_key} / ${row.hook || "-"} / ${row.persona_slug || "通用"}`} badge={row.status}>
            <p className="mb-3 line-clamp-2 text-sm text-slate-400">{row.content}</p>
            <RowActions onEdit={() => onEdit(row)} onToggle={() => onToggle(row)} toggleText={row.status === "approved" ? "停用" : "启用"} onDelete={() => onArchive(row)} deleteText="归档" />
          </ListRow>
        ))}
      </div>
    </Panel>
  );
}

function PersonaList({ rows, onEdit, onArchive, onToggle }: { rows: PersonaPrompt[]; onEdit: (row: PersonaPrompt) => void; onArchive: (row: PersonaPrompt) => void; onToggle: (row: PersonaPrompt) => void }) {
  return (
    <Panel title="AI 人设列表">
      <div className="divide-y divide-slate-800">
        {rows.map((row) => (
          <ListRow key={row.id} title={row.display_name} subtitle={`${row.slug} / ${row.tone_family}`} badge={row.status}>
            <p className="mb-3 line-clamp-2 text-sm text-slate-400">{row.prompt_text}</p>
            <RowActions onEdit={() => onEdit(row)} onToggle={() => onToggle(row)} toggleText={row.status === "active" ? "停用" : "启用"} onDelete={() => onArchive(row)} deleteText="归档" />
          </ListRow>
        ))}
      </div>
    </Panel>
  );
}

function RedlineList({ rows, onEdit, onDelete, onToggle }: { rows: Redline[]; onEdit: (row: Redline) => void; onDelete: (row: Redline) => void; onToggle: (row: Redline) => void }) {
  return (
    <Panel title="禁用词 / 安全红线">
      <div className="divide-y divide-slate-800">
        {rows.map((row) => (
          <ListRow key={row.id} title={row.id} subtitle={`${row.category} / ${row.reason}`} badge={row.enabled === false ? "disabled" : "enabled"}>
            <p className="mb-3 text-sm text-slate-400">{row.patterns.join(" / ")}</p>
            <RowActions onEdit={() => onEdit(row)} onToggle={() => onToggle(row)} toggleText={row.enabled === false ? "启用" : "停用"} onDelete={() => onDelete(row)} deleteText="删除" />
          </ListRow>
        ))}
      </div>
    </Panel>
  );
}

function IntentList({ rows, onEdit, onDelete, onToggle }: { rows: IntentRule[]; onEdit: (row: IntentRule) => void; onDelete: (row: IntentRule) => void; onToggle: (row: IntentRule) => void }) {
  return (
    <Panel title="意图 taxonomy 规则">
      <div className="divide-y divide-slate-800">
        {rows.map((row) => (
          <ListRow key={row.id} title={row.intent} subtitle={`${row.id} / priority ${row.priority} / confidence ${row.confidence}`} badge={row.enabled === false ? "disabled" : "enabled"}>
            <p className="mb-3 text-sm text-slate-400">{(row.keywords || []).slice(0, 8).join(" / ")}</p>
            <RowActions onEdit={() => onEdit(row)} onToggle={() => onToggle(row)} toggleText={row.enabled === false ? "启用" : "停用"} onDelete={() => onDelete(row)} deleteText="删除" />
          </ListRow>
        ))}
      </div>
    </Panel>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-5 py-4 text-lg font-semibold text-slate-100">{title}</h2>
      <div className="p-5">{children}</div>
    </div>
  );
}

function ListRow({ title, subtitle, badge, children }: { title: string; subtitle: string; badge: string; children: React.ReactNode }) {
  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="font-medium text-slate-100">{title}</div>
          <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs ${badgeClass(badge)}`}>{badge}</span>
      </div>
      {children}
    </div>
  );
}

function RowActions({ onEdit, onToggle, onDelete, toggleText, deleteText }: { onEdit: () => void; onToggle: () => void; onDelete: () => void; toggleText: string; deleteText: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button onClick={onEdit} className="rounded-md bg-slate-800 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-700">编辑</button>
      <button onClick={onToggle} className="rounded-md border border-amber-700 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-950">{toggleText}</button>
      <button onClick={onDelete} className="rounded-md border border-rose-800 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-950">{deleteText}</button>
    </div>
  );
}

function FormActions({ saving, primary, onCancel }: { saving: boolean; primary: string; onCancel: () => void }) {
  return (
    <div className="flex gap-3 pt-2">
      <button disabled={saving} className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50">{saving ? "保存中..." : primary}</button>
      <button type="button" onClick={onCancel} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">清空</button>
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
            {option ? (labels?.[option] || option) : "不限"}
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
      <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500" />
    </label>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-200">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4" />
      {label}
    </label>
  );
}

function badgeClass(status: string) {
  if (status === "approved" || status === "active" || status === "enabled") return "bg-emerald-500/10 text-emerald-300";
  if (status === "draft" || status === "inactive" || status === "disabled") return "bg-amber-500/10 text-amber-300";
  return "bg-slate-800 text-slate-400";
}

function scriptCategoryLabel(categoryKey: string): string {
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

function personaToForm(row: PersonaPrompt): PersonaForm {
  return {
    id: row.id,
    slug: row.slug,
    display_name: row.display_name,
    language: row.language || "zh",
    tone_family: row.tone_family || "warm",
    prompt_text: row.prompt_text || "",
    safety_notes: listToText(row.safety_notes),
    status: row.status || "active",
  };
}

function intentToForm(row: IntentRule): IntentForm {
  return {
    originalId: row.id,
    id: row.id,
    intent: row.intent,
    priority: String(row.priority ?? 0),
    confidence: String(row.confidence ?? 0.75),
    keywords: listToText(row.keywords),
    patterns: (row.patterns || []).join("\n"),
    excludes: listToText(row.excludes || []),
    enabled: row.enabled !== false,
  };
}

function redlineToForm(row: Redline): RedlineForm {
  return {
    originalId: row.id,
    id: row.id,
    category: row.category,
    reason: row.reason,
    patterns: (row.patterns || []).join("\n"),
    enabled: row.enabled !== false,
  };
}

function splitList(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function splitLines(value: string): string[] {
  return value.split(/\n/).map((item) => item.trim()).filter(Boolean);
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

function countBy<T>(rows: T[], key: (row: T) => string): Record<string, number> {
  return rows.reduce<Record<string, number>>((acc, row) => {
    const value = key(row);
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}
