"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import ProtectedSubPage from "../_components/SubPageFrame";
import { apiFetch } from "@/lib/auth";

type Tab = "t1" | "platforms" | "routes";
type RouteItem = { country_code: string; platform_key: string; download_url: string | null };
type Platform = { id: string; platform_key: string; display_name: string; download_url: string; is_active: boolean; is_default: boolean };
const T1 = [["US","美国"],["CA","加拿大"],["GB","英国"],["DE","德国"],["FR","法国"],["IT","意大利"],["ES","西班牙"],["NL","荷兰"],["BE","比利时"],["CH","瑞士"],["AT","奥地利"],["IE","爱尔兰"],["DK","丹麦"],["NO","挪威"],["SE","瑞典"],["FI","芬兰"],["IS","冰岛"],["LU","卢森堡"],["PT","葡萄牙"],["GR","希腊"],["CZ","捷克"],["JP","日本"],["AU","澳大利亚"],["NZ","新西兰"],["SG","新加坡"],["HK","中国香港"]] as const;
const KEYS = ["platform_a","platform_b","platform_c","platform_d","platform_e","platform_f"];

export default function CountryRoutesPage() {
  const [tab, setTab] = useState<Tab>("t1");
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [routes, setRoutes] = useState<Record<string, RouteItem>>({});
  const [links, setLinks] = useState<Record<string, string>>({});
  const [platformForm, setPlatformForm] = useState({ platform_key: "platform_a", display_name: "A平台", download_url: "" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [routeForm, setRouteForm] = useState({ country_code: "US", platform_key: "platform_c" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, r] = await Promise.all([
        apiFetch<{items: Platform[]}>("/ai-ops/admin/app-download-platforms"),
        apiFetch<{items: RouteItem[]}>("/ai-ops/admin/app-download-country-routes"),
      ]);
      setPlatforms(p.items);
      const map: Record<string, RouteItem> = {};
      r.items.forEach((item) => { map[item.country_code] = item; });
      setRoutes(map);
      setLinks(Object.fromEntries(T1.map(([code]) => [code, map[code]?.download_url || ""])));
    } catch (e) { setError(e instanceof Error ? e.message : "加载失败"); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const routeList = useMemo(() => Object.values(routes).sort((a,b) => a.country_code.localeCompare(b.country_code)), [routes]);
  function notice(text: string) { setToast(text); window.setTimeout(() => setToast(null), 1800); }
  function urlOk(value: string) { try { return !value || ["http:","https:"].includes(new URL(value).protocol); } catch { return false; } }

  async function saveT1(e: FormEvent, code: string) {
    e.preventDefault(); const download_url = (links[code] || "").trim();
    if (!urlOk(download_url)) { setError("请填写完整的 http(s) 链接"); return; }
    setBusy(code); setError(null);
    try { await apiFetch(`/ai-ops/admin/app-download-country-routes/${code}`, { method:"PUT", body:JSON.stringify({ platform_key:routes[code]?.platform_key || "platform_c", download_url:download_url || null }) }); notice(`${code} 已保存`); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "保存失败"); } finally { setBusy(""); }
  }
  async function savePlatform(e: FormEvent) {
    e.preventDefault();
    if (!platformForm.display_name.trim() || !urlOk(platformForm.download_url.trim())) { setError("平台名称或链接格式不正确"); return; }
    setBusy("platform"); setError(null);
    try {
      await apiFetch(editingId ? `/ai-ops/admin/app-download-platforms/${editingId}` : "/ai-ops/admin/app-download-platforms", { method:editingId ? "PATCH":"POST", body:JSON.stringify({ ...platformForm, is_active:true, is_default:platforms.length===0, sort_order:platforms.length }) });
      notice(editingId ? "平台已更新":"平台已添加"); setEditingId(null); setPlatformForm({platform_key:"platform_a",display_name:"A平台",download_url:""}); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); } finally { setBusy(""); }
  }
  async function patchPlatform(id:string, body:Partial<Platform>) { setBusy(id); try { await apiFetch(`/ai-ops/admin/app-download-platforms/${id}`, {method:"PATCH",body:JSON.stringify(body)}); await load(); } catch(e) { setError(e instanceof Error ? e.message:"操作失败"); } finally { setBusy(""); } }
  async function removePlatform(id:string) { if(!confirm("确认删除这个平台？")) return; await apiFetch(`/ai-ops/admin/app-download-platforms/${id}`,{method:"DELETE"}); notice("平台已删除"); await load(); }
  async function saveRoute(e:FormEvent) { e.preventDefault(); setBusy("route"); try { await apiFetch(`/ai-ops/admin/app-download-country-routes/${routeForm.country_code.toUpperCase()}`,{method:"PUT",body:JSON.stringify({platform_key:routeForm.platform_key})}); notice("国家路由已保存"); await load(); } catch(e) { setError(e instanceof Error ? e.message:"保存失败"); } finally { setBusy(""); } }
  async function removeRoute(code:string) { if(!confirm(`确认删除 ${code} 的国家路由？`)) return; await apiFetch(`/ai-ops/admin/app-download-country-routes/${code}`,{method:"DELETE"}); notice("路由已删除"); await load(); }

  return <ProtectedSubPage title="国家路由" subtitle="三个区块切换管理" description="T1 独立链接、三方平台下载链接和国家路由绑定集中在此页面，原发送及失败回退规则不变。">
    <div className="mb-4 flex flex-wrap gap-2 rounded-md border border-slate-800 bg-slate-900 p-3">
      {([['t1','T1 独立链接'],['platforms','三方平台下载链接'],['routes','国家路由绑定']] as const).map(([key,label]) => <button key={key} onClick={()=>setTab(key)} className={`rounded-md px-4 py-2 text-sm font-medium ${tab===key?'bg-blue-600 text-white':'border border-slate-700 text-slate-300 hover:bg-slate-800'}`}>{label}</button>)}
    </div>
    {error && <div className="mb-4 rounded border border-rose-800 bg-rose-950/50 p-3 text-sm text-rose-200">{error}</div>}
    {toast && <div className="mb-4 rounded border border-emerald-800 bg-emerald-950/50 p-3 text-sm text-emerald-200">{toast}</div>}

    {tab==="t1" && <section className="rounded-md border border-slate-800 bg-slate-900 p-5"><h2 className="text-lg font-semibold">T1 国家独立链接</h2><p className="mt-1 text-sm text-slate-400">共 {T1.length} 个国家，留空保存可清除独立链接。</p><div className="mt-4 grid gap-4 lg:grid-cols-2">{T1.map(([code,name]) => <form key={code} onSubmit={(e)=>saveT1(e,code)} className="rounded border border-slate-700 p-4"><div className="flex justify-between gap-2"><strong>{code} - {name} - T1</strong><span className="text-xs text-slate-400">{routes[code]?.platform_key || 'platform_c'}</span></div><p className="mt-1 truncate text-xs text-slate-500">当前：{routes[code]?.download_url || '使用平台默认链接'}</p><div className="mt-3 flex gap-2"><input value={links[code]||''} onChange={(e)=>setLinks({...links,[code]:e.target.value})} placeholder="https://..." className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"/><button disabled={busy===code} className="rounded bg-blue-600 px-4 py-2 text-sm disabled:opacity-50">保存</button></div></form>)}</div></section>}

    {tab==="platforms" && <section className="grid gap-4 xl:grid-cols-[360px_1fr]"><form onSubmit={savePlatform} className="rounded-md border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">{editingId?'编辑平台':'新增平台'}</h2><div className="space-y-3"><select disabled={!!editingId} value={platformForm.platform_key} onChange={(e)=>setPlatformForm({...platformForm,platform_key:e.target.value})} className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2">{KEYS.map(k=><option key={k}>{k}</option>)}</select><input value={platformForm.display_name} onChange={(e)=>setPlatformForm({...platformForm,display_name:e.target.value})} placeholder="平台名称" className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2"/><input value={platformForm.download_url} onChange={(e)=>setPlatformForm({...platformForm,download_url:e.target.value})} placeholder="下载链接" className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2"/><button disabled={busy==='platform'} className="rounded bg-blue-600 px-4 py-2">{editingId?'保存修改':'添加平台'}</button></div></form><Table headers={['平台','链接','状态','操作']}>{platforms.map(p=><tr key={p.id}><td className="p-4"><strong>{p.display_name}</strong><div className="text-xs text-slate-500">{p.platform_key}</div></td><td className="max-w-sm truncate p-4 text-cyan-300">{p.download_url}</td><td className="p-4">{p.is_default?'默认 / ':''}{p.is_active?'启用':'停用'}</td><td className="p-4"><div className="flex flex-wrap gap-2"><Small onClick={()=>{setEditingId(p.id);setPlatformForm(p)}}>编辑</Small><Small onClick={()=>patchPlatform(p.id,{is_default:true})}>设默认</Small><Small onClick={()=>patchPlatform(p.id,{is_active:!p.is_active})}>{p.is_active?'停用':'启用'}</Small><Small onClick={()=>removePlatform(p.id)} danger>删除</Small></div></td></tr>)}</Table></section>}

    {tab==="routes" && <section className="grid gap-4 xl:grid-cols-[360px_1fr]"><form onSubmit={saveRoute} className="rounded-md border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">绑定国家到平台</h2><div className="space-y-3"><input value={routeForm.country_code} maxLength={2} onChange={(e)=>setRouteForm({...routeForm,country_code:e.target.value.toUpperCase()})} placeholder="国家代码，如 US" className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2"/><select value={routeForm.platform_key} onChange={(e)=>setRouteForm({...routeForm,platform_key:e.target.value})} className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2">{KEYS.map(k=><option key={k} value={k}>{platforms.find(p=>p.platform_key===k)?.display_name||k}</option>)}</select><button disabled={busy==='route'} className="rounded bg-blue-600 px-4 py-2">保存路由</button></div></form><Table headers={['国家','平台','独立链接','操作']}>{routeList.map(r=><tr key={r.country_code}><td className="p-4 font-semibold">{r.country_code}</td><td className="p-4">{platforms.find(p=>p.platform_key===r.platform_key)?.display_name||r.platform_key}</td><td className="max-w-sm truncate p-4 text-slate-400">{r.download_url||'跟随平台'}</td><td className="p-4"><Small onClick={()=>removeRoute(r.country_code)} danger>删除</Small></td></tr>)}</Table></section>}
  </ProtectedSubPage>;
}

function Table({headers,children}:{headers:string[];children:React.ReactNode}) { return <div className="overflow-x-auto rounded-md border border-slate-800 bg-slate-900"><table className="min-w-full text-left text-sm"><thead className="bg-slate-950/60 text-slate-400"><tr>{headers.map(h=><th key={h} className="p-4">{h}</th>)}</tr></thead><tbody className="divide-y divide-slate-800">{children}</tbody></table></div>; }
function Small({children,onClick,danger=false}:{children:React.ReactNode;onClick:()=>void;danger?:boolean}) { return <button type="button" onClick={onClick} className={`rounded border px-3 py-1 ${danger?'border-rose-700 text-rose-200':'border-slate-700 text-slate-200'}`}>{children}</button>; }
