"use client";

import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";

const sections = [
  {
    title: "H5 与支付",
    task: "P4-08 / P4-09",
    items: ["H5 WebSocket 正在输入动效", "VIP 弹窗文案", "支付 CTA 跳转", "H-05 产品验收"],
  },
  {
    title: "推送触达",
    task: "P4-10",
    items: ["FCM/APNs 配置", "真机推送证据", "设备 token 测试", "失败原因追踪"],
  },
  {
    title: "媒体与弱网",
    task: "P4-11",
    items: ["音视频渲染", "本地缓存", "历史播放", "弱网可看历史"],
  },
  {
    title: "监控与上线",
    task: "P5-05 / P5-08",
    items: ["Prometheus 指标", "Grafana 五大盘", "付费漏斗 SQL", "feature flag 按 level 切流"],
  },
  {
    title: "链接与 App 归因",
    task: "P3-22 / P4-12 / P5-11",
    items: ["话术链接 tracking_id", "点击国家与年龄分布", "App 下载注册回传", "付费订单归因"],
  },
];

export default function DeliveryPage() {
  return (
    <AuthGate>
      {(operator) => (
        <AdminFrame
          operator={operator}
          active="delivery"
          title="推送监控与 H5"
          subtitle="覆盖 P4/P5 的用户侧触达、H5 验收、推送、媒体缓存、链接归因、监控告警和灰度切流。"
        >
          <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {sections.map((section) => (
              <div key={section.title} className="rounded-lg border border-slate-800 bg-slate-900">
                <div className="border-b border-slate-800 px-5 py-4">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h2 className="text-lg font-semibold">{section.title}</h2>
                    <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-sky-300">{section.task}</span>
                  </div>
                </div>
                <div className="divide-y divide-slate-800">
                  {section.items.map((item) => (
                    <div key={item} className="px-5 py-4 text-sm text-slate-300">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>
        </AdminFrame>
      )}
    </AuthGate>
  );
}
