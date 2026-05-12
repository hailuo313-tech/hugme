"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getOperator, clearAuth, isLoggedIn, Operator } from "@/lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const [operator, setOperator] = useState<Operator | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    setOperator(getOperator());
  }, [router]);

  function handleLogout() {
    clearAuth();
    router.replace("/login");
  }

  if (!operator) return null;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-400 text-sm">运营后台</span>
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

      {/* Main */}
      <main className="p-8 max-w-6xl mx-auto">
        <h1 className="text-2xl font-semibold mb-2">Dashboard</h1>
        <p className="text-slate-400 text-sm mb-8">欢迎回来，{operator.display_name || operator.username}</p>

        {/* Stats placeholder */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {[
            { label: "活跃用户", value: "—" },
            { label: "今日消息", value: "—" },
            { label: "待接管会话", value: "—" },
            { label: "Onboarding 完成率", value: "—" },
          ].map((stat) => (
            <div
              key={stat.label}
              className="bg-slate-800 rounded-xl p-5 border border-slate-700"
            >
              <p className="text-slate-400 text-xs mb-1">{stat.label}</p>
              <p className="text-2xl font-bold text-white">{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Placeholder sections */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="font-medium text-slate-200 mb-3">最近会话</h2>
            <p className="text-slate-500 text-sm">D5-2 将在此展示会话列表</p>
          </div>
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="font-medium text-slate-200 mb-3">用户画像</h2>
            <p className="text-slate-500 text-sm">D5-2 将在此展示用户 loneliness_score</p>
          </div>
        </div>
      </main>
    </div>
  );
}
