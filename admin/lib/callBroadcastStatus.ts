export function callStatusLabel(
  status: string | null | undefined,
  failureReason?: string | null,
): string {
  if (status === "failed") {
    const reason = (failureReason || "").toLowerCase();
    if (reason.includes("not answered") || reason.includes("timedoutanswer")) return "未接听";
    if (reason.includes("is busy")) return "用户占线";
    if (reason.includes("declined") || reason.includes("discarded")) return "用户已挂断";
  }
  switch (status) {
    case "completed":
      return "成功";
    case "cancelled":
      return "未成功";
    case "failed":
      return "失败";
    case "pending":
      return "待执行";
    case "pending_operator":
      return "待人工接听";
    case "dialing":
      return "正在接听";
    case "streaming":
      return "通话中";
    case "running":
      return "执行中";
    default:
      return status || "—";
  }
}

export function callStatusClassName(status: string | null | undefined): string {
  switch (status) {
    case "completed":
      return "text-emerald-300";
    case "cancelled":
      return "text-amber-300";
    case "failed":
      return "text-rose-300";
    case "pending_operator":
      return "text-amber-200";
    case "dialing":
    case "streaming":
    case "running":
      return "text-sky-300";
    case "pending":
      return "text-slate-400";
    default:
      return "text-slate-300";
  }
}

export function formatCallDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Number(seconds) || 0);
  if (total < 60) return `${total} 秒`;
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return secs > 0 ? `${mins} 分 ${secs} 秒` : `${mins} 分`;
}

export function callDurationLabel(
  record: {
    status: string | null | undefined;
    duration_seconds?: number | null;
    started_at?: string | null;
  },
): string {
  const status = record.status || "";
  const duration = Number(record.duration_seconds) || 0;
  if (
    duration > 0 &&
    (status === "completed" ||
      status === "cancelled" ||
      status === "failed")
  ) {
    return formatCallDuration(duration);
  }
  if (status === "streaming" || status === "dialing" || status === "running") {
    if (record.started_at) {
      const startedMs = new Date(record.started_at).getTime();
      if (!Number.isNaN(startedMs)) {
        const elapsed = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
        if (elapsed > 0) {
          return `${formatCallDuration(elapsed)}（进行中）`;
        }
      }
    }
    return "进行中";
  }
  if (status === "pending_operator") {
    return "待接听";
  }
  return "—";
}
