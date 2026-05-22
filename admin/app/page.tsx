"use client";

import { useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import { apiFetch, clearAuth, LOGIN_PATH, Operator } from "@/lib/auth";

interface ConversationListResponse {
  total: number;
}

interface ModuleItem {
  title: string;
  desc: string;
  href: string;
  metric?: string;
  status: "online" | "config";
}

const statusClass = {
  online: "border-emerald-500/30 text-emerald-300 bg-emerald-500/10",
  config: "border-sky-500/30 text-sky-300 bg-sky-500/10",
};

const statusText = {
  online: "在线",
  config: "配置",
};

export default function AdminHomePage() {
  return (
    <AuthGate>
      {(operator) => <AdminHome operator={operator} />}
    </AuthGate>
  );
}

function AdminHome({ operator }: { operator: Operator }) {
  const [conversationTotal, setConversationTotal] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    apiFetch<ConversationListResponse>("/admin/conversations?page=1&page_size=1")
      .then((data) => {
        if (mounted) {
          setConversationTotal(data.total);
          setLoadError(null);
        }
      })
      .catch((err: Error) => {
        if (mounted) setLoadError(err.message);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const modules = useMemo<ModuleItem[]>(
    () => [
      {
        title: "会话总览",
        desc: "筛选、检索、查看用户对话与精聊轨迹。",
        href: "/admin/conversations",
        metric: conversationTotal === null ? "加载中" : `${conversationTotal} 条`,
        status: "online",
      },
      {
        title: "TG 账号",
        desc: "添加真人 Telegram 账号、发送验证码、生成 StringSession 并查看连接状态。",
        href: "/admin/telegram-accounts",
        metric: "Telegram",
        status: "config",
      },
      {
        title: "H5 聊天",
        desc: "验证用户侧聊天、VIP 弹窗和支付跳转。",
        href: "/admin/h5/chat",
        metric: "H5",
        status: "online",
      },
    ],
    [conversationTotal]
  );

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <header className="border-b border-slate-800 bg-slate-900 px-6 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <span className="text-xl font-bold text-violet-400">ERIS</span>
            <span className="text-sm text-slate-400">运营后台</span>
            <nav className="ml-2 flex items-center gap-1">
              <span className="rounded-md bg-slate-700 px-3 py-1 text-sm font-medium text-violet-300">
                总后台
              </span>
              <a
                href="/admin/conversations"
                className="rounded-md px-3 py-1 text-sm text-slate-400 transition hover:bg-slate-800 hover:text-white"
              >
                会话
              </a>
              <a
                href="/admin/telegram-accounts"
                className="rounded-md px-3 py-1 text-sm text-slate-400 transition hover:bg-slate-800 hover:text-white"
              >
                TG 账号
              </a>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-300">
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

      <main className="mx-auto max-w-7xl px-8 py-8">
        <div className="mb-6">
          <h1 className="mb-2 text-2xl font-semibold">总后台</h1>
          <p className="text-sm text-slate-400">
            只保留当前项目正在使用的入口，旧版独立页面已下线。
          </p>
        </div>

        {loadError && (
          <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            部分统计加载失败：{loadError}
          </div>
        )}

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3">
          <SummaryBlock label="保留模块" value={`${modules.length} 个入口`} />
          <SummaryBlock label="会话数据" value={conversationTotal === null ? "加载中" : `${conversationTotal} 条`} />
          <SummaryBlock label="当前身份" value={operator.role} />
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {modules.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="group rounded-lg border border-slate-800 bg-slate-900 p-5 transition hover:border-violet-500/60 hover:bg-slate-900/80"
            >
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-white">{item.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{item.desc}</p>
                </div>
                <span className={`whitespace-nowrap rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}>
                  {statusText[item.status]}
                </span>
              </div>
              <div className="flex items-center justify-between border-t border-slate-800 pt-4">
                <span className="text-sm text-slate-500">{item.metric}</span>
                <span className="text-sm font-medium text-violet-300 transition group-hover:text-violet-200">
                  进入
                </span>
              </div>
            </a>
          ))}
        </section>
      </main>
    </div>
  );
}

function SummaryBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
