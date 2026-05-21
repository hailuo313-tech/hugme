"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

interface FeedbackItem {
  id: number;
  operator_id: string | null;
  overall_satisfaction: number;
  usability_rating: number;
  ai_assist_rating: number;
  translation_quality: number;
  features_used: string[];
  issues: string;
  suggestions: string;
  status: string;
  admin_notes: string | null;
  created_at: string;
  updated_at: string;
}

interface ListResponse {
  items: FeedbackItem[];
  total: number;
  limit: number;
  offset: number;
}

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "reviewed", label: "已审核" },
  { value: "resolved", label: "已解决" },
];

export default function FeedbackManagementPage() {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [updating, setUpdating] = useState(false);
  const [newStatus, setNewStatus] = useState("");
  const [adminNotes, setAdminNotes] = useState("");

  const loadFeedback = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: "50",
        offset: "0",
      });
      if (statusFilter) params.set("status", statusFilter);

      const resp = await apiFetch<ListResponse>(
        `/admin/feedback?${params.toString()}`
      );
      setItems(resp.items);
      setTotal(resp.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  const handleUpdateStatus = async () => {
    if (!selectedFeedback || !newStatus) return;

    setUpdating(true);
    try {
      await apiFetch(`/admin/feedback/${selectedFeedback.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: newStatus,
          admin_notes: adminNotes,
        }),
      });

      alert("反馈状态更新成功！");
      setSelectedFeedback(null);
      setNewStatus("");
      setAdminNotes("");
      loadFeedback();
    } catch (e) {
      alert(e instanceof Error ? e.message : "更新失败");
    } finally {
      setUpdating(false);
    }
  };

  const StarRating = ({ value }: { value: number }) => (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          className={`text-sm ${star <= value ? "text-amber-400" : "text-slate-600"}`}
        >
          ★
        </span>
      ))}
    </div>
  );

  const statusColor = (status: string) => {
    switch (status) {
      case "pending":
        return "bg-amber-900/30 text-amber-200 border-amber-800";
      case "reviewed":
        return "bg-sky-900/30 text-sky-200 border-sky-800";
      case "resolved":
        return "bg-emerald-900/30 text-emerald-200 border-emerald-800";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  const statusLabel = (status: string) => {
    switch (status) {
      case "pending":
        return "待处理";
      case "reviewed":
        return "已审核";
      case "resolved":
        return "已解决";
      default:
        return status;
    }
  };

  const processedCount = items.filter(f => f.status === "resolved").length;

  return (
    <AuthGate>{() => (
      <div className="min-h-screen bg-slate-950">
        {/* Header */}
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
              <span className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium">
                反馈管理
              </span>
            </nav>
          </div>
        </header>

        {/* Main */}
        <main className="p-8 max-w-7xl mx-auto">
          <div className="flex items-baseline justify-between mb-6">
            <div>
              <h1 className="text-2xl font-semibold mb-1">反馈管理</h1>
              <p className="text-slate-400 text-sm">
                共 {total} 条反馈 · 已处理 {processedCount} 条 · 
                验收标准：≥5 条已处理 {processedCount >= 5 ? "✅" : "⏳"}
              </p>
            </div>
          </div>

          {/* Filters */}
          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-4 flex items-center gap-3">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-900 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              onClick={loadFeedback}
              className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-md transition"
            >
              刷新
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3 mb-4">
              {error}
            </div>
          )}

          {/* Table */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">ID</th>
                  <th className="text-left px-4 py-3 font-medium">操作员</th>
                  <th className="text-left px-4 py-3 font-medium">满意度</th>
                  <th className="text-left px-4 py-3 font-medium">状态</th>
                  <th className="text-left px-4 py-3 font-medium">问题描述</th>
                  <th className="text-left px-4 py-3 font-medium">提交时间</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/60">
                {loading && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                      加载中…
                    </td>
                  </tr>
                )}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                      暂无反馈
                    </td>
                  </tr>
                )}
                {!loading &&
                  items.map((item) => (
                    <tr key={item.id} className="hover:bg-slate-700/30 transition">
                      <td className="px-4 py-3 text-slate-300">#{item.id}</td>
                      <td className="px-4 py-3 text-slate-300">
                        {item.operator_id || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <StarRating value={item.overall_satisfaction} />
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 text-xs rounded-full border ${statusColor(
                            item.status
                          )}`}
                        >
                          {statusLabel(item.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-300 max-w-xs truncate">
                        {item.issues}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">
                        {new Date(item.created_at).toLocaleString("zh-CN")}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => {
                            setSelectedFeedback(item);
                            setNewStatus(item.status);
                            setAdminNotes(item.admin_notes || "");
                          }}
                          className="text-violet-400 hover:text-violet-300 text-xs"
                        >
                          查看/处理
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </main>

        {/* Detail Modal */}
        {selectedFeedback && (
          <div
            className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
            onClick={() => setSelectedFeedback(null)}
          >
            <div
              className="bg-slate-900 rounded-xl border border-slate-700 w-full max-w-3xl max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-100">
                  反馈详情 #{selectedFeedback.id}
                </h2>
                <button
                  onClick={() => setSelectedFeedback(null)}
                  className="text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              </div>

              <div className="p-6 space-y-6">
                {/* 基本信息 */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-slate-500 mb-1">操作员ID</div>
                    <div className="text-slate-200">
                      {selectedFeedback.operator_id || "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 mb-1">提交时间</div>
                    <div className="text-slate-200">
                      {new Date(selectedFeedback.created_at).toLocaleString("zh-CN")}
                    </div>
                  </div>
                </div>

                {/* 评分 */}
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-slate-300">评分</h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-xs text-slate-500 mb-1">整体满意度</div>
                      <StarRating value={selectedFeedback.overall_satisfaction} />
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-1">界面易用性</div>
                      <StarRating value={selectedFeedback.usability_rating} />
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-1">AI辅助准确性</div>
                      <StarRating value={selectedFeedback.ai_assist_rating} />
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-1">翻译质量</div>
                      <StarRating value={selectedFeedback.translation_quality} />
                    </div>
                  </div>
                </div>

                {/* 使用功能 */}
                <div>
                  <div className="text-xs text-slate-500 mb-2">使用过的功能</div>
                  <div className="flex flex-wrap gap-2">
                    {selectedFeedback.features_used.length === 0 ? (
                      <span className="text-slate-500 text-sm">无</span>
                    ) : (
                      selectedFeedback.features_used.map((feature) => (
                        <span
                          key={feature}
                          className="text-xs bg-slate-800 text-slate-300 px-2 py-1 rounded-md"
                        >
                          {feature}
                        </span>
                      ))
                    )}
                  </div>
                </div>

                {/* 问题描述 */}
                <div>
                  <div className="text-xs text-slate-500 mb-2">问题描述</div>
                  <div className="bg-slate-950 border border-slate-700 rounded-md p-3 text-sm text-slate-200">
                    {selectedFeedback.issues}
                  </div>
                </div>

                {/* 改进建议 */}
                {selectedFeedback.suggestions && (
                  <div>
                    <div className="text-xs text-slate-500 mb-2">改进建议</div>
                    <div className="bg-slate-950 border border-slate-700 rounded-md p-3 text-sm text-slate-200">
                      {selectedFeedback.suggestions}
                    </div>
                  </div>
                )}

                {/* 管理员处理 */}
                <div className="border-t border-slate-700 pt-6">
                  <h3 className="text-sm font-medium text-slate-300 mb-4">管理员处理</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs text-slate-500 mb-2">
                        状态
                      </label>
                      <select
                        value={newStatus}
                        onChange={(e) => setNewStatus(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200"
                      >
                        <option value="pending">待处理</option>
                        <option value="reviewed">已审核</option>
                        <option value="resolved">已解决</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-2">
                        处理备注
                      </label>
                      <textarea
                        value={adminNotes}
                        onChange={(e) => setAdminNotes(e.target.value)}
                        rows={3}
                        placeholder="填写处理备注..."
                        className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 placeholder-slate-600"
                      />
                    </div>
                    <div className="flex gap-3">
                      <button
                        onClick={handleUpdateStatus}
                        disabled={updating}
                        className="flex-1 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-md transition"
                      >
                        {updating ? "更新中..." : "更新状态"}
                      </button>
                      <button
                        onClick={() => setSelectedFeedback(null)}
                        disabled={updating}
                        className="px-4 py-2 border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )}
    </AuthGate>
  );
}
