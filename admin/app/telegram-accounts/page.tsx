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
  username: string | null;
  user_id: number | null;
  is_connected: boolean;
  is_bot: boolean;
  last_connected_at: string | null;
  last_error_at: string | null;
  error_message: string | null;
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

const emptyLoginForm = {
  phone: "",
  display_name: "",
  code: "",
  password: "",
  auto_connect: true,
};

export default function TelegramAccountsPage() {
  return (
    <AuthGate>
      {() => <TelegramAccountsManager />}
    </AuthGate>
  );
}

function TelegramAccountsManager() {
  const [accounts, setAccounts] = useState<TelegramAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState(emptyLoginForm);
  const [loginId, setLoginId] = useState<string | null>(null);
  const [codePhone, setCodePhone] = useState<string | null>(null);
  const [requiresPassword, setRequiresPassword] = useState(false);

  const loadAccounts = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<TelegramAccountsResponse>("/telegram/accounts");
      setAccounts(resp.accounts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载账号列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAccounts();
  }, []);

  const filteredAccounts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return accounts;
    return accounts.filter((account) => {
      const fields = [
        account.phone,
        account.display_name,
        account.username,
        account.username ? `@${account.username}` : null,
        account.user_id ? String(account.user_id) : null,
        account.status,
      ];
      return fields.some((field) => field?.toLowerCase().includes(needle));
    });
  }, [accounts, query]);

  const resetLoginForm = () => {
    setForm(emptyLoginForm);
    setLoginId(null);
    setCodePhone(null);
    setRequiresPassword(false);
  };

  const startLogin = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<SessionLoginStartResponse>("/telegram/session-login/start", {
        method: "POST",
        body: JSON.stringify({
          phone: form.phone,
          display_name: form.display_name,
        }),
      });
      setLoginId(resp.login_id);
      setCodePhone(resp.phone);
      setRequiresPassword(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送验证码失败");
    } finally {
      setLoading(false);
    }
  };

  const verifyLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!loginId) return;
    setLoading(true);
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
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "验证登录失败");
    } finally {
      setLoading(false);
    }
  };

  const connectAccount = async (accountId: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/connect`, { method: "POST" });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接账号失败");
    } finally {
      setLoading(false);
    }
  };

  const disconnectAccount = async (accountId: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/disconnect`, { method: "POST" });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开账号失败");
    } finally {
      setLoading(false);
    }
  };

  const deleteAccount = async (account: TelegramAccount) => {
    const label = account.display_name || account.username || account.phone;
    if (!confirm(`确定要删除 Telegram 账号「${label}」吗？删除后需要重新发送验证码才能接入。`)) return;
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${account.id}`, { method: "DELETE" });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除账号失败");
    } finally {
      setLoading(false);
    }
  };

  const connectAll = async () => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/connect-all", { method: "POST" });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接所有账号失败");
    } finally {
      setLoading(false);
    }
  };

  const disconnectAll = async () => {
    if (!confirm("确定要断开所有账号吗？")) return;
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/disconnect-all", { method: "POST" });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开所有账号失败");
    } finally {
      setLoading(false);
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
            <button onClick={connectAll} disabled={loading} className="rounded-lg bg-green-600 px-4 py-2 text-sm transition hover:bg-green-500 disabled:opacity-50">
              连接所有账号
            </button>
            <button onClick={disconnectAll} disabled={loading} className="rounded-lg bg-red-600 px-4 py-2 text-sm transition hover:bg-red-500 disabled:opacity-50">
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
        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-700 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold">账号列表</h2>
              <div className="mt-1 text-sm text-slate-400">
                总计: <span className="font-semibold text-white">{accounts.length}</span> | 已连接:{" "}
                <span className="font-semibold text-green-400">{accounts.filter((a) => a.is_connected).length}</span>
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
              <p>{accounts.length === 0 ? "暂无 Telegram 账号" : "没有匹配的 Telegram 账号"}</p>
              <button onClick={() => setShowAddModal(true)} className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm transition hover:bg-blue-500">
                添加账号
              </button>
            </div>
          ) : (
            <div className="divide-y divide-slate-700">
              {filteredAccounts.map((account) => (
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
                        <Info label="显示名称" value={account.display_name} />
                        <Info label="用户名" value={account.username ? `@${account.username}` : null} />
                        <Info label="用户ID" value={account.user_id ? String(account.user_id) : null} />
                        <Info label="最后连接" value={formatDate(account.last_connected_at)} />
                        <Info label="最近错误" value={account.error_message} danger />
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col gap-2">
                      {account.is_connected ? (
                        <button onClick={() => disconnectAccount(account.id)} disabled={loading} className="rounded bg-red-600 px-3 py-1.5 text-sm transition hover:bg-red-500 disabled:opacity-50">
                          断开
                        </button>
                      ) : (
                        <button onClick={() => connectAccount(account.id)} disabled={loading} className="rounded bg-green-600 px-3 py-1.5 text-sm transition hover:bg-green-500 disabled:opacity-50">
                          连接
                        </button>
                      )}
                      <button onClick={() => deleteAccount(account)} disabled={loading} className="rounded border border-red-500/70 px-3 py-1.5 text-sm text-red-300 transition hover:bg-red-500/10 disabled:opacity-50">
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              ))}
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
                <button type="submit" disabled={loading} className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm transition hover:bg-blue-500 disabled:opacity-50">
                  {loading ? "处理中..." : loginId ? "验证并添加" : "发送验证码"}
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
