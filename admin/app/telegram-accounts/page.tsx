"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { apiFetch } from "@/lib/auth";

interface TelegramAccount {
  id: string;
  phone: string;
  status: string;
  is_active: boolean;
  display_name: string | null;
  admin_display_name?: string | null;
  username: string | null;
  user_id: number | null;
  is_connected: boolean;
  is_bot: boolean;
  last_connected_at: string | null;
  last_error_at: string | null;
  error_message: string | null;
  reply_mode: "ai" | "fixed";
  app_download_platform?: string;
  api_credential_id?: string | null;
  api_credential_name?: string | null;
}

interface TelegramAccountsResponse {
  accounts: TelegramAccount[];
  total: number;
  connected_count: number;
}

interface SessionLoginStartResponse {
  login_id: string;
  phone: string;
  expires_at: string;
  message: string;
}

interface SessionLoginVerifyResponse {
  account_id: string | null;
  phone: string | null;
  status: string;
  requires_password: boolean;
  message: string;
}

interface TelegramApiCredential {
  id: string | null;
  name: string;
  serial_no: number;
  serial_label: string;
  api_id: number;
  api_hash_masked: string;
  is_default: boolean;
  is_active: boolean;
  max_accounts: number | null;
  note: string | null;
  account_count: number;
}

interface TelegramApiCredentialListResponse {
  credentials: TelegramApiCredential[];
  total: number;
}

const emptyLoginForm = {
  phone: "",
  display_name: "",
  code: "",
  password: "",
  auto_connect: true,
  api_credential_id: "",
};

const emptyCredentialForm = {
  sort_order: "",
  name: "",
  api_id: "",
  api_hash: "",
  max_accounts: "",
  note: "",
};

const APP_DOWNLOAD_PLATFORM_OPTIONS = [
  { value: "default", label: "跟随A设为默认" },
  { value: "platform_a", label: "A平台" },
  { value: "platform_b", label: "B平台" },
  { value: "platform_c", label: "C平台" },
  { value: "platform_d", label: "D平台" },
  { value: "platform_e", label: "E平台" },
  { value: "platform_f", label: "F平台" },
];

export default function TelegramAccountsPage() {
  return (
    <AuthGate>
      {() => <TelegramAccountsManager />}
    </AuthGate>
  );
}

function TelegramAccountsManager() {
  const [accounts, setAccounts] = useState<TelegramAccount[]>([]);
  const [credentials, setCredentials] = useState<TelegramApiCredential[]>([]);
  const [credentialForm, setCredentialForm] = useState(emptyCredentialForm);
  const [showCredentialForm, setShowCredentialForm] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [formBusy, setFormBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(40);
  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState(emptyLoginForm);
  const [loginId, setLoginId] = useState<string | null>(null);
  const [codePhone, setCodePhone] = useState<string | null>(null);
  const [requiresPassword, setRequiresPassword] = useState(false);

  const loadCredentials = async () => {
    try {
      const resp = await apiFetch<TelegramApiCredentialListResponse>("/telegram/api-credentials");
      setCredentials(resp.credentials);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载开发者应用失败");
    }
  };

  const loadAccounts = async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setListLoading(true);
    if (!opts?.silent) setError(null);
    try {
      const resp = await apiFetch<TelegramAccountsResponse>("/telegram/accounts");
      setAccounts(resp.accounts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载账号列表失败");
    } finally {
      if (!opts?.silent) setListLoading(false);
    }
  };

  useEffect(() => {
    void loadAccounts();
    void loadCredentials();
  }, []);

  useEffect(() => {
    setVisibleCount(40);
  }, [query]);

  const filteredAccounts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return accounts;
    return accounts.filter((account) => {
      const fields = [
        account.phone,
        account.display_name,
        account.admin_display_name,
        account.username,
        account.username ? `@${account.username}` : null,
        account.user_id ? String(account.user_id) : null,
        account.status,
        account.api_credential_name,
      ];
      return fields.some((field) => field?.toLowerCase().includes(needle));
    });
  }, [accounts, query]);

  const visibleAccounts = useMemo(
    () => filteredAccounts.slice(0, visibleCount),
    [filteredAccounts, visibleCount],
  );

  const resetLoginForm = () => {
    setForm(emptyLoginForm);
    setLoginId(null);
    setCodePhone(null);
    setRequiresPassword(false);
  };

  const startLogin = async (e: FormEvent) => {
    e.preventDefault();
    setFormBusy(true);
    setError(null);
    try {
      const resp = await apiFetch<SessionLoginStartResponse>("/telegram/session-login/start", {
        method: "POST",
        body: JSON.stringify({
          phone: form.phone,
          display_name: form.display_name,
          api_credential_id: form.api_credential_id || null,
        }),
      });
      setLoginId(resp.login_id);
      setCodePhone(resp.phone);
      setRequiresPassword(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送验证码失败");
    } finally {
      setFormBusy(false);
    }
  };

  const verifyLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!loginId) return;
    setFormBusy(true);
    setError(null);
    try {
      const resp = await apiFetch<SessionLoginVerifyResponse>("/telegram/session-login/verify", {
        method: "POST",
        body: JSON.stringify({
          login_id: loginId,
          code: form.code || null,
          password: form.password || null,
          display_name: form.display_name,
          auto_connect: form.auto_connect,
        }),
      });
      if (resp.requires_password) {
        setRequiresPassword(true);
        return;
      }
      setShowAddModal(false);
      resetLoginForm();
      setQuery("");
      setVisibleCount(40);
      if (resp.account_id) {
        const optimistic: TelegramAccount = {
          id: resp.account_id,
          phone: resp.phone || form.phone,
          status: resp.status || "active",
          is_active: true,
          display_name: form.display_name || null,
          username: null,
          user_id: null,
          is_connected: Boolean(form.auto_connect),
          is_bot: false,
          last_connected_at: null,
          last_error_at: null,
          error_message: null,
          reply_mode: "ai",
        };
        setAccounts((prev) => [optimistic, ...prev.filter((item) => item.id !== resp.account_id)]);
      }
      void loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "验证登录失败");
    } finally {
      setFormBusy(false);
    }
  };

  const connectAccount = async (accountId: string) => {
    setBusyId(accountId);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/connect`, { method: "POST" });
      await loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接账号失败");
    } finally {
      setBusyId(null);
    }
  };

  const disconnectAccount = async (accountId: string) => {
    setBusyId(accountId);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/disconnect`, { method: "POST" });
      await loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开账号失败");
    } finally {
      setBusyId(null);
    }
  };

  const deleteAccount = async (account: TelegramAccount) => {
    const label = account.display_name || account.username || account.phone;
    if (!confirm(`确定要删除 Telegram 账号「${label}」吗？删除后需要重新发送验证码才能接入。`)) return;
    setBusyId(account.id);
    setError(null);
    setAccounts((prev) => prev.filter((item) => item.id !== account.id));
    try {
      const resp = await apiFetch<{ status?: string; executed?: boolean; message?: string }>(
        `/telegram/accounts/${account.id}`,
        { method: "DELETE" },
      );
      if (resp.status !== "deleted") {
        throw new Error(resp.message || "删除未完成，请刷新后重试");
      }
      void loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除账号失败");
      await loadAccounts();
    } finally {
      setBusyId(null);
    }
  };

  const updateAdminDisplayName = async (accountId: string, adminDisplayName: string) => {
    setBusyId(accountId);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/admin-display-name`, {
        method: "PATCH",
        body: JSON.stringify({ admin_display_name: adminDisplayName }),
      });
      setAccounts((prev) =>
        prev.map((item) =>
          item.id === accountId ? { ...item, admin_display_name: adminDisplayName } : item,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改显示名称失败");
    } finally {
      setBusyId(null);
    }
  };

  const updateReplyMode = async (accountId: string, replyMode: "ai" | "fixed") => {
    setBusyId(accountId);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/reply-mode`, {
        method: "PATCH",
        body: JSON.stringify({ reply_mode: replyMode }),
      });
      setAccounts((prev) =>
        prev.map((item) => (item.id === accountId ? { ...item, reply_mode: replyMode } : item)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改回复模式失败");
    } finally {
      setBusyId(null);
    }
  };

  const updateAppDownloadPlatform = async (accountId: string, platformKey: string) => {
    setBusyId(accountId);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/app-download-platform`, {
        method: "PATCH",
        body: JSON.stringify({ app_download_platform: platformKey }),
      });
      setAccounts((prev) =>
        prev.map((item) =>
          item.id === accountId ? { ...item, app_download_platform: platformKey } : item,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改下载平台失败");
    } finally {
      setBusyId(null);
    }
  };

  const createCredential = async (e: FormEvent) => {
    e.preventDefault();
    setFormBusy(true);
    setError(null);
    try {
      await apiFetch("/telegram/api-credentials", {
        method: "POST",
        body: JSON.stringify({
          sort_order: credentialForm.sort_order ? Number(credentialForm.sort_order) : null,
          name: credentialForm.name.trim(),
          api_id: Number(credentialForm.api_id),
          api_hash: credentialForm.api_hash.trim(),
          max_accounts: credentialForm.max_accounts ? Number(credentialForm.max_accounts) : null,
          note: credentialForm.note.trim() || null,
        }),
      });
      setCredentialForm(emptyCredentialForm);
      setShowCredentialForm(false);
      await loadCredentials();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建开发者应用失败");
    } finally {
      setFormBusy(false);
    }
  };

  const defaultCredential = credentials.find((item) => item.is_default) ?? credentials[0] ?? null;
  const rowBusy = (accountId: string) => busyId === accountId || bulkBusy;

  const connectAll = async () => {
    setBulkBusy(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/connect-all", { method: "POST" });
      await loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接所有账号失败");
    } finally {
      setBulkBusy(false);
    }
  };

  const disconnectAll = async () => {
    if (!confirm("确定要断开所有账号吗？")) return;
    setBulkBusy(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/disconnect-all", { method: "POST" });
      await loadAccounts({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开所有账号失败");
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700 bg-slate-800 px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <a href="/admin" className="text-slate-400 transition hover:text-white">
              返回会话总览
            </a>
            <div>
              <h1 className="text-xl font-bold">Telegram 账号管理</h1>
              <p className="text-sm text-slate-400">管理真人 Telegram 账号</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={connectAll} disabled={bulkBusy} className="rounded-lg bg-green-600 px-4 py-2 text-sm transition hover:bg-green-500 disabled:opacity-50">
              {bulkBusy ? "处理中..." : "连接所有账号"}
            </button>
            <button onClick={disconnectAll} disabled={bulkBusy} className="rounded-lg bg-red-600 px-4 py-2 text-sm transition hover:bg-red-500 disabled:opacity-50">
              断开所有账号
            </button>
            <button onClick={() => setShowAddModal(true)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm transition hover:bg-blue-500">
              添加账号
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="mx-6 mt-4 rounded-lg border border-red-700 bg-red-900/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <main className="p-6">
        <section className="mb-6 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-700 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold">开发者应用 (API ID)</h2>
              <p className="mt-1 text-sm text-slate-400">
                每个 TG 号绑定一个开发者应用；现有账号默认走「{defaultCredential?.name || "default"}」，不影响当前业务。
              </p>
            </div>
            <button
              onClick={() => setShowCredentialForm((value) => !value)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm transition hover:bg-indigo-500"
            >
              {showCredentialForm ? "取消添加" : "添加开发者应用"}
            </button>
          </div>

          {showCredentialForm && (
            <form onSubmit={createCredential} className="grid gap-4 border-b border-slate-700 px-6 py-4 md:grid-cols-2">
              <TextInput label="序列号（运营可见，如 1、2、3）" value={credentialForm.sort_order} onChange={(sort_order) => setCredentialForm({ ...credentialForm, sort_order })} placeholder="1" required />
              <TextInput label="名称" value={credentialForm.name} onChange={(name) => setCredentialForm({ ...credentialForm, name })} placeholder="#1 · 12602041988" required />
              <TextInput label="api_id" value={credentialForm.api_id} onChange={(api_id) => setCredentialForm({ ...credentialForm, api_id })} placeholder="12345678" required />
              <TextInput label="api_hash" value={credentialForm.api_hash} onChange={(api_hash) => setCredentialForm({ ...credentialForm, api_hash })} placeholder="从 my.telegram.org 获取" required />
              <TextInput label="账号上限（留空表示无上限）" value={credentialForm.max_accounts} onChange={(max_accounts) => setCredentialForm({ ...credentialForm, max_accounts })} placeholder="无上限可留空" />
              <div className="md:col-span-2">
                <TextInput label="备注" value={credentialForm.note} onChange={(note) => setCredentialForm({ ...credentialForm, note })} placeholder="可选" />
              </div>
              <div className="md:col-span-2">
                <button type="submit" disabled={formBusy} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm transition hover:bg-indigo-500 disabled:opacity-50">
                  {formBusy ? "保存中..." : "保存开发者应用"}
                </button>
              </div>
            </form>
          )}

          <div className="divide-y divide-slate-700">
            {credentials.length === 0 ? (
              <div className="p-6 text-sm text-slate-400">暂无开发者应用配置，系统将回退到环境变量中的默认 api_id。</div>
            ) : (
              credentials.map((credential) => (
                <div key={credential.id || credential.name} className="grid gap-2 px-6 py-4 text-sm md:grid-cols-5">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">序列号</div>
                    <div className="mt-1 text-lg font-semibold text-amber-300">{credential.serial_label}</div>
                  </div>
                  <div>
                    <div className="font-medium text-white">{credential.name}</div>
                    {credential.is_default && <span className="mt-1 inline-block rounded bg-blue-900/50 px-2 py-0.5 text-xs text-blue-200">默认</span>}
                    {credential.note && <div className="mt-1 text-xs text-slate-500">{credential.note}</div>}
                  </div>
                  <div className="text-slate-300">api_id: {credential.api_id}</div>
                  <div className="text-slate-300">hash: {credential.api_hash_masked}</div>
                  <div className="text-slate-300">
                    已绑定 {credential.account_count} 个账号 / 上限 {credential.max_accounts ?? "无"}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-700 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold">账号列表</h2>
              <div className="mt-1 text-sm text-slate-400">
                总计: <span className="font-semibold text-white">{accounts.length}</span> | 已连接:{" "}
                <span className="font-semibold text-green-400">{accounts.filter((a) => a.is_connected).length}</span>
                {listLoading ? <span className="ml-2 text-slate-500">刷新中...</span> : null}
              </div>
            </div>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索手机号、用户名、显示名称、TG ID"
              className="w-full max-w-sm rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500"
            />
          </div>

          {filteredAccounts.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <p>
                {listLoading
                  ? "正在加载账号..."
                  : accounts.length === 0
                    ? "暂无 Telegram 账号"
                    : "没有匹配的 Telegram 账号"}
              </p>
              <button onClick={() => setShowAddModal(true)} className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm transition hover:bg-blue-500">
                添加账号
              </button>
            </div>
          ) : (
            <div className="divide-y divide-slate-700">
              {visibleAccounts.map((account) => (
                <div key={account.id} className="p-4 transition hover:bg-slate-700/50">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className={`rounded px-2 py-1 text-xs font-semibold ${account.is_connected ? "bg-green-600 text-green-100" : "bg-slate-600 text-slate-300"}`}>
                          {account.is_connected ? "已连接" : "未连接"}
                        </span>
                        <span className="rounded bg-slate-700 px-2 py-1 text-xs text-slate-200">{account.status}</span>
                        {account.is_bot && <span className="rounded bg-purple-600 px-2 py-1 text-xs font-semibold text-purple-100">Bot</span>}
                        {!account.is_active && <span className="rounded bg-red-600 px-2 py-1 text-xs font-semibold text-red-100">已禁用</span>}
                      </div>
                      <div className="grid gap-1 text-sm md:grid-cols-2">
                        <Info label="手机号" value={account.phone} />
                        <Info label="TG 资料名" value={account.display_name} />
                        <Info label="用户名" value={account.username ? `@${account.username}` : null} />
                        <Info label="用户ID" value={account.user_id ? String(account.user_id) : null} />
                        <Info label="开发者应用" value={account.api_credential_name || "default"} />
                        <Info label="最后连接" value={formatDate(account.last_connected_at)} />
                        <Info label="最近错误" value={account.error_message} danger />
                        <div className="md:col-span-2">
                          <label className="flex max-w-xs flex-col gap-1 text-sm text-slate-400">
                            显示名称
                            <input
                              type="text"
                              defaultValue={account.admin_display_name || ""}
                              placeholder="例如：86号机"
                              disabled={rowBusy(account.id)}
                              onBlur={(event) => {
                                const nextValue = event.target.value.trim();
                                const currentValue = (account.admin_display_name || "").trim();
                                if (nextValue !== currentValue) {
                                  void updateAdminDisplayName(account.id, nextValue);
                                }
                              }}
                              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white outline-none transition focus:border-blue-500 disabled:opacity-50"
                            />
                          </label>
                          <p className="mt-1 text-xs text-slate-500">
                            这是运营备注名，会显示在数据页的「显示名称」列。
                          </p>
                        </div>
                        <div className="md:col-span-1">
                          <label className="flex max-w-xs flex-col gap-1 text-sm text-slate-400">
                            回复模式
                            <select
                              value={account.reply_mode || "ai"}
                              onChange={(e) => updateReplyMode(account.id, e.target.value === "fixed" ? "fixed" : "ai")}
                              disabled={rowBusy(account.id)}
                              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white outline-none transition focus:border-blue-500 disabled:opacity-50"
                            >
                              <option value="ai">AI系统</option>
                              <option value="fixed">固定回复</option>
                            </select>
                          </label>
                          <p className="mt-1 text-xs text-slate-500">
                            AI系统走现有话术和 AI 链路；固定回复只走固定回复规则。
                          </p>
                        </div>
                        <div className="md:col-span-1">
                          <label className="flex max-w-xs flex-col gap-1 text-sm text-slate-400">
                            下载平台
                            <select
                              value={account.app_download_platform || "default"}
                              onChange={(e) => updateAppDownloadPlatform(account.id, e.target.value)}
                              disabled={rowBusy(account.id)}
                              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white outline-none transition focus:border-blue-500 disabled:opacity-50"
                            >
                              {APP_DOWNLOAD_PLATFORM_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <p className="mt-1 text-xs text-slate-500">
                            该号发出的下载链接走对应平台；跟随A设为默认时用 A 平台链接。
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col gap-2">
                      {account.is_connected ? (
                        <button onClick={() => disconnectAccount(account.id)} disabled={rowBusy(account.id)} className="rounded bg-red-600 px-3 py-1.5 text-sm transition hover:bg-red-500 disabled:opacity-50">
                          {busyId === account.id ? "处理中..." : "断开"}
                        </button>
                      ) : (
                        <button onClick={() => connectAccount(account.id)} disabled={rowBusy(account.id)} className="rounded bg-green-600 px-3 py-1.5 text-sm transition hover:bg-green-500 disabled:opacity-50">
                          {busyId === account.id ? "处理中..." : "连接"}
                        </button>
                      )}
                      <button onClick={() => deleteAccount(account)} disabled={rowBusy(account.id)} className="rounded border border-red-500/70 px-3 py-1.5 text-sm text-red-300 transition hover:bg-red-500/10 disabled:opacity-50">
                        {busyId === account.id ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {visibleCount < filteredAccounts.length && (
                <div className="p-4 text-center">
                  <button
                    type="button"
                    onClick={() => setVisibleCount((count) => count + 40)}
                    className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 transition hover:bg-slate-700"
                  >
                    加载更多（还有 {filteredAccounts.length - visibleCount} 个）
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      </main>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-800 p-6">
            <h3 className="mb-4 text-lg font-semibold">添加 Telegram 账号</h3>
            <form onSubmit={loginId ? verifyLogin : startLogin} className="space-y-4">
              <TextInput label="手机号" value={form.phone} onChange={(phone) => setForm({ ...form, phone })} placeholder="+1234567890" disabled={!!loginId} required />
              <TextInput label="显示名称" value={form.display_name} onChange={(display_name) => setForm({ ...form, display_name })} placeholder="可选" />
              <label className="flex flex-col gap-1 text-sm text-slate-400">
                开发者应用
                <select
                  value={form.api_credential_id}
                  onChange={(e) => setForm({ ...form, api_credential_id: e.target.value })}
                  disabled={!!loginId}
                  className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-white outline-none focus:border-blue-500 disabled:opacity-60"
                >
                  <option value="">
                    默认 ({defaultCredential?.name || "default"})
                  </option>
                  {credentials
                    .filter((item) => item.id && item.is_active)
                    .map((item) => (
                      <option key={item.id!} value={item.id!}>
                        {item.serial_label} · {item.name} ({item.account_count}/上限{item.max_accounts ?? "无"})
                      </option>
                    ))}
                </select>
              </label>
              <p className="text-xs text-slate-500">
                新号登录时选定开发者应用；Session 创建后不可随意更换 api_id。
              </p>
              {loginId && <div className="rounded-lg border border-blue-800 bg-blue-950/30 p-3 text-sm text-blue-200">验证码已发送到 {codePhone}</div>}
              {loginId && !requiresPassword && (
                <TextInput label="验证码" value={form.code} onChange={(code) => setForm({ ...form, code })} placeholder="Telegram 验证码" required />
              )}
              {requiresPassword && (
                <TextInput label="2FA 密码" type="password" value={form.password} onChange={(password) => setForm({ ...form, password })} placeholder="Telegram 两步验证密码" required />
              )}
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={form.auto_connect} onChange={(e) => setForm({ ...form, auto_connect: e.target.checked })} className="h-4 w-4 rounded border-slate-600 bg-slate-700 text-blue-600 focus:ring-blue-500" />
                添加后自动连接
              </label>
              <div className="flex gap-2 pt-4">
                <button type="button" onClick={() => { setShowAddModal(false); resetLoginForm(); }} className="flex-1 rounded-lg bg-slate-600 px-4 py-2 text-sm transition hover:bg-slate-500">
                  取消
                </button>
                <button type="submit" disabled={formBusy} className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm transition hover:bg-blue-500 disabled:opacity-50">
                  {formBusy ? "处理中..." : loginId ? "验证并添加" : "发送验证码"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Info({ label, value, danger = false }: { label: string; value: string | null; danger?: boolean }) {
  if (!value) return null;
  return (
    <div>
      <span className="text-slate-400">{label}: </span>
      <span className={danger ? "text-red-400" : "text-slate-200"}>{value}</span>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  disabled = false,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm text-slate-400">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-white placeholder-slate-400 outline-none focus:border-blue-500 disabled:opacity-60"
      />
    </div>
  );
}

function formatDate(value: string | null): string | null {
  if (!value) return null;
  return new Date(value).toLocaleString("zh-CN");
}
