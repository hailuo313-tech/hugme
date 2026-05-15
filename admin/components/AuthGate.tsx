"use client";

/**
 * AuthGate — 统一鉴权守卫（DEV-D8-01）
 *
 * 规则：
 * 1. 未登录（无 token）→ window.location.href = LOGIN_PATH（硬跳转，与 apiFetch 401 一致）
 * 2. Half-auth（有 token、无 operator JSON）→ clearAuth() + 硬跳转
 * 3. 已登录 → 渲染子节点，并通过 renderProps 把 operator 传下去
 *
 * 使用方式：
 * <AuthGate>{(operator) => <YourPage operator={operator} />}</AuthGate>
 */

import { useEffect, useState } from "react";
import {
  clearAuth,
  getOperator,
  isLoggedIn,
  LOGIN_PATH,
  Operator,
} from "@/lib/auth";

interface AuthGateProps {
  children: (operator: Operator) => React.ReactNode;
}

export default function AuthGate({ children }: AuthGateProps) {
  const [operator, setOperator] = useState<Operator | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      window.location.href = LOGIN_PATH;
      return;
    }
    const op = getOperator();
    if (!op) {
      // half-auth：token 存在但 operator JSON 缺失，清除并重新登录
      clearAuth();
      window.location.href = LOGIN_PATH;
      return;
    }
    setOperator(op);
  }, []);

  if (!operator) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-400 flex items-center justify-center">
        <span className="text-sm">加载中…</span>
      </div>
    );
  }

  return <>{children(operator)}</>;
}
