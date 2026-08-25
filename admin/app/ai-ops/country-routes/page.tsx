"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import ProtectedSubPage from "../_components/SubPageFrame";
import { apiFetch } from "@/lib/auth";

type CountryRouteItem = {
  country_code: string;
  platform_key: string;
  download_url: string | null;
};

const TARGET_T1_COUNTRIES = [
  { code: "US", name: "美国" },
  { code: "SE", name: "瑞典" },
  { code: "AT", name: "奥地利" },
  { code: "FI", name: "芬兰" },
  { code: "FR", name: "法国" },
  { code: "GB", name: "英国" },
  { code: "GR", name: "希腊" },
];

const T1_PLATFORM_KEY = "platform_c";

export default function AiOpsCountryRoutesPage() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [routes, setRoutes] = useState<Record<string, CountryRouteItem>>({});
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(TARGET_T1_COUNTRIES.map((item) => [item.code, ""])),
  );
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch<{ items: CountryRouteItem[] }>(
        "/ai-ops/admin/app-download-country-routes",
      );
      const mapping: Record<string, CountryRouteItem> = {};
      for (const item of response.items) {
        if (!item.country_code) continue;
        mapping[item.country_code] = item;
      }
      setRoutes(mapping);
      const nextValues: Record<string, string> = {};
      for (const item of TARGET_T1_COUNTRIES) {
        const record = mapping[item.code];
        nextValues[item.code] = record?.download_url?.trim() || "";
      }
      setValues(nextValues);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function setValue(code: string, value: string) {
    setValues((prev) => ({ ...prev, [code]: value }));
  }

  function clearValues() {
    const next = { ...values };
    for (const item of TARGET_T1_COUNTRIES) {
      next[item.code] = routes[item.code]?.download_url?.trim() || "";
    }
    setValues(next);
  }

  async function saveCountry(event: FormEvent, countryCode: string) {
    event.preventDefault();
    setError(null);
    const nextUrl = values[countryCode]?.trim() || "";

    if (nextUrl) {
      try {
        const parsed = new URL(nextUrl);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
          setError("下载链接请填写 http/https 链接");
          return;
        }
      } catch {
        setError("下载链接格式不正确，请填写完整 http(s) URL");
        return;
      }
    }

    setSaving((prev) => ({ ...prev, [countryCode]: true }));
    try {
      await apiFetch(`/ai-ops/admin/app-download-country-routes/${countryCode}`, {
        method: "PUT",
        body: JSON.stringify({
          platform_key: routes[countryCode]?.platform_key || T1_PLATFORM_KEY,
          download_url: nextUrl || null,
        }),
      });
      setToast(`${countryCode} 的独立链接已保存`);
      window.setTimeout(() => setToast(null), 1800);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving((prev) => ({ ...prev, [countryCode]: false }));
    }
  }

  return (
    <ProtectedSubPage
      title="国家路由（T1-D 平台）"
      subtitle="为 T1 国家设置独立下载链接"
      description="该页面用于把指定 T1 国家拆分为独立下载入口，方便后续按国家投放不同的落地页。"
    >
      <div className="rounded-md border border-slate-800 bg-slate-900 p-5">
        <p className="text-sm text-slate-200">
          目前已覆盖国家：US / SE / AT / FI / FR / GB / GR。清空输入框并保存可恢复该国家的默认平台规则。
        </p>
        {error ? <p className="mt-3 rounded bg-rose-900/30 p-3 text-sm text-rose-200">{error}</p> : null}
        {toast ? <p className="mt-3 rounded bg-emerald-900/30 p-3 text-sm text-emerald-200">{toast}</p> : null}
        {loading ? <p className="mt-3 text-sm text-slate-400">加载中...</p> : null}

        <div className="mt-4 space-y-4">
          {TARGET_T1_COUNTRIES.map((item) => {
            const current = routes[item.code];
            const platformKey = current?.platform_key || T1_PLATFORM_KEY;
            const currentUrl = current?.download_url?.trim() || "";
            return (
              <form
                key={item.code}
                className="rounded-md border border-slate-700 p-4"
                onSubmit={(event) => saveCountry(event, item.code)}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-100">
                    {item.code} - {item.name} - T1
                  </h3>
                  <span className="text-xs text-slate-400">绑定平台：{platformKey}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  当前独立链接：{currentUrl || "未配置（使用平台默认）"}
                </p>
                <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
                  <label className="flex-1">
                    <span className="mb-1 block text-xs text-slate-400">专属链接</span>
                    <input
                      value={values[item.code] || ""}
                      onChange={(event) => setValue(item.code, event.target.value)}
                      placeholder="https://..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-slate-500"
                    />
                  </label>
                  <button
                    type="submit"
                    className="rounded bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!!saving[item.code]}
                  >
                    {saving[item.code] ? "保存中..." : "保存"}
                  </button>
                </div>
                <p className="mt-2 text-xs text-slate-500">留空并保存可清除独立链接。</p>
              </form>
            );
          })}
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={clearValues}
            className="rounded border border-slate-700 px-3 py-2 text-sm text-slate-200 transition hover:bg-slate-800"
          >
            重置为当前配置
          </button>
        </div>
      </div>
    </ProtectedSubPage>
  );
}
