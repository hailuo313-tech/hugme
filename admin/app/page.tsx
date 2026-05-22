"use client";

import { useEffect, useMemo, useState } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { apiFetch, Operator } from "@/lib/auth";

interface ConversationListResponse {
  total: number;
}

interface ModuleItem {
  title: string;
  desc: string;
  href: string;
  metric?: string;
  status: "online" | "config" | "review";
}

const statusClass = {
  online: "border-emerald-500/30 text-emerald-300 bg-emerald-500/10",
  config: "border-sky-500/30 text-sky-300 bg-sky-500/10",
  review: "border-amber-500/30 text-amber-300 bg-amber-500/10",
};

const statusText = {
  online: "在线",
  config: "配置",
  review: "待验收",
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
        title: "会话流控",
        desc: "S/A 接管、B/C/D 自动投递、话术命中轨迹、用户画像入口。",
        href: "/admin/conversations",
        metric: conversationTotal === null ? "加载中" : `${conversationTotal} 条会话`,
        status: "online",
      },
      {
        title: "TG 真人账号",
        desc: "添加账号、发送验证码、生成 StringSession、连接状态与账号池运维。",
        href: "/admin/telegram-accounts",
        metric: "MTProto",
        status: "config",
      },
      {
        title: "数据总览",
        desc: "话术链接点击、国家/年龄分布、App 下载注册和付费归因。",
        href: "/admin/data",
        metric: "Attribution",
        status: "online",
      },
      {
        title: "AI 话术与人设",
        desc: "话术底料、意图 taxonomy、persona prompt、安全过滤、script_hit 审计。",
        href: "/admin/ai-ops",
        metric: "P3 链路",
        status: "review",
      },
      {
        title: "运营审批",
        desc: "H-01 到 H-11 的配置签字、SOP、灰度审批和 Go/No-Go。",
        href: "/admin/approvals",
        metric: "Human gates",
        status: "review",
      },
      {
        title: "推送监控与 H5",
        desc: "H5 VIP 弹窗、推送服务、Grafana、转化漏斗和 feature flag。",
        href: "/admin/delivery",
        metric: "P4/P5",
        status: "config",
      },
      {
        title: "H5 聊天",
        desc: "验证用户侧聊天、typing 动效、VIP 弹窗和支付跳转。",
        href: "/admin/h5/chat",
        metric: "H5",
        status: "online",
      },
    ],
    [conversationTotal]
  );

  return (
    <AdminFrame
      operator={operator}
      active="home"
      title="总后台"
      subtitle="对照 business-flow 业务流程表，只保留新项目需要的入口；旧版独立页面路径不再使用。"
    >
      {loadError && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          部分统计加载失败：{loadError}
        </div>
      )}

      <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        <SummaryBlock label="新后台模块" value={`${modules.length} 个入口`} />
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
    </AdminFrame>
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
