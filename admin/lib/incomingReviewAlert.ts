export type IncomingReviewAlertPayload = {
  id: string;
  nickname: string | null;
  external_id: string | null;
  chat_id: number;
  call_number?: number | null;
  call_attempt_number?: number | null;
  inbound_call_number: number | null;
  completed_calls?: number | null;
  completed_inbound_calls?: number | null;
  trigger_source?: string | null;
  matched_keyword?: string | null;
};

/** 用户主动打来几次（含曾进入人工队列的来电尝试）。 */
export function incomingReviewUserCallCountText(review: IncomingReviewAlertPayload): string {
  const attemptNumber =
    review.call_attempt_number ?? review.call_number ?? review.inbound_call_number ?? 1;
  if (review.trigger_source === "inbound_keyword_review") {
    const played = review.completed_calls ?? 0;
    return `文字打视频（非来电）· 历史已播放 ${played} 次 · 视频链路累计 ${attemptNumber} 次`;
  }
  return `用户累计第 ${attemptNumber} 次打来（此前累计 ${Math.max(0, attemptNumber - 1)} 次）`;
}

/** 卡片内：本次应播哪段来电视频。 */
export function incomingReviewVideoHeadline(review: IncomingReviewAlertPayload): string {
  if (review.trigger_source === "inbound_keyword_review") {
    return `请选择播放视频 · 文字请求 ${review.matched_keyword || "打视频"}`;
  }
  const attempt = review.inbound_call_number ?? 1;
  const playSeq = attempt >= 3 ? 3 : attempt;
  return `推荐播放：第 ${playSeq} 次来电视频`;
}

export function incomingReviewCallCountText(review: IncomingReviewAlertPayload): string {
  return incomingReviewUserCallCountText(review);
}

export function incomingReviewAlertTitle(review: IncomingReviewAlertPayload): string {
  const name = review.nickname || review.external_id || `chat ${review.chat_id}`;
  return `待人工接听：${name}`;
}

export function incomingReviewAlertBody(review: IncomingReviewAlertPayload): string {
  return incomingReviewUserCallCountText(review);
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
