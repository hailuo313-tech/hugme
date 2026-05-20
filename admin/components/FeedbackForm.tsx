"use client";

import { useState } from "react";

interface FeedbackData {
  overall_satisfaction: number;
  usability_rating: number;
  ai_assist_rating: number;
  translation_quality: number;
  features_used: string[];
  issues: string;
  suggestions: string;
  operator_id?: string;
}

interface FeedbackFormProps {
  operatorId?: string;
  onSubmit: (feedback: FeedbackData) => Promise<void>;
  onCancel: () => void;
}

const FEATURE_OPTIONS = [
  { id: "session_list", label: "会话列表筛选" },
  { id: "ai_assist", label: "AI 辅助功能" },
  { id: "translation", label: "消息翻译" },
  { id: "draft_edit", label: "草稿编辑" },
  { id: "user_profile", label: "用户画像查看" },
  { id: "memory_view", label: "记忆查看" },
];

export default function FeedbackForm({ operatorId, onSubmit, onCancel }: FeedbackFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState<FeedbackData>({
    overall_satisfaction: 5,
    usability_rating: 5,
    ai_assist_rating: 5,
    translation_quality: 5,
    features_used: [],
    issues: "",
    suggestions: "",
    operator_id: operatorId,
  });

  const handleRatingChange = (field: keyof FeedbackData, value: number) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleFeatureToggle = (featureId: string) => {
    setFormData(prev => ({
      ...prev,
      features_used: prev.features_used.includes(featureId)
        ? prev.features_used.filter(f => f !== featureId)
        : [...prev.features_used, featureId]
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await onSubmit(formData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
      setSubmitting(false);
    }
  };

  const StarRating = ({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) => (
    <div className="mb-4">
      <label className="block text-sm font-medium text-slate-300 mb-2">{label}</label>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => onChange(star)}
            className={`text-2xl transition ${star <= value ? "text-amber-400" : "text-slate-600 hover:text-slate-500"}`}
          >
            ★
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 rounded-xl border border-slate-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">坐席看板使用反馈</h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-slate-400 hover:text-white"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="bg-rose-900/30 border border-rose-800 text-rose-200 text-sm rounded-md px-4 py-3">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <h3 className="text-sm font-medium text-slate-300">评分（1-5星，5星最好）</h3>
            
            <StarRating
              value={formData.overall_satisfaction}
              onChange={(v) => handleRatingChange("overall_satisfaction", v)}
              label="整体满意度"
            />
            
            <StarRating
              value={formData.usability_rating}
              onChange={(v) => handleRatingChange("usability_rating", v)}
              label="界面易用性"
            />
            
            <StarRating
              value={formData.ai_assist_rating}
              onChange={(v) => handleRatingChange("ai_assist_rating", v)}
              label="AI 辅助功能准确性"
            />
            
            <StarRating
              value={formData.translation_quality}
              onChange={(v) => handleRatingChange("translation_quality", v)}
              label="消息翻译质量"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              使用过的功能（可多选）
            </label>
            <div className="grid grid-cols-2 gap-2">
              {FEATURE_OPTIONS.map((feature) => (
                <label key={feature.id} className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={formData.features_used.includes(feature.id)}
                    onChange={() => handleFeatureToggle(feature.id)}
                    className="rounded border-slate-700 bg-slate-800 text-violet-600"
                  />
                  {feature.label}
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              遇到的问题 *
            </label>
            <textarea
              value={formData.issues}
              onChange={(e) => setFormData(prev => ({ ...prev, issues: e.target.value }))}
              rows={4}
              required
              placeholder="请描述使用过程中遇到的任何问题或困难..."
              className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-100 placeholder-slate-600"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              改进建议
            </label>
            <textarea
              value={formData.suggestions}
              onChange={(e) => setFormData(prev => ({ ...prev, suggestions: e.target.value }))}
              rows={3}
              placeholder="请提出您的改进建议..."
              className="w-full bg-slate-950 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-100 placeholder-slate-600"
            />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-md transition"
            >
              {submitting ? "提交中..." : "提交反馈"}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={submitting}
              className="px-4 py-2 border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              取消
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}