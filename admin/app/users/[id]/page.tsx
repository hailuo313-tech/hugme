"use client";

/**
 * D8-DEV-01 / CUR-API-01 — 用户画像页  /admin/users/[id]
 *
 * 数据来源：GET /api/v1/admin/users/{id}（operator JWT，user + profile + memories）
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  apiFetch,
  clearAuth,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型 ──────────────────────────────────────────────────────────

interface UserRow {
  id: string;
  channel: string | null;
  external_id: string | null;
  nickname: string | null;
  language: string | null;
  timezone: string | null;
  status: string | null;
  age_verified: boolean | null;
  is_minor_suspected: boolean | null;
  risk_level: string | null;
  opt_out_marketing: boolean | null;
  notification_opt_in: boolean | null;
  gdpr_consent_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface ProfileRow {
  user_id: string;
  current_character_id: string | null;
  interests: unknown;
  chat_style: string | null;
  forbidden_topics: unknown;
  relationship_stage: string | null;
  risk_score: number | null;
  vip_level: number | null;
  initiation_score: number | null;
  emotion_score: number | null;
  retention_score: number | null;
  dependency_score: number | null;
  loneliness_score: number | null;
  score_stage: string | null;
  trigger_threshold: number | null;
  score_updated_at: string | null;
  notes: string | null;
  updated_at: string | null;
}

interface MemoryRow {
  id: string;
  memory_type: string | null;
  content: string | null;
  importance_score: number | null;
  created_at: string | null;
}

interface AdminUserResponse {
  user: UserRow | null;
  profile: ProfileRow | null;
  memories: MemoryRow[];
}

interface CharacterOption {
  id: string;
  name: string;
  age_feel?: string | null;
  region?: string | null;
  occupation?: string | null;
  status?: string | null;
}

interface CharacterUpdateResponse {
  user_id: string;
  character: CharacterOption;
  updated_conversations: number | null;
}

// ── 工具函数 ──────────────────────────────────────────────────────

function fmtTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function fmtBool(v: boolean | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v ? "是" : "否";
}

function fmtJson(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) {
    if (v.length === 0) return "—";
    return (v as string[]).join("、");
  }
  if (typeof v === "string") return v || "—";
  return JSON.stringify(v);
}

function riskColor(r: string | null): string {
  switch (r) {
    case "high":      return "text-rose-400";
    case "elevated":  return "text-amber-400";
    default:          return "text-slate-300";
  }
}

function stageColor(s: string | null): string {
  switch (s) {
    case "S0": return "bg-slate-800 text-slate-400 border-slate-700";
    case "S1": return "bg-sky-900/40 text-sky-300 border-sky-800";
    case "S2": return "bg-violet-900/40 text-violet-300 border-violet-800";
    case "S3": return "bg-amber-900/40 text-amber-300 border-amber-800";
    default:   return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

function scoreBar(val: number | null, max = 100): React.ReactNode {
  const pct = val != null ? Math.min(100, Math.max(0, (val / max) * 100)) : 0;
  const color =
    pct >= 70 ? "bg-rose-500" : pct >= 40 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tabular-nums text-xs text-slate-300 w-10 text-right">
        {val != null ? val.toFixed(1) : "—"}
      </span>
    </div>
  );
}

// ── 子组件 ────────────────────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-700 bg-slate-900/40">
        <h2 className="text-sm font-medium text-slate-300">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function MetaGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4">
      {children}
    </div>
  );
}

function MetaItem({
  label,
  value,
  mono,
  className,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="text-xs text-slate-500 mb-0.5">{label}</div>
      <div className={`text-sm text-slate-200 ${mono ? "font-mono" : ""}`}>
        {value ?? <span className="text-slate-600">—</span>}
      </div>
    </div>
  );
}

// ── 主页面（内部组件，由 AuthGate 传入 operator） ─────────────────

function UserProfileContent({ operator }: { operator: Operator }) {
  const params = useParams<{ id: string }>();
  const userId = params.id;

  const [data, setData] = useState<AdminUserResponse | null>(null);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [selectedCharacterId, setSelectedCharacterId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [characterSaving, setCharacterSaving] = useState(false);
  const [characterMessage, setCharacterMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    setError(null);

    Promise.all([
      apiFetch<AdminUserResponse>(`/admin/users/${encodeURIComponent(userId)}`),
      apiFetch<CharacterOption[]>("/characters"),
    ])
      .then(([d, chars]) => {
        setData(d);
        setCharacters(chars);
        setSelectedCharacterId(d.profile?.current_character_id || "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [userId]);

  async function handleCharacterSave() {
    if (!userId || !selectedCharacterId) return;
    setCharacterSaving(true);
    setCharacterMessage(null);
    setError(null);
    try {
      const res = await apiFetch<CharacterUpdateResponse>(
        `/characters/users/${encodeURIComponent(userId)}/character`,
        {
          method: "PATCH",
          body: JSON.stringify({ character_id: selectedCharacterId }),
        }
      );
      const refreshed = await apiFetch<AdminUserResponse>(
        `/admin/users/${encodeURIComponent(userId)}`
      );
      setData(refreshed);
      setSelectedCharacterId(refreshed.profile?.current_character_id || res.character.id);
      setCharacterMessage(
        `已切换为 ${res.character.name}，已同步 ${res.updated_conversations ?? 0} 个 AI_ACTIVE 会话。`
      );
    } catch (e) {
      setCharacterMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setCharacterSaving(false);
    }
  }

  function handleLogout() {
    clearAuth();
    window.location.href = LOGIN_PATH;
  }

  // ── 渲染 ────────────────────────────────────────────────────────

  const user = data?.user ?? null;
  const profile = data?.profile ?? null;
  const memories = data?.memories ?? [];
  const currentCharacter = characters.find(
    (c) => c.id === profile?.current_character_id
  );
  const selectedCharacter = characters.find((c) => c.id === selectedCharacterId);

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
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
            <span className="text-sm text-sky-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
              用户画像
            </span>
            <a
              href="/admin/telegram-accounts"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              TG账号
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          {operator && (
            <span className="text-sm text-slate-300">
              {operator.display_name || operator.username}
              <span className="ml-2 text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
                {operator.role}
              </span>
            </span>
          )}
          <button
            onClick={handleLogout}
            className="text-sm text-slate-400 hover:text-white transition"
          >
            退出
          </button>
        </div>
      </header>

      <main className="p-8 max-w-5xl mx-auto space-y-6">
        {/* 面包屑 + 返回 */}
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <a href="/admin" className="hover:text-slate-300 transition">
            会话列表
          </a>
          <span>/</span>
          <span className="text-slate-300">用户画像</span>
        </div>

        {/* 加载 / 错误 */}
        {loading && (
          <div className="text-slate-500 text-sm py-12 text-center">
            加载中…
          </div>
        )}
        {error && (
          <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
            加载失败：{error}
          </div>
        )}

        {/* 内容区 */}
        {!loading && !error && data && (
          <>
            {/* 标题行 */}
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-semibold">
                  {user?.nickname || (
                    <span className="text-slate-500 italic">未命名用户</span>
                  )}
                </h1>
                <p className="text-slate-500 text-xs font-mono mt-1">{userId}</p>
              </div>
              <div className="flex items-center gap-2 mt-1">
                {profile?.relationship_stage && (
                  <span
                    className={`inline-block px-2.5 py-1 text-xs rounded-full border ${stageColor(
                      profile.relationship_stage
                    )}`}
                  >
                    {profile.relationship_stage}
                  </span>
                )}
                {profile?.vip_level != null && profile.vip_level > 0 && (
                  <span className="inline-block px-2.5 py-1 text-xs rounded-full border bg-amber-900/40 text-amber-300 border-amber-800">
                    VIP {profile.vip_level}
                  </span>
                )}
              </div>
            </div>

            {/* 基本信息 */}
            <Section title="基本信息">
              <MetaGrid>
                <MetaItem label="昵称" value={user?.nickname} />
                <MetaItem label="渠道" value={user?.channel} />
                <MetaItem
                  label="外部 ID"
                  value={user?.external_id}
                  mono
                />
                <MetaItem label="语言" value={user?.language} />
                <MetaItem label="时区" value={user?.timezone} />
                <MetaItem label="状态" value={user?.status} />
                <MetaItem
                  label="风险等级"
                  value={
                    <span className={riskColor(user?.risk_level ?? null)}>
                      {user?.risk_level || "—"}
                    </span>
                  }
                />
                <MetaItem
                  label="年龄已验证"
                  value={fmtBool(user?.age_verified)}
                />
                <MetaItem
                  label="疑似未成年"
                  value={
                    <span
                      className={
                        user?.is_minor_suspected ? "text-rose-400" : ""
                      }
                    >
                      {fmtBool(user?.is_minor_suspected)}
                    </span>
                  }
                />
                <MetaItem
                  label="营销退出"
                  value={fmtBool(user?.opt_out_marketing)}
                />
                <MetaItem
                  label="通知订阅"
                  value={fmtBool(user?.notification_opt_in)}
                />
                <MetaItem
                  label="GDPR 同意"
                  value={fmtTime(user?.gdpr_consent_at)}
                />
                <MetaItem
                  label="注册时间"
                  value={fmtTime(user?.created_at)}
                />
                <MetaItem
                  label="最后更新"
                  value={fmtTime(user?.updated_at)}
                />
              </MetaGrid>
            </Section>

            {/* 角色切换 */}
            <Section title="角色切换">
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-4">
                  <MetaItem
                    label="当前角色"
                    value={
                      currentCharacter
                        ? `${currentCharacter.name}${currentCharacter.region ? ` · ${currentCharacter.region}` : ""}`
                        : profile?.current_character_id || "未绑定"
                    }
                    mono={!currentCharacter && !!profile?.current_character_id}
                  />
                  <MetaItem
                    label="切换后生效范围"
                    value="该账号画像 + 当前 AI_ACTIVE 会话"
                    className="sm:col-span-2"
                  />
                </div>
                <div className="flex flex-col sm:flex-row gap-3">
                  <select
                    value={selectedCharacterId}
                    onChange={(e) => {
                      setSelectedCharacterId(e.target.value);
                      setCharacterMessage(null);
                    }}
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  >
                    <option value="">选择角色</option>
                    {characters.map((char) => (
                      <option key={char.id} value={char.id}>
                        {char.name}
                        {char.region ? ` · ${char.region}` : ""}
                        {char.occupation ? ` · ${char.occupation}` : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={handleCharacterSave}
                    disabled={
                      characterSaving ||
                      !selectedCharacterId ||
                      selectedCharacterId === profile?.current_character_id
                    }
                    className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition"
                  >
                    {characterSaving ? "保存中…" : "保存切换"}
                  </button>
                </div>
                {selectedCharacter && (
                  <p className="text-xs text-slate-500">
                    将切换为：{selectedCharacter.name}
                    {selectedCharacter.age_feel ? ` · ${selectedCharacter.age_feel}` : ""}
                    {selectedCharacter.region ? ` · ${selectedCharacter.region}` : ""}
                    {selectedCharacter.occupation ? ` · ${selectedCharacter.occupation}` : ""}
                  </p>
                )}
                {characterMessage && (
                  <p
                    className={`text-sm ${
                      characterMessage.startsWith("已切换")
                        ? "text-emerald-400"
                        : "text-rose-300"
                    }`}
                  >
                    {characterMessage}
                  </p>
                )}
              </div>
            </Section>

            {/* 画像评分 */}
            <Section title="用户画像 · 评分">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    孤独感分
                  </div>
                  {scoreBar(profile?.loneliness_score ?? null)}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    风险分
                  </div>
                  {scoreBar(profile?.risk_score ?? null)}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    主动开话
                  </div>
                  {scoreBar(profile?.initiation_score ?? null)}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    情绪分
                  </div>
                  {scoreBar(profile?.emotion_score ?? null)}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    留存分
                  </div>
                  {scoreBar(profile?.retention_score ?? null)}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1.5">
                    依赖分
                  </div>
                  {scoreBar(profile?.dependency_score ?? null)}
                </div>
              </div>

              <div className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-4 pt-4 border-t border-slate-700/60">
                <MetaItem
                  label="评分阶段"
                  value={profile?.score_stage}
                />
                <MetaItem
                  label="触发阈值"
                  value={
                    profile?.trigger_threshold != null
                      ? profile.trigger_threshold.toFixed(1)
                      : null
                  }
                />
                <MetaItem
                  label="VIP 等级"
                  value={
                    profile?.vip_level != null
                      ? String(profile.vip_level)
                      : null
                  }
                />
                <MetaItem
                  label="评分更新"
                  value={fmtTime(profile?.score_updated_at)}
                />
              </div>
            </Section>

            {/* 偏好与画像 */}
            <Section title="偏好 · 聊天风格 · 关系阶段">
              <MetaGrid>
                <MetaItem
                  label="聊天风格"
                  value={profile?.chat_style}
                />
                <MetaItem
                  label="关系阶段"
                  value={
                    profile?.relationship_stage && (
                      <span
                        className={`inline-block px-2 py-0.5 text-xs rounded-full border ${stageColor(
                          profile.relationship_stage
                        )}`}
                      >
                        {profile.relationship_stage}
                      </span>
                    )
                  }
                />
                <MetaItem
                  label="兴趣爱好"
                  value={fmtJson(profile?.interests)}
                  className="col-span-2 sm:col-span-1"
                />
                <MetaItem
                  label="禁忌话题"
                  value={fmtJson(profile?.forbidden_topics)}
                  className="col-span-2 sm:col-span-1"
                />
                {profile?.notes && (
                  <MetaItem
                    label="备注"
                    value={profile.notes}
                    className="col-span-2 sm:col-span-3"
                  />
                )}
              </MetaGrid>
            </Section>

            {/* 最近记忆（前 5 条） */}
            <Section title={`记忆摘要（共 ${memories.length} 条，仅展示前 5）`}>
              {memories.length === 0 ? (
                <p className="text-slate-500 text-sm">暂无记忆记录</p>
              ) : (
                <>
                  <div className="space-y-2">
                    {memories.slice(0, 5).map((m) => (
                      <div
                        key={m.id}
                        className="flex items-start gap-3 text-sm py-2 border-b border-slate-700/50 last:border-0"
                      >
                        <span className="text-xs text-slate-500 whitespace-nowrap w-28 shrink-0 pt-0.5">
                          {fmtTime(m.created_at)}
                        </span>
                        <span className="text-xs px-1.5 py-0.5 rounded border bg-slate-900/60 border-slate-700 text-slate-400 whitespace-nowrap shrink-0">
                          {m.memory_type || "—"}
                        </span>
                        <span className="text-slate-200 leading-relaxed flex-1 break-words">
                          {m.content || "—"}
                        </span>
                        {m.importance_score != null && (
                          <span className="text-xs text-slate-500 tabular-nums shrink-0">
                            {m.importance_score.toFixed(1)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Section>
          </>
        )}

        {/* 用户不存在 */}
        {!loading && !error && !data?.user && (
          <div className="bg-slate-800 rounded-xl border border-slate-700 border-dashed p-12 text-center">
            <p className="text-slate-500 text-sm">找不到该用户（用户 ID：{userId}）</p>
            <a
              href="/admin"
              className="mt-3 inline-block text-sm text-violet-400 hover:text-violet-300 transition"
            >
              ← 返回会话列表
            </a>
          </div>
        )}
      </main>
    </div>
  );
}

// ── 页面入口（AuthGate 统一守卫） ──────────────────────────────────

export default function UserProfilePage() {
  return (
    <AuthGate>
      {(operator) => <UserProfileContent operator={operator} />}
    </AuthGate>
  );
}
