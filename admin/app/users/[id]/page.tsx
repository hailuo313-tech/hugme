"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  clearAuth,
  getOperator,
  isLoggedIn,
  Operator,
} from "@/lib/auth";

// ── 分数类型 & 假数据 ─────────────────────────────────────────────

interface ScoreMetric {
  key: string;
  label: string;
  value: number;
  description: string;
}

/** 假数据：D4-3 接入时替换为 fetch user_profiles 即可 */
const MOCK_SCORES: ScoreMetric[] = [
  {
    key: "vulnerability",
    label: "Vulnerability",
    value: 38,
    description:
      "脆弱度：衡量用户当前情绪脆弱程度。数值越高表示越需要关注和温柔回应。",
  },
  {
    key: "initiation",
    label: "Initiation",
    value: 52,
    description:
      "主动性：衡量用户主动发起对话的频率。数值越高表示用户越主动寻求陪伴。",
  },
  {
    key: "dependency",
    label: "Dependency",
    value: 67,
    description:
      "依赖度：衡量用户对 AI 陪伴的依赖程度。数值过高需关注是否形成不健康依赖。",
  },
  {
    key: "loneliness",
    label: "Loneliness",
    value: 81,
    description:
      "孤独感：综合评估用户的孤独程度。数值越高表示越孤独，需要更多主动关怀。",
  },
];

// ── 工具函数 ──────────────────────────────────────────────────────

function scoreBarColor(value: number): string {
  if (value > 70) return "bg-rose-500";
  if (value >= 40) return "bg-amber-500";
  return "bg-emerald-500";
}

function scoreTextColor(value: number): string {
  if (value > 70) return "text-rose-400";
  if (value >= 40) return "text-amber-400";
  return "text-emerald-400";
}

// ── ScoreCard 组件 ────────────────────────────────────────────────

function ScoreCard({ metric }: { metric: ScoreMetric }) {
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 relative">
      {/* 标题行 + 问号 */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-400 uppercase tracking-wider font-medium">
          {metric.label}
        </span>
        <div className="relative">
          <button
            onMouseEnter={() => setShowTip(true)}
            onMouseLeave={() => setShowTip(false)}
            onFocus={() => setShowTip(true)}
            onBlur={() => setShowTip(false)}
            className="w-5 h-5 rounded-full border border-slate-600 text-slate-500 hover:text-slate-300 hover:border-slate-400 text-xs flex items-center justify-center transition"
            aria-label={`${metric.label} 说明`}
          >
            ?
          </button>
          {showTip && (
            <div className="absolute right-0 top-7 z-10 w-56 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-xs text-slate-200 leading-relaxed shadow-lg">
              {metric.description}
            </div>
          )}
        </div>
      </div>

      {/* 数值 */}
      <div className={`text-3xl font-bold tabular-nums mb-3 ${scoreTextColor(metric.value)}`}>
        {metric.value}
      </div>

      {/* 进度条 */}
      <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(metric.value)}`}
          style={{ width: `${metric.value}%` }}
        />
      </div>
    </div>
  );
}

// ── Nav header ────────────────────────────────────────────────────

function NavHeader({
  operator,
  onLogout,
}: {
  operator: Operator;
  onLogout: () => void;
}) {
  return (
    <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xl font-bold text-violet-400">ERIS</span>
        <span className="text-slate-400 text-sm">运营后台</span>
        <nav className="flex items-center gap-1 ml-4">
          <a
            href="/admin"
            className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
          >
            会话
          </a>
          <a
            href="/admin/memories"
            className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
          >
            记忆
          </a>
          <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
            用户画像
          </span>
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm text-slate-300">
          {operator.display_name || operator.username}
          <span className="ml-2 text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
            {operator.role}
          </span>
        </span>
        <button
          onClick={onLogout}
          className="text-sm text-slate-400 hover:text-white transition"
        >
          退出
        </button>
      </div>
    </header>
  );
}

// ── 主页面 ────────────────────────────────────────────────────────

export default function UserScorePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [operator, setOperator] = useState<Operator | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    setOperator(getOperator());
  }, [router]);

  if (!operator) return null;

  const userId = params.id;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <NavHeader
        operator={operator}
        onLogout={() => {
          clearAuth();
          router.replace("/login");
        }}
      />

      <main className="p-8 max-w-7xl mx-auto">
        {/* 页面标题 */}
        <div className="mb-6">
          <h1 className="text-2xl font-semibold mb-1">用户画像</h1>
          <p className="text-slate-400 text-sm font-mono">
            user_id: {userId}
          </p>
        </div>

        {/* 4 维分数卡片 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          {MOCK_SCORES.map((m) => (
            <ScoreCard key={m.key} metric={m} />
          ))}
        </div>

        {/* 最后更新提示 */}
        <p className="text-xs text-slate-600 mb-8">
          最后更新：（暂未连接 D4-3 数据源）
        </p>

        {/* 快捷导航 */}
        <div className="flex gap-3">
          <a
            href="/admin"
            className="text-sm text-violet-400 hover:text-violet-300 transition"
          >
            &larr; 返回会话列表
          </a>
          <a
            href={`/admin/memories?user_id=${userId}`}
            className="text-sm text-violet-400 hover:text-violet-300 transition"
          >
            查看记忆 &rarr;
          </a>
        </div>
      </main>
    </div>
  );
}
