"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  apiFetch,
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

/**
 * Mock fallback：当 GET /admin/users/{id}/profile 尚未实装时使用。
 * TODO(D4-3): Cursor 补完后端接口后，删除此 fallback 并改用真数据。
 */
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

// ── 后端响应类型（与 user_profiles 表对齐） ───────────────────────

interface UserProfile {
  user_id: string;
  nickname?: string | null;
  initiation_score: number | null;
  emotion_score: number | null;
  retention_score: number | null;
  dependency_score: number | null;
  loneliness_score: number | null;
  score_stage: string | null;
  score_updated_at: string | null;
  relationship_stage: string | null;
  risk_score: number | null;
  vip_level: number | null;
}

/** 将后端 user_profiles 字段映射为前端 ScoreMetric 卡片 */
function profileToScores(p: UserProfile): ScoreMetric[] {
  return [
    {
      key: "vulnerability",
      label: "Vulnerability",
      value: p.emotion_score ?? 0,
      description:
        "脆弱度：衡量用户当前情绪脆弱程度。数值越高表示越需要关注和温柔回应。（对应 emotion_score）",
    },
    {
      key: "initiation",
      label: "Initiation",
      value: p.initiation_score ?? 0,
      description:
        "主动性：衡量用户主动发起对话的频率。数值越高表示用户越主动寻求陪伴。",
    },
    {
      key: "dependency",
      label: "Dependency",
      value: p.dependency_score ?? 0,
      description:
        "依赖度：衡量用户对 AI 陪伴的依赖程度。数值过高需关注是否形成不健康依赖。",
    },
    {
      key: "loneliness",
      label: "Loneliness",
      value: p.loneliness_score ?? 0,
      description:
        "孤独感：综合评估用户的孤独程度。数值越高表示越孤独，需要更多主动关怀。",
    },
  ];
}

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

function fmtTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
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
        {metric.value.toFixed(1)}
      </div>

      {/* 进度条 */}
      <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(metric.value)}`}
          style={{ width: `${Math.min(metric.value, 100)}%` }}
        />
      </div>
    </div>
  );
}

// ── ScoreCard 骨架屏 ─────────────────────────────────────────────

function ScoreCardSkeleton() {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 animate-pulse">
      <div className="flex items-center justify-between mb-3">
        <div className="h-3 bg-slate-700 rounded w-20" />
        <div className="w-5 h-5 bg-slate-700 rounded-full" />
      </div>
      <div className="h-8 bg-slate-700 rounded w-16 mb-3" />
      <div className="h-2 bg-slate-900 rounded-full" />
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

  const [scores, setScores] = useState<ScoreMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingMock, setUsingMock] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    setOperator(getOperator());
  }, [router]);

  const userId = params.id;

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUsingMock(false);
    try {
      /**
       * 尝试 GET /admin/users/{id}/profile（Cursor 补接口后自动生效）。
       * 接口不存在时（404）回落到 mock 数据。
       */
      const data = await apiFetch<UserProfile>(
        `/admin/users/${encodeURIComponent(userId)}/profile`
      );
      setScores(profileToScores(data));
      setUpdatedAt(data.score_updated_at ?? null);
    } catch {
      // 后端接口尚未实装 → 使用 mock fallback
      setScores(MOCK_SCORES);
      setUsingMock(true);
      setUpdatedAt(null);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    if (operator) loadProfile();
  }, [operator, loadProfile]);

  if (!operator) return null;

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

        {/* Loading 骨架屏 */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            {[1, 2, 3, 4].map((i) => (
              <ScoreCardSkeleton key={i} />
            ))}
          </div>
        )}

        {/* 错误状态 */}
        {!loading && error && (
          <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
            <p className="mb-2">加载失败：{error}</p>
            <button
              onClick={loadProfile}
              className="text-xs text-rose-300 hover:text-white underline transition"
            >
              重试
            </button>
          </div>
        )}

        {/* 空状态：加载成功但分数全为 0 / 无数据 */}
        {!loading && !error && scores.length === 0 && (
          <div className="bg-slate-800 rounded-xl border border-slate-700 border-dashed p-12 text-center mb-4">
            <p className="text-slate-500 text-sm mb-2">
              该用户暂无画像数据
            </p>
            <p className="text-slate-600 text-xs">
              用户与 AI 交互后，系统将自动生成孤独度评分
            </p>
          </div>
        )}

        {/* 4 维分数卡片 */}
        {!loading && !error && scores.length > 0 && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              {scores.map((m) => (
                <ScoreCard key={m.key} metric={m} />
              ))}
            </div>

            {/* 最后更新提示 */}
            <p className="text-xs text-slate-600 mb-8">
              {usingMock
                ? "数据来源：Mock（后端接口 GET /admin/users/{id}/profile 尚未实装）"
                : `最后更新：${fmtTime(updatedAt)}`}
            </p>
          </>
        )}

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
