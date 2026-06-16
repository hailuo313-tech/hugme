export const REPORT_TIMEZONE = "Asia/Shanghai";

/** Postgres/asyncpg naive timestamps from ERIS are UTC wall-clock values. */
export function parseDbUtcTimestamp(value: string): Date | null {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(raw)) {
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const parsed = new Date(`${normalized}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatBeijingDateTime(value: string | Date | null | undefined): string {
  if (value == null || value === "") return "—";
  const d = value instanceof Date ? value : parseDbUtcTimestamp(String(value));
  if (!d || Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("zh-CN", {
    timeZone: REPORT_TIMEZONE,
    hour12: false,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function beijingYmd(offsetDays = 0): string {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: REPORT_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const today = formatter.format(new Date());
  if (offsetDays === 0) return today;

  const [year, month, day] = today.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + offsetDays, 12, 0, 0));
  return formatter.format(shifted);
}
