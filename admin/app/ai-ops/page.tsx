"use client";

import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";

const scriptHooks = [
  ["入站", "P3-20", "入站消息先匹配话术，记录 script_hit_id。"],
  ["消费", "P3-20", "结合消费/付费场景匹配转化底料。"],
  ["探测", "P2-03", "D 级画像缺口触发探测话术。"],
  ["分级", "P2-09", "路由与 level 一致，S/A 进入接管。"],
  ["回复", "P3-11", "LLM 只包装已命中话术底料。"],
  ["坐席", "P4-05", "坐席可选用推荐话术或改写。"],
  ["出站", "P3-17", "120s 超时投递兜底话术。"],
  ["归档", "P3-21", "任一步可反查命中话术。"],
];

const policyItems = [
  ["H-03", "话术底料审核", "问候/转化/拒绝等 >=50 条底料批准。"],
  ["H-04", "AI 人设与禁用词", "persona prompt、性格边界、安全禁用词签字。"],
  ["P3-05", "意图 taxonomy", "意图标签、置信度、低置信降级策略统一。"],
  ["P3-12", "安全过滤", "红线 100% 拦截，拒答原因可审计。"],
];

export default function AiOpsPage() {
  return (
    <AuthGate>
      {(operator) => (
        <AdminFrame
          operator={operator}
          active="ai"
          title="AI 话术与人设"
          subtitle="覆盖 business-flow 的 P3 AI 链路：话术底料、意图识别、persona prompt、安全过滤和全链路 script_hit 审计。"
        >
          <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="话术类目" value="5 类" />
            <Metric label="全链路钩子" value="8 个" />
            <Metric label="回归集" value="50 条" />
            <Metric label="安全红线" value="100%" />
          </section>

          <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900">
            <div className="border-b border-slate-800 px-5 py-4">
              <h2 className="text-lg font-semibold">script_match 全链路</h2>
              <p className="mt-1 text-sm text-slate-400">每一步必须有 match 结果或明确降级。</p>
            </div>
            <div className="grid grid-cols-1 divide-y divide-slate-800 md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-4">
              {scriptHooks.map(([name, task, desc]) => (
                <div key={name} className="p-5">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h3 className="font-medium text-white">{name}</h3>
                    <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-sky-300">{task}</span>
                  </div>
                  <p className="text-sm leading-6 text-slate-400">{desc}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="审核与配置">
              {policyItems.map(([task, title, desc]) => (
                <Row key={task} task={task} title={title} desc={desc} />
              ))}
            </Panel>
            <Panel title="后台需要承载的动作">
              <Action text="查看 script_templates 五类底料数量和缺口。" />
              <Action text="查看 Top3 话术命中、confidence、intent 和 fallback 原因。" />
              <Action text="查看 persona_prompts 与禁用词版本，等待人工签字。" />
              <Action text="按 conversation_script_hits 反查每一步命中的话术。" />
            </Panel>
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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-5 py-4 text-lg font-semibold">{title}</h2>
      <div className="divide-y divide-slate-800">{children}</div>
    </div>
  );
}

function Row({ task, title, desc }: { task: string; title: string; desc: string }) {
  return (
    <div className="p-5">
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded bg-violet-500/10 px-2 py-0.5 text-xs text-violet-300">{task}</span>
        <span className="font-medium text-slate-100">{title}</span>
      </div>
      <p className="text-sm leading-6 text-slate-400">{desc}</p>
    </div>
  );
}

function Action({ text }: { text: string }) {
  return <div className="p-5 text-sm leading-6 text-slate-300">{text}</div>;
}
