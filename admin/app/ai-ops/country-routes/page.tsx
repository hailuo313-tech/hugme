"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import ProtectedSubPage from "../_components/SubPageFrame";
import { apiFetch } from "@/lib/auth";

type CountryRouteItem = {
  country_code: string;
  platform_key: string;
  download_url: string | null;
};

const T1_COUNTRIES = [
  ["US", "美国"], ["CA", "加拿大"], ["GB", "英国"], ["DE", "德国"],
  ["FR", "法国"], ["IT", "意大利"], ["ES", "西班牙"], ["NL", "荷兰"],
  ["BE", "比利时"], ["CH", "瑞士"], ["AT", "奥地利"], ["IE", "爱尔兰"],
  ["DK", "丹麦"], ["NO", "挪威"], ["SE", "瑞典"], ["FI", "芬兰"],
  ["IS", "冰岛"], ["LU", "卢森堡"], ["PT", "葡萄牙"], ["GR", "希腊"],
  ["CZ", "捷克"], ["JP", "日本"], ["AU", "澳大利亚"], ["NZ", "新西兰"],
  ["SG", "新加坡"], ["HK", "中国香港"],
] as const;

const T1_PLATFORM_KEY = "platform_c";

export default function AiOpsCountryRoutesPage() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [routes, setRoutes] = useState<Record<string, CountryRouteItem>>({});
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(T1_COUNTRIES.map(([code]) => [code, ""])),
  );
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch<{ items: CountryRouteItem[] }>("/ai-ops/admin/app-download-country-routes");
      const mapping: Record<string, CountryRouteItem> = {};
      for (const item of response.items) mapping[item.country_code] = item;
      setRoutes(mapping);
      setValues(Object.fromEntries(T1_COUNTRIES.map(([code]) => [code, mapping[code]?.download_url?.trim() || ""])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function saveCountry(event: FormEvent, countryCode: string) {
    event.preventDefault();
    setError(null);
    const nextUrl = values[countryCode]?.trim() || "";
    if (nextUrl) {
      try {
        const parsed = new URL(nextUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error();
      } catch {
        setError("链接格式不正确，请填写完整的 http(s) 地址");
        return;
      }
    }
    setSaving((prev) => ({ ...prev, [countryCode]: true }));
    try {
      await apiFetch(`/ai-ops/admin/app-download-country-routes/${countryCode}`, {
        method: "PUT",
        body: JSON.stringify({ platform_key: routes[countryCode]?.platform_key || T1_PLATFORM_KEY, download_url: nextUrl || null }),
      });
      setToast(`${countryCode} 独立链接已保存`);
      window.setTimeout(() => setToast(null), 1800);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving((prev) => ({ ...prev, [countryCode]: false }));
    }
  }

  return (
    <ProtectedSubPage title="国家路由" subtitle="T1 国家独立下载链接" description="为每个 T1 国家设置独立链接；发送失败时仍按系统规则回退到 C 平台和默认平台。">
      <div className="rounded-md border border-slate-800 bg-slate-900 p-5">
        <p className="text-sm text-slate-300">共 {T1_COUNTRIES.length} 个 T1 国家。留空并保存可清除该国家的独立链接。</p>
        {error && <p className="mt-3 rounded bg-rose-900/30 p-3 text-sm text-rose-200">{error}</p>}
        {toast && <p className="mt-3 rounded bg-emerald-900/30 p-3 text-sm text-emerald-200">{toast}</p>}
        {loading && <p className="mt-3 text-sm text-slate-400">加载中...</p>}
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {T1_COUNTRIES.map(([code, name]) => {
            const current = routes[code];
            return (
              <form key={code} className="rounded-md border border-slate-700 p-4" onSubmit={(event) => saveCountry(event, code)}>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold text-slate-100">{code} - {name} - T1</h3>
                  <span className="text-xs text-slate-400">绑定平台：{current?.platform_key || T1_PLATFORM_KEY}</span>
                </div>
                <p className="mt-1 truncate text-xs text-slate-500">当前独立链接：{current?.download_url?.trim() || "未配置（使用平台默认）"}</p>
                <div className="mt-3 flex gap-3">
                  <input value={values[code] || ""} onChange={(event) => setValues((prev) => ({ ...prev, [code]: event.target.value }))} placeholder="https://..." className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500" />
                  <button disabled={!!saving[code]} className="rounded bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-60">{saving[code] ? "保存中..." : "保存"}</button>
                </div>
              </form>
            );
          })}
        </div>
      </div>
    </ProtectedSubPage>
  );
}
