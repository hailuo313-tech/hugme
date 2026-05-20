/** C-11: VIP / level badge for dashboard priority (P4-04 proxy until user_level in API). */

export type LevelTier = "S" | "A" | "B" | "C" | "D";

export function vipToLevelTier(vip: number | null | undefined): LevelTier {
  const v = vip ?? 0;
  if (v >= 3) return "S";
  if (v >= 2) return "A";
  if (v >= 1) return "B";
  return "C";
}

export function levelBadgeClass(tier: LevelTier): string {
  switch (tier) {
    case "S":
      return "bg-rose-900/50 text-rose-200 border-rose-700";
    case "A":
      return "bg-orange-900/40 text-orange-200 border-orange-700";
    case "B":
      return "bg-sky-900/40 text-sky-200 border-sky-700";
    case "C":
      return "bg-slate-800 text-slate-300 border-slate-600";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

export function rowPriorityClass(state: string | null, vip: number | null): string {
  if (state === "WAITING_OPERATOR") {
    return "bg-amber-950/40 ring-1 ring-amber-800/60";
  }
  if (vipToLevelTier(vip) === "S") {
    return "bg-rose-950/20";
  }
  return "";
}
