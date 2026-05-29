/* eslint-disable @next/next/no-img-element */
"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, getToken, Operator } from "@/lib/auth";

type ScriptAsset = {
  id: string;
  asset_type: "image" | "video" | "voice" | "audio";
  asset_url: string;
  original_filename?: string | null;
  mime_type?: string | null;
  caption?: string | null;
  sort_order: number;
};

type DownloadPlatform = {
  id: string;
  platform_key: string;
  display_name: string;
  download_url: string;
  is_active: boolean;
  is_default: boolean;
  sort_order: number;
};

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
  operator_translation_zh?: string | null;
  variables: unknown[] | string | null;
  safety_tags: unknown[] | string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  assets?: ScriptAsset[];
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
  operator_translation_zh: string;
  variables: string;
  safety_tags: string;
  status: string;
};

type PlatformForm = {
  platform_key: string;
  display_name: string;
  download_url: string;
};

const scriptEmpty: ScriptForm = {
  category_key: "app_download_first_push",
  title: "",
  language: "en",
  channel: "telegram_real_user",
  platform: "telegram_real_user",
  user_level: "",
  chat_route: "ai_auto",
  persona_slug: "",
  hook: "reply",
  content: "",
  operator_translation_zh: "",
  variables: "app_download_url",
  safety_tags: "app_download_conversion",
  status: "draft",
};

const platformEmpty: PlatformForm = {
  platform_key: "platform_a",
  display_name: "A平台",
  download_url: "",
};

const PLATFORM_PRESETS = [
  { platform_key: "platform_a", display_name: "A平台" },
  { platform_key: "platform_b", display_name: "B平台" },
  { platform_key: "platform_c", display_name: "C平台" },
];

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

const ASSET_LABELS: Record<string, string> = {
  image: "图片",
  video: "视频",
  voice: "语音",
  audio: "音频",
};

const ASSET_ACCEPT: Record<string, string> = {
  image: "image/*",
  video: "video/*",
  voice: "audio/*",
  audio: "audio/*",
};

async function loadAllScriptTemplates() {
  const pageSize = 500;
  const items: ScriptTemplate[] = [];

  for (let offset = 0; ; offset += pageSize) {
    const response = await apiFetch<{ items: ScriptTemplate[] }>(
      `/ai-ops/admin/script-templates?limit=${pageSize}&offset=${offset}`,
    );
    items.push(...response.items);
    if (response.items.length < pageSize) return items;
  }
}

export default function AiOpsPage() {
  return (
    <AuthGate>
      {(operator) => <AiOpsContent operator={operator} />}
    </AuthGate>
  );
}

function AiOpsContent({ operator }: { operator: Operator }) {
  const [scripts, setScripts] = useState<ScriptTemplate[]>([]);
  const [platforms, setPlatforms] = useState<DownloadPlatform[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [platformSaving, setPlatformSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("active");
  const [scriptForm, setScriptForm] = useState<ScriptForm>(scriptEmpty);
  const [platformForm, setPlatformForm] = useState<PlatformForm>(platformEmpty);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [scriptResponse, platformResponse] = await Promise.all([
        loadAllScriptTemplates(),
        apiFetch<{ items: DownloadPlatform[] }>("/ai-ops/admin/app-download-platforms"),
      ]);
      setScripts(scriptResponse);
      setPlatforms(platformResponse.items);
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
      return [row.title, row.content, row.category_key, categoryLabel(row.category_key), row.language].some((value) =>
        String(value || "").toLowerCase().includes(needle),
      );
    }).sort((a, b) => newestTime(b) - newestTime(a));
  }, [categoryFilter, query, scripts, statusFilter]);

  const currentAssets = scriptForm.id ? scripts.find((item) => item.id === scriptForm.id)?.assets || [] : [];
  const totalActiveCount = scripts.filter((row) => row.status !== "archived").length;
  const appDownloadCount = scripts.filter((row) => APP_DOWNLOAD_CATEGORY_KEYS.has(row.category_key) && row.status !== "archived").length;
  const approvedCount = visibleScripts.filter((row) => row.status === "approved").length;
  const defaultPlatform = platforms.find((item) => item.is_default && item.is_active) || platforms.find((item) => item.is_active);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 2200);
  }

  async function savePlatform(event: FormEvent) {
    event.preventDefault();
    if (!platformForm.display_name.trim() || !platformForm.download_url.trim()) {
      setError("平台名称和下载链接不能为空");
      return;
    }
    setPlatformSaving(true);
    setError(null);
    try {
      await apiFetch("/ai-ops/admin/app-download-platforms", {
        method: "POST",
        body: JSON.stringify({
          ...platformForm,
          platform_key: platformForm.platform_key.trim(),
          display_name: platformForm.display_name.trim(),
          download_url: platformForm.download_url.trim(),
          is_active: true,
          is_default: platforms.length === 0,
          sort_order: platforms.length,
        }),
      });
      setPlatformForm(platformEmpty);
      notify("三方平台已添加");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlatformSaving(false);
    }
  }

  async function patchPlatform(id: string, payload: Partial<DownloadPlatform>) {
    await apiFetch(`/ai-ops/admin/app-download-platforms/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await load();
  }

  async function deletePlatform(id: string) {
    if (!window.confirm("确认删除这个三方平台链接？")) return;
    await apiFetch(`/ai-ops/admin/app-download-platforms/${id}`, { method: "DELETE" });
    notify("三方平台已删除");
    await load();
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
        language: scriptForm.language.trim() || "en",
        channel: scriptForm.channel.trim() || "telegram_real_user",
        platform: scriptForm.platform.trim() || "telegram_real_user",
        user_level: scriptForm.user_level || null,
        chat_route: scriptForm.chat_route || null,
        persona_slug: scriptForm.persona_slug.trim() || null,
        hook: scriptForm.hook.trim() || null,
        content: scriptForm.content.trim(),
        operator_translation_zh: scriptForm.operator_translation_zh.trim() || null,
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
        await apiFetch<ScriptTemplate>("/ai-ops/admin/script-templates", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setScriptForm(scriptEmpty);
        setCategoryFilter("all");
        notify("话术已新增，可以继续上传附件");
      }
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

  async function uploadAsset(templateId: string, file: File, assetType: string) {
    setUploading(true);
    setError(null);
    try {
      const token = getToken();
      const body = new FormData();
      body.append("file", file);
      body.append("asset_type", assetType);
      const response = await fetch(`/api/v1/ai-ops/admin/script-templates/${templateId}/assets`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body,
      });
      if (!response.ok) {
        const err = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail || response.statusText);
      }
      notify("附件已上传");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function deleteAsset(assetId: string) {
    if (!window.confirm("确认删除这个附件？")) return;
    await apiFetch(`/ai-ops/admin/script-template-assets/${assetId}`, { method: "DELETE" });
    notify("附件已删除");
    await load();
  }

  async function moveAsset(asset: ScriptAsset, direction: -1 | 1) {
    const ordered = [...currentAssets].sort((a, b) => a.sort_order - b.sort_order);
    const index = ordered.findIndex((item) => item.id === asset.id);
    const target = ordered[index + direction];
    if (!target) return;

    await Promise.all([
      apiFetch(`/ai-ops/admin/script-template-assets/${asset.id}?sort_order=${target.sort_order}`, { method: "PATCH" }),
      apiFetch(`/ai-ops/admin/script-template-assets/${target.id}?sort_order=${asset.sort_order}`, { method: "PATCH" }),
    ]);
    await load();
  }

  return (
    <AdminFrame
      operator={operator}
      active="ai"
      title="话术库管理"
      subtitle="管理下载引导话术、媒体附件和三方平台下载链接。话术里的 {{app_download_url}} 会自动替换成默认平台的追踪链接。"
    >
      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="全部话术" value={`${totalActiveCount}`} hint="未归档的所有话术，不限制数量" />
        <Metric label="下载引导话术" value={`${appDownloadCount}`} hint="未归档的 App 下载类目话术" />
        <Metric label="当前列表启用" value={`${approvedCount}`} hint="当前筛选下会被系统自动匹配使用" />
        <Metric label="默认三方平台" value={defaultPlatform?.display_name || "-"} hint="用户点击追踪链接后跳转到这里" />
      </section>

      {error && <div className="mb-4 rounded-md border border-rose-800 bg-rose-950/50 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {toast && <div className="fixed bottom-6 right-6 z-50 rounded-md border border-emerald-700 bg-emerald-950 px-5 py-3 text-sm text-emerald-100 shadow-xl">{toast}</div>}

      <DownloadPlatformPanel
        platforms={platforms}
        form={platformForm}
        saving={platformSaving}
        onChange={setPlatformForm}
        onSubmit={savePlatform}
        onPatch={patchPlatform}
        onDelete={deletePlatform}
      />

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-[390px_1fr]">
        <ScriptEditor
          form={scriptForm}
          saving={saving}
          uploading={uploading}
          assets={currentAssets}
          onChange={setScriptForm}
          onSubmit={saveScript}
          onCancel={() => setScriptForm(scriptEmpty)}
          onUploadAsset={uploadAsset}
          onDeleteAsset={deleteAsset}
          onMoveAsset={moveAsset}
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

function DownloadPlatformPanel({
  platforms,
  form,
  saving,
  onChange,
  onSubmit,
  onPatch,
  onDelete,
}: {
  platforms: DownloadPlatform[];
  form: PlatformForm;
  saving: boolean;
  onChange: (form: PlatformForm) => void;
  onSubmit: (event: FormEvent) => void;
  onPatch: (id: string, payload: Partial<DownloadPlatform>) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <section className="mb-6 rounded-md border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-5 py-4">
        <h2 className="text-lg font-semibold text-slate-100">三方平台下载链接</h2>
      </div>
      <div className="grid grid-cols-1 gap-5 p-5 xl:grid-cols-[380px_1fr]">
        <form onSubmit={onSubmit} className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {PLATFORM_PRESETS.map((preset) => (
              <button
                key={preset.platform_key}
                type="button"
                onClick={() => onChange({ ...form, ...preset })}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
              >
                {preset.display_name}
              </button>
            ))}
          </div>
          <Input label="平台标识" value={form.platform_key} onChange={(value) => onChange({ ...form, platform_key: value })} />
          <Input label="平台名称" value={form.display_name} onChange={(value) => onChange({ ...form, display_name: value })} />
          <Input label="三方下载链接" value={form.download_url} onChange={(value) => onChange({ ...form, download_url: value })} />
          <button disabled={saving} className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50">
            {saving ? "保存中..." : "添加平台"}
          </button>
        </form>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-950/50 text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">平台</th>
                <th className="px-4 py-3 font-medium">链接</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {platforms.length === 0 ? (
                <tr>
                  <td className="px-4 py-8 text-slate-500" colSpan={4}>暂无平台，先添加 A平台 / B平台 / C平台</td>
                </tr>
              ) : (
                platforms.map((platform) => (
                  <tr key={platform.id}>
                    <td className="px-4 py-4 text-slate-100">
                      <div className="font-medium">{platform.display_name}</div>
                      <div className="mt-1 font-mono text-xs text-slate-500">{platform.platform_key}</div>
                    </td>
                    <td className="max-w-[360px] px-4 py-4">
                      <a className="block truncate text-sky-300 hover:text-sky-200" href={platform.download_url} target="_blank" rel="noreferrer">
                        {platform.download_url}
                      </a>
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex flex-wrap gap-2">
                        {platform.is_default && <span className="rounded bg-violet-500/10 px-2 py-1 text-xs text-violet-200">默认</span>}
                        <span className={`rounded px-2 py-1 text-xs ${platform.is_active ? "bg-emerald-500/10 text-emerald-200" : "bg-slate-800 text-slate-400"}`}>
                          {platform.is_active ? "启用" : "停用"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={() => onPatch(platform.id, { is_default: true, is_active: true })} className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">设默认</button>
                        <button type="button" onClick={() => onPatch(platform.id, { is_active: !platform.is_active })} className="rounded-md border border-amber-700 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-950">
                          {platform.is_active ? "停用" : "启用"}
                        </button>
                        <button type="button" onClick={() => onDelete(platform.id)} className="rounded-md border border-rose-800 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-950">删除</button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function ScriptEditor({
  form,
  saving,
  uploading,
  assets,
  onChange,
  onSubmit,
  onCancel,
  onUploadAsset,
  onDeleteAsset,
  onMoveAsset,
}: {
  form: ScriptForm;
  saving: boolean;
  uploading: boolean;
  assets: ScriptAsset[];
  onChange: (form: ScriptForm) => void;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
  onUploadAsset: (templateId: string, file: File, assetType: string) => void;
  onDeleteAsset: (assetId: string) => void;
  onMoveAsset: (asset: ScriptAsset, direction: -1 | 1) => void;
}) {
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
        <TextArea label="中文译文（仅后台运营查看，不会发送给用户）" rows={5} value={form.operator_translation_zh} onChange={(value) => onChange({ ...form, operator_translation_zh: value })} />

        <MediaManager
          templateId={form.id}
          assets={assets}
          uploading={uploading}
          onUploadAsset={onUploadAsset}
          onDeleteAsset={onDeleteAsset}
          onMoveAsset={onMoveAsset}
        />

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

function MediaManager({
  templateId,
  assets,
  uploading,
  onUploadAsset,
  onDeleteAsset,
  onMoveAsset,
}: {
  templateId?: string;
  assets: ScriptAsset[];
  uploading: boolean;
  onUploadAsset: (templateId: string, file: File, assetType: string) => void;
  onDeleteAsset: (assetId: string) => void;
  onMoveAsset: (asset: ScriptAsset, direction: -1 | 1) => void;
}) {
  const orderedAssets = [...assets].sort((a, b) => a.sort_order - b.sort_order);
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-100">附件上传区</div>
          <div className="mt-1 text-xs text-slate-500">命中话术后会按顺序发出，效果和正常聊天发送一致</div>
        </div>
        {!templateId && <span className="text-xs text-amber-300">先保存话术</span>}
      </div>

      {templateId && (
        <div className="grid grid-cols-2 gap-2">
          {(["image", "video", "voice", "audio"] as const).map((type) => (
            <label key={type} className="cursor-pointer rounded-md border border-slate-700 px-3 py-2 text-center text-xs text-slate-200 hover:bg-slate-800">
              {uploading ? "上传中..." : `上传${ASSET_LABELS[type]}`}
              <input
                type="file"
                accept={ASSET_ACCEPT[type]}
                className="hidden"
                disabled={uploading}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.currentTarget.value = "";
                  if (file) onUploadAsset(templateId, file, type);
                }}
              />
            </label>
          ))}
        </div>
      )}

      <div className="mt-3 space-y-2">
        {orderedAssets.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-800 px-3 py-4 text-center text-xs text-slate-500">暂无附件</div>
        ) : (
          orderedAssets.map((asset, index) => (
            <div key={asset.id} className="rounded-md border border-slate-800 bg-slate-900 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-slate-100">{ASSET_LABELS[asset.asset_type] || asset.asset_type}</div>
                  <a className="mt-1 block truncate text-xs text-slate-500 hover:text-slate-300" href={asset.asset_url} target="_blank" rel="noreferrer">
                    {asset.original_filename || asset.asset_url}
                  </a>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button type="button" disabled={index === 0} onClick={() => onMoveAsset(asset, -1)} className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40">上移</button>
                  <button type="button" disabled={index === orderedAssets.length - 1} onClick={() => onMoveAsset(asset, 1)} className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40">下移</button>
                  <button type="button" onClick={() => onDeleteAsset(asset.id)} className="rounded border border-rose-800 px-2 py-1 text-xs text-rose-200 hover:bg-rose-950">删除</button>
                </div>
              </div>
              <AssetPreview asset={asset} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function AssetPreview({ asset }: { asset: ScriptAsset }) {
  if (asset.asset_type === "image") {
    return <img src={asset.asset_url} alt="" className="mt-3 max-h-40 rounded-md border border-slate-800 object-contain" />;
  }
  if (asset.asset_type === "video") {
    return <video src={asset.asset_url} controls className="mt-3 max-h-44 w-full rounded-md border border-slate-800" />;
  }
  if (asset.asset_type === "voice" || asset.asset_type === "audio") {
    return <audio src={asset.asset_url} controls className="mt-3 w-full" />;
  }
  return null;
}

function ScriptRow({ row, onEdit, onToggle, onArchive }: { row: ScriptTemplate; onEdit: () => void; onToggle: () => void; onArchive: () => void }) {
  const assets = [...(row.assets || [])].sort((a, b) => a.sort_order - b.sort_order);
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
      <p className="mb-2 line-clamp-3 whitespace-pre-wrap text-sm text-slate-400">{row.content}</p>
      {row.operator_translation_zh && (
        <div className="mb-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
          <div className="mb-1 text-xs text-slate-500">中文译文（运营查看）</div>
          <p className="line-clamp-3 whitespace-pre-wrap text-sm text-slate-300">{row.operator_translation_zh}</p>
        </div>
      )}
      {assets.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {assets.map((asset) => (
            <span key={asset.id} className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{ASSET_LABELS[asset.asset_type] || asset.asset_type}</span>
          ))}
        </div>
      )}
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
      <div className="mt-2 truncate text-2xl font-semibold text-slate-100">{value}</div>
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
      <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm leading-6 text-slate-100 outline-none focus:border-violet-500" />
    </label>
  );
}

function categoryLabel(key: string) {
  return SCRIPT_CATEGORY_LABELS[key] || key;
}

function badgeClass(status: string) {
  if (status === "approved") return "bg-emerald-950 text-emerald-200";
  if (status === "archived") return "bg-slate-800 text-slate-400";
  return "bg-amber-950 text-amber-200";
}

function newestTime(row: ScriptTemplate) {
  const value = row.created_at || row.updated_at || "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToText(value: unknown[] | string | null | undefined) {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (typeof value === "string") return value;
  return "";
}

function scriptToForm(row: ScriptTemplate): ScriptForm {
  return {
    id: row.id,
    category_key: row.category_key,
    title: row.title,
    language: row.language || "en",
    channel: row.channel || "telegram_real_user",
    platform: row.platform || "telegram_real_user",
    user_level: row.user_level || "",
    chat_route: row.chat_route || "",
    persona_slug: row.persona_slug || "",
    hook: row.hook || "",
    content: row.content || "",
    operator_translation_zh: row.operator_translation_zh || "",
    variables: listToText(row.variables),
    safety_tags: listToText(row.safety_tags),
    status: row.status || "draft",
  };
}
