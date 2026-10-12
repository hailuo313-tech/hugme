// lib/auth.ts — JWT 存取工具（浏览器端，存在 localStorage）
// 须与 next.config.js 的 basePath=/admin 一致（硬跳转不能用 "/login"）

export const ADMIN_BASE_PATH = "/admin";
export const DEFAULT_ADMIN_ENTRY_PATH = ADMIN_BASE_PATH;
export const LOGIN_PATH = `${ADMIN_BASE_PATH}/login`;

export const TOKEN_KEY = "eris_admin_token";
export const OPERATOR_KEY = "eris_admin_operator";

export interface Operator {
  operator_id: string;
  username: string;
  display_name: string | null;
  role: string;
}

function getBrowserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

export function saveAuth(token: string, operator: Operator) {
  const storage = getBrowserStorage();
  if (!storage) return;
  storage.setItem(TOKEN_KEY, token);
  storage.setItem(OPERATOR_KEY, JSON.stringify(operator));
}

export function getToken(): string | null {
  return getBrowserStorage()?.getItem(TOKEN_KEY) ?? null;
}

export function getOperator(): Operator | null {
  const raw = getBrowserStorage()?.getItem(OPERATOR_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export function clearAuth() {
  const storage = getBrowserStorage();
  if (!storage) return;
  storage.removeItem(TOKEN_KEY);
  storage.removeItem(OPERATOR_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

// ERIS API base (relative — Next.js rewrite proxies /api/* to FastAPI)
export const API_BASE = "/api/v1";

function resolveApiPath(path: string): string {
  if (path.startsWith("/api/")) return path;
  if (path.startsWith("/")) return `${API_BASE}${path}`;
  return `${API_BASE}/${path}`;
}

type FastApiErrorItem = {
  msg?: string;
  loc?: (string | number)[];
};

export function formatApiErrorDetail(detail: unknown, fallback = "Request failed"): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const err = item as FastApiErrorItem;
          const loc = Array.isArray(err.loc) ? err.loc.join(".") : "";
          return loc ? `${loc}: ${err.msg}` : (err.msg || null);
        }
        return null;
      })
      .filter((part): part is string => Boolean(part));
    return parts.length > 0 ? parts.join("; ") : fallback;
  }
  if (typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail);
}

const TRANSIENT_GATEWAY_STATUSES = new Set([502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export type ApiFetchOptions = RequestInit & {
  /** Retry count for transient gateway errors (502/503/504). */
  retries?: number;
};

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { retries = 0, ...fetchOptions } = options;
  const token = getToken();
  const headers: Record<string, string> = { ...(fetchOptions.headers as Record<string, string>) };
  if (!(fetchOptions.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    let res: Response;
    try {
      res = await fetch(resolveApiPath(path), { ...fetchOptions, headers });
    } catch (error) {
      if (attempt < retries) {
        await sleep(400 * (attempt + 1));
        continue;
      }
      throw error;
    }
    if (res.status === 401) {
      clearAuth();
      window.location.href = LOGIN_PATH;
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({})) as { detail?: unknown };
      const message = formatApiErrorDetail(err.detail, res.statusText);
      if (TRANSIENT_GATEWAY_STATUSES.has(res.status) && attempt < retries) {
        await sleep(400 * (attempt + 1));
        continue;
      }
      throw new Error(message);
    }
    return res.json() as Promise<T>;
  }

  throw new Error("Request failed");
}
