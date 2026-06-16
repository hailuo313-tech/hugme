export type IncomingReviewAlertPayload = {
  id: string;
  nickname: string | null;
  external_id: string | null;
  chat_id: number;
  inbound_call_number: number | null;
  completed_inbound_calls?: number | null;
  trigger_source?: string | null;
  matched_keyword?: string | null;
};

export function incomingReviewCallCountText(review: IncomingReviewAlertPayload): string {
  const next = review.inbound_call_number;
  const completed =
    review.completed_inbound_calls ??
    (next != null ? Math.max(0, next - 1) : null);
  if (next == null) return "视频次数未知";
  if (completed != null) {
    return `第 ${next} 次视频（已完成 ${completed} 次自动接听）`;
  }
  return `第 ${next} 次视频`;
}

export function incomingReviewAlertTitle(review: IncomingReviewAlertPayload): string {
  const name = review.nickname || review.external_id || `chat ${review.chat_id}`;
  return `待人工接听：${name}`;
}

export function incomingReviewAlertBody(review: IncomingReviewAlertPayload): string {
  const count = incomingReviewCallCountText(review);
  if (review.trigger_source === "inbound_keyword_review") {
    return `${count} · 文字请求：${review.matched_keyword || "打视频"}`;
  }
  return count;
}

export function notifyIncomingReview(review: IncomingReviewAlertPayload): void {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  const show = () => {
    new Notification(incomingReviewAlertTitle(review), {
      body: incomingReviewAlertBody(review),
      tag: `incoming-review-${review.id}`,
    });
  };
  if (Notification.permission === "granted") {
    show();
    return;
  }
  if (Notification.permission !== "denied") {
    void Notification.requestPermission().then((perm) => {
      if (perm === "granted") show();
    });
  }
}
