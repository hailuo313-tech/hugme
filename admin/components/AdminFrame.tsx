"use client";

import { clearAuth, LOGIN_PATH, Operator } from "@/lib/auth";

const navItems = [
  { key: "home", label: "总后台", href: "/admin" },
  { key: "conversations", label: "会话流控", href: "/admin/conversations" },
  { key: "telegram", label: "TG账号", href: "/admin/telegram-accounts" },
  { key: "data", label: "数据总览", href: "/admin/data" },
  { key: "ai", label: "AI话术", href: "/admin/ai-ops" },
  { key: "broadcast", label: "视频通话", href: "/admin/video-broadcast" },
  { key: "characters", label: "角色", href: "/admin/characters" },
  { key: "approvals", label: "运营审批", href: "/admin/approvals" },
  { key: "delivery", label: "推送监控", href: "/admin/delivery" },
];

export default function AdminFrame({
  operator,
  active,
  title,
  subtitle,
  children,
}: {
  operator: Operator;
  active: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <header className="border-b border-slate-800 bg-slate-900 px-6 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <span className="text-xl font-bold text-violet-400">ERIS</span>
            <span className="hidden text-sm text-slate-400 sm:inline">运营后台</span>
            <nav className="ml-1 flex min-w-0 items-center gap-1 overflow-x-auto">
              {navItems.map((item) =>
                item.key === active ? (
                  <span
                    key={item.key}
                    className="whitespace-nowrap rounded-md bg-slate-700 px-3 py-1 text-sm font-medium text-violet-300"
                  >
                    {item.label}
                  </span>
                ) : (
                  <a
                    key={item.key}
                    href={item.href}
                    className="whitespace-nowrap rounded-md px-3 py-1 text-sm text-slate-400 transition hover:bg-slate-800 hover:text-white"
                  >
                    {item.label}
                  </a>
                )
              )}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <span className="hidden text-sm text-slate-300 sm:inline">
              {operator.display_name || operator.username}
              <span className="ml-2 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-500">
                {operator.role}
              </span>
            </span>
            <button
              onClick={handleLogout}
              className="text-sm text-slate-400 transition hover:text-white"
            >
              退出
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <div className="mb-6">
          <h1 className="mb-2 text-2xl font-semibold">{title}</h1>
          <p className="max-w-3xl text-sm leading-6 text-slate-400">{subtitle}</p>
        </div>
        {children}
      </main>
    </div>
  );
}
