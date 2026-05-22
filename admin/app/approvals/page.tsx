"use client";

import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";

const approvals = [
  ["H-01", "技术选型与部署环境", "FastAPI/PostgreSQL/Redis/WS 与 REPO_LAYOUT 一致。", "已签字"],
  ["H-02", "T1 国家与分级阈值", "S 级：T1 且累计消费 >= $200；A 级：累计消费 >= $99 或 vip_level >= 1。", "已批准"],
  ["H-05", "H5 VIP 弹窗与支付跳转", "产品验收通过后进入灰度。", "已批准"],
  ["H-07", "Week9 C/D 灰度", "仅 C/D 级切流审批。", "已批准"],
  ["H-08", "Week10-11 B/A/S 灰度", "B 级观察，A/S 接管。", "已批准"],
  ["H-09", "坐席 SOP 培训", "参训率 100%，考核通过。", "已批准"],
  ["H-10", "Go/No-Go 最终签署", "12 项检查全通过。", "GO"],
  ["H-11", "Telegram 真人号 SOP", "频率、批量、ToS 合规和频率上限签字。", "已签字"],
];

export default function ApprovalsPage() {
  return (
    <AuthGate>
      {(operator) => (
        <AdminFrame
          operator={operator}
          active="approvals"
          title="运营审批"
          subtitle="汇总 business-flow 中所有人工关口，统一展示签字项、灰度审批、SOP 和上线 Go/No-Go；这些项目已由 human_owner 在 2026-05-22 最终确认。"
        >
          <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="人工关口" value="8 项" />
            <Metric label="灰度阶段" value="2 段" />
            <Metric label="上线检查" value="12 项" />
            <Metric label="SOP" value="2 份" />
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900">
            <div className="grid grid-cols-[110px_1fr_1.2fr_120px] border-b border-slate-800 px-5 py-3 text-xs uppercase tracking-wide text-slate-500">
              <span>任务</span>
              <span>审批项</span>
              <span>验收口径</span>
              <span>状态</span>
            </div>
            <div className="divide-y divide-slate-800">
              {approvals.map(([task, title, desc, status]) => (
                <div key={task} className="grid grid-cols-1 gap-2 px-5 py-4 text-sm md:grid-cols-[110px_1fr_1.2fr_120px] md:items-center">
                  <span className="font-mono text-sky-300">{task}</span>
                  <span className="font-medium text-slate-100">{title}</span>
                  <span className="text-slate-400">{desc}</span>
                  <span className="w-fit rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300">
                    {status}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </AdminFrame>
      )}
    </AuthGate>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-5 py-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
