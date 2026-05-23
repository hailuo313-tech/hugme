"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型定义 ─────────────────────────────────────────────────────

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
}

interface SessionLoginVerifyResponse {
  account_id: string | null;
  status: string;
  requires_password: boolean;
  username: string | null;
  display_name: string | null;
}

// ── Telegram账号管理组件 ─────────────────────────────────────────

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
  const [showAddModal, setShowAddModal] = useState(false);
  const [loginForm, setLoginForm] = useState({
    phone: "",
    display_name: "",
    code: "",
    password: "",
    auto_connect: true,
  });
  const [loginId, setLoginId] = useState<string | null>(null);
  const [requiresPassword, setRequiresPassword] = useState(false);
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);

  // 加载账号列表
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

  const resetLoginForm = () => {
    setLoginForm({
      phone: "",
      display_name: "",
      code: "",
      password: "",
      auto_connect: true,
    });
    setLoginId(null);
    setRequiresPassword(false);
    setCodeSentTo(null);
  };

  // 发送验证码
  const handleStartSessionLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<SessionLoginStartResponse>("/telegram/session-login/start", {
        method: "POST",
        body: JSON.stringify({
          phone: loginForm.phone,
          display_name: loginForm.display_name,
        }),
      });
      setLoginId(resp.login_id);
      setCodeSentTo(resp.phone);
      setRequiresPassword(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送验证码失败");
    } finally {
      setLoading(false);
    }
  };

  // 验证并添加账号
  const handleVerifySessionLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loginId) return;

    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<SessionLoginVerifyResponse>("/telegram/session-login/verify", {
        method: "POST",
        body: JSON.stringify({
          login_id: loginId,
          code: loginForm.code || null,
          password: loginForm.password || null,
          display_name: loginForm.display_name,
          auto_connect: loginForm.auto_connect,
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

  // 连接账号
  const handleConnectAccount = async (accountId: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/connect`, {
        method: "POST",
      });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接账号失败");
    } finally {
      setLoading(false);
    }
  };

  // 断开账号
  const handleDisconnectAccount = async (accountId: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${accountId}/disconnect`, {
        method: "POST",
      });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开账号失败");
    } finally {
      setLoading(false);
    }
  };

  // 删除账号
  const handleDeleteAccount = async (account: TelegramAccount) => {
    const label = account.display_name || account.username || account.phone;
    if (!confirm(`确定要删除 Telegram 账号「${label}」吗？删除后需要重新发送验证码才能接入。`)) return;

    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/telegram/accounts/${account.id}`, {
        method: "DELETE",
      });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除账号失败");
    } finally {
      setLoading(false);
    }
  };

  // 连接所有账号
  const handleConnectAll = async () => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/connect-all", {
        method: "POST",
      });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接所有账号失败");
    } finally {
      setLoading(false);
    }
  };

  // 断开所有账号
  const handleDisconnectAll = async () => {
    if (!confirm("确定要断开所有账号吗？")) return;
    
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/telegram/accounts/disconnect-all", {
        method: "POST",
      });
      await loadAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "断开所有账号失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* 顶部导航栏 */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a
              href="/admin"
              className="text-slate-400 hover:text-white transition"
            >
              ← 返回会话总览
            </a>
            <div>
              <h1 className="text-xl font-bold">Telegram 账号管理</h1>
              <p className="text-sm text-slate-400">
                管理真人 Telegram 账号
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={handleConnectAll}
              disabled={loading}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-lg text-sm transition"
            >
              连接所有账号
            </button>
            <button
              onClick={handleDisconnectAll}
              disabled={loading}
              className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg text-sm transition"
            >
              断开所有账号
            </button>
            <button
              onClick={() => setShowAddModal(true)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition"
            >
              添加账号
            </button>
          </div>
        </div>
      </header>

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mt-4 px-4 py-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* 主内容区 */}
      <main className="p-6">
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-lg font-semibold">账号列表</h2>
            <div className="text-sm text-slate-400">
              总计: <span className="text-white font-semibold">{accounts.length}</span> | 
              已连接: <span className="text-green-400 font-semibold">{accounts.filter(a => a.is_connected).length}</span>
            </div>
          </div>
          
          {accounts.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <div className="text-4xl mb-4">📱</div>
              <p>暂无 Telegram 账号</p>
              <button
                onClick={() => setShowAddModal(true)}
                className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition"
              >
                添加第一个账号
              </button>
            </div>
          ) : (
            <div className="divide-y divide-slate-700">
              {accounts.map((account) => (
                <div key={account.id} className="p-4 hover:bg-slate-700/50 transition">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      {/* 状态标签 */}
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className={`px-2 py-1 rounded text-xs font-semibold ${
                            account.is_connected
                              ? "bg-green-600 text-green-100"
                              : "bg-slate-600 text-slate-300"
                          }`}
                        >
                          {account.is_connected ? "已连接" : "未连接"}
                        </span>
                        {account.is_bot && (
                          <span className="px-2 py-1 rounded text-xs font-semibold bg-purple-600 text-purple-100">
                            Bot
                          </span>
                        )}
                        {!account.is_active && (
                          <span className="px-2 py-1 rounded text-xs font-semibold bg-red-600 text-red-100">
                            已禁用
                          </span>
                        )}
                      </div>
                      
                      {/* 账号信息 */}
                      <div className="space-y-1">
                        <div className="text-sm">
                          <span className="text-slate-400">手机号:</span>{" "}
                          <span className="text-slate-200">{account.phone}</span>
                        </div>
                        {account.display_name && (
                          <div className="text-sm">
                            <span className="text-slate-400">显示名称:</span>{" "}
                            <span className="text-slate-200">{account.display_name}</span>
                          </div>
                        )}
                        {account.username && (
                          <div className="text-sm">
                            <span className="text-slate-400">用户名:</span>{" "}
                            <span className="text-slate-200">@{account.username}</span>
                          </div>
                        )}
                        {account.user_id && (
                          <div className="text-sm">
                            <span className="text-slate-400">用户ID:</span>{" "}
                            <span className="text-slate-200">{account.user_id}</span>
                          </div>
                        )}
                        {account.last_connected_at && (
                          <div className="text-sm">
                            <span className="text-slate-400">最后连接:</span>{" "}
                            <span className="text-slate-200">
                              {new Date(account.last_connected_at).toLocaleString("zh-CN")}
                            </span>
                          </div>
                        )}
                        {account.error_message && (
                          <div className="text-sm text-red-400">
                            <span className="text-slate-400">错误:</span>{" "}
                            <span>{account.error_message}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    
                    {/* 操作按钮 */}
                    <div className="flex flex-col gap-2">
                      {account.is_connected ? (
                        <button
                          onClick={() => handleDisconnectAccount(account.id)}
                          disabled={loading}
                          className="px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded text-sm transition"
                        >
                          断开
                        </button>
                      ) : (
                        <button
                          onClick={() => handleConnectAccount(account.id)}
                          disabled={loading}
                          className="px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-sm transition"
                        >
                          连接
                        </button>
                      )}
                      <button
                        onClick={() => handleDeleteAccount(account)}
                        disabled={loading}
                        className="px-3 py-1.5 border border-red-500/70 text-red-300 hover:bg-red-500/10 disabled:opacity-50 rounded text-sm transition"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* 添加账号模态框 */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">添加 Telegram 账号</h3>
            <form onSubmit={loginId ? handleVerifySessionLogin : handleStartSessionLogin} className="space-y-4">
              <div>
                <label className="block text-sm text-slate-400 mb-1">手机号</label>
                <input
                  type="text"
                  value={loginForm.phone}
                  onChange={(e) => setLoginForm({ ...loginForm, phone: e.target.value })}
                  placeholder="+1234567890"
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                  disabled={!!loginId}
                  required
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">显示名称</label>
                <input
                  type="text"
                  value={loginForm.display_name}
                  onChange={(e) => setLoginForm({ ...loginForm, display_name: e.target.value })}
                  placeholder="可选"
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                />
              </div>

              {loginId && (
                <div className="rounded-lg border border-blue-800 bg-blue-950/30 p-3 text-sm text-blue-200">
                  验证码已发送到 {codeSentTo}
                </div>
              )}

              {loginId && !requiresPassword && (
                <div>
                  <label className="block text-sm text-slate-400 mb-1">验证码</label>
                  <input
                    type="text"
                    value={loginForm.code}
                    onChange={(e) => setLoginForm({ ...loginForm, code: e.target.value })}
                    placeholder="Telegram 验证码"
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                    required
                  />
                </div>
              )}

              {requiresPassword && (
                <div>
                  <label className="block text-sm text-slate-400 mb-1">2FA 密码</label>
                  <input
                    type="password"
                    value={loginForm.password}
                    onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                    placeholder="Telegram 两步验证密码"
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                    required
                  />
                </div>
              )}

              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={loginForm.auto_connect}
                  onChange={(e) => setLoginForm({ ...loginForm, auto_connect: e.target.checked })}
                  className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-blue-600 focus:ring-blue-500"
                />
                添加后自动连接
              </label>

              <div className="flex gap-2 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddModal(false);
                    resetLoginForm();
                  }}
                  className="flex-1 px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-sm transition"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm transition"
                >
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
