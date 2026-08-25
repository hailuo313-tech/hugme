"use client";

import { ReactNode } from "react";
import AuthGate from "@/components/AuthGate";
import AdminFrame from "@/components/AdminFrame";
import { Operator } from "@/lib/auth";

interface SubPageFrameProps {
  operator: Operator;
  title: string;
  subtitle: string;
  description: string;
  children?: ReactNode;
}

export function SubPageFrame({ operator, title, subtitle, description, children }: SubPageFrameProps) {
  return (
    <AdminFrame operator={operator} active="ai" title={title} subtitle={subtitle}>
      <section className="rounded-md border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-lg font-semibold text-slate-100">页面说明</h2>
        <p className="mt-2 text-sm text-slate-400">{description}</p>
      </section>
      {children ? <div className="mt-4">{children}</div> : null}
      <div className="mt-4">
        <a href="/admin/ai-ops" className="inline-flex rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:bg-slate-800">
          返回 AI 运营主页
        </a>
      </div>
    </AdminFrame>
  );
}

export default function ProtectedSubPage({ title, subtitle, description, children }: Omit<SubPageFrameProps, "operator">) {
  return (
    <AuthGate>
      {(operator) => <SubPageFrame operator={operator} title={title} subtitle={subtitle} description={description}>{children}</SubPageFrame>}
    </AuthGate>
  );
}
