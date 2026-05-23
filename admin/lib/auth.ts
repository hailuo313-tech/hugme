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

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(resolveApiPath(path), { ...options, headers });
  if (res.status === 401) {
    clearAuth();
    window.location.href = LOGIN_PATH;
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail || res.statusText);
  }
  return res.json() as Promise<T>;
}
