"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { saveAuth, isLoggedIn, getOperator, clearAuth, API_BASE } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isLoggedIn()) return;
    if (!getOperator()) {
      clearAuth();
      return;
    }
    router.replace("/");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(data.detail || "登录失败");
      }
      const data = await res.json() as {
        token: string; operator_id: string;
        username: string; display_name: string | null; role: string;
      };
      saveAuth(data.token, {
        operator_id: data.operator_id,
        username: data.username,
        display_name: data.display_name,
        role: data.role,
      });
      router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "用户名或密码错误");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-800 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-wide">ERIS</h1>
          <p className="text-slate-400 text-sm mt-1">运营后台</p>
        </div>

        {/* Card */}
        <div className="bg-slate-800 rounded-2xl shadow-xl p-8 border border-slate-700">
          <h2 className="text-lg font-semibold text-white mb-6">登录</h2>

          {error && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-red-900/40 border border-red-700 text-red-300 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-slate-300 mb-1.5">用户名</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                className="w-full px-4 py-2.5 rounded-lg bg-slate-700 border border-slate-600 text-white placeholder-slate-400 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition"
                placeholder="admin"
              />
            </div>

            <div>
              <label className="block text-sm text-slate-300 mb-1.5">密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full px-4 py-2.5 rounded-lg bg-slate-700 border border-slate-600 text-white placeholder-slate-400 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition"
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium transition"
            >
              {loading ? "登录中…" : "登录"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
