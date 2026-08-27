"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AdminFrame from "@/components/AdminFrame";
import AuthGate from "@/components/AuthGate";
import { apiFetch, Operator } from "@/lib/auth";

type Account = { id:string; display_name:string|null; username:string|null; phone:string|null; status:string; is_active:boolean; first_connected_at:string|null; connection_days:number|null; tier:number|null; effective_daily_limit:number|null };
type Candidate = { user_id:string; external_id:string; nickname:string|null; language:string|null; risk_level:string|null; chat_id:number; last_message_at:string|null; last_seen_at:string; already_migrating:boolean };
type Campaign = { id:string; name:string; status:string; rate_per_minute:number; source_account:string|null; target_account:string|null; total:number; success:number; sent:number; unreachable:number; restricted:number; retry_wait:number; pending:number; created_at:string };
type MigrationTask = { id:string; external_id:string; nickname:string|null; telegram_chat_id:number; status:string; attempt_count:number; failure_reason:string|null; sent_at:string|null; replied_at:string|null; updated_at:string };

const statusLabels: Record<string,string> = {
  draft:"草稿", running:"运行中", paused:"已暂停", completed:"已完成",
  pending:"待处理", resolving:"解析中", resolved:"已解析", sending:"发送中",
  sent:"已发送待回复", success:"迁移成功", unreachable:"无法联系",
  restricted:"被限制", retry_wait:"待重试", failed:"失败", cancelled:"已取消",
};

function cardClass(status:string) {
  if (status === "success") return "text-emerald-300";
  if (["unreachable","restricted","failed"].includes(status)) return "text-rose-300";
  if (["retry_wait","pending"].includes(status)) return "text-amber-300";
  return "text-sky-300";
}

function MigrationContent({operator}:{operator:Operator}) {
  const [sources,setSources]=useState<Account[]>([]); const [targets,setTargets]=useState<Account[]>([]);
  const [source,setSource]=useState(""); const [target,setTarget]=useState("");
  const [candidates,setCandidates]=useState<Candidate[]>([]); const [selected,setSelected]=useState<Set<string>>(new Set());
  const [campaigns,setCampaigns]=useState<Campaign[]>([]); const [tasks,setTasks]=useState<MigrationTask[]>([]); const [activeCampaign,setActiveCampaign]=useState<string|null>(null);
  const [search,setSearch]=useState(""); const [activeDays,setActiveDays]=useState(""); const [name,setName]=useState(""); const [rate,setRate]=useState(5);
  const [message,setMessage]=useState("我的旧 Telegram 账号无法继续使用了，这是我的新账号。请回复这条消息，我会继续为你服务。");
  const [loading,setLoading]=useState(false); const [notice,setNotice]=useState("");

  const loadAccounts=useCallback(async()=>{ const data=await apiFetch<{source_accounts:Account[];target_accounts:Account[]}>("/telegram-user-migration/admin/accounts"); setSources(data.source_accounts);setTargets(data.target_accounts);},[]);
  const loadCampaigns=useCallback(async()=>{const data=await apiFetch<{items:Campaign[]}>("/telegram-user-migration/admin/campaigns");setCampaigns(data.items);},[]);
  useEffect(()=>{void loadAccounts();void loadCampaigns();const timer=setInterval(()=>void loadCampaigns(),10000);return()=>clearInterval(timer);},[loadAccounts,loadCampaigns]);

  async function loadCandidates(){if(!source)return;setLoading(true);try{const query=new URLSearchParams({source_account_id:source,limit:"5000"});if(search)query.set("search",search);if(activeDays)query.set("active_days",activeDays);const data=await apiFetch<{items:Candidate[]}>(`/telegram-user-migration/admin/candidates?${query}`);setCandidates(data.items);setSelected(new Set());}catch(e){setNotice(e instanceof Error?e.message:"加载失败");}finally{setLoading(false);}}
  async function createCampaign(){if(!source||!target||selected.size===0)return;setLoading(true);try{const result=await apiFetch<{id:string;tasks_created:number}>("/telegram-user-migration/admin/campaigns",{method:"POST",body:JSON.stringify({source_account_id:source,target_account_id:target,name:name||`迁移 ${new Date().toLocaleString()}`,intro_message:message,rate_per_minute:rate,user_ids:Array.from(selected),filters:{search,active_days:activeDays||null}})});setNotice(`已生成 ${result.tasks_created} 个限速迁移任务；检查后点击“启动”。`);await loadCampaigns();await loadTasks(result.id);}catch(e){setNotice(e instanceof Error?e.message:"创建失败");}finally{setLoading(false);}}
  async function action(id:string,actionName:"start"|"pause"){await apiFetch(`/telegram-user-migration/admin/campaigns/${id}/${actionName}`,{method:"POST",body:"{}"});await loadCampaigns();}
  async function loadTasks(id:string){setActiveCampaign(id);setTasks([]);try{const data=await apiFetch<{items:MigrationTask[]}>(`/telegram-user-migration/admin/campaigns/${id}/tasks`);setTasks(data.items);if(data.items.length===0)setNotice("该批次暂时没有用户任务。");}catch(e){setNotice(e instanceof Error?e.message:"迁移明细加载失败");}}
  async function retry(id:string){await apiFetch(`/telegram-user-migration/admin/tasks/${id}/retry`,{method:"POST",body:"{}"});if(activeCampaign)await loadTasks(activeCampaign);}
  const selectable=useMemo(()=>candidates.filter(x=>!x.already_migrating),[candidates]);

  return <AdminFrame operator={operator} active="migration" title="被封TG用户迁移" subtitle="独立迁移任务：保留原画像与历史，新账号收到回复后自动关联；迁移用户的视频顺序从视频11重新开始。">
    <div className="space-y-6 p-6">
      {notice&&<div className="rounded-lg border border-sky-800 bg-sky-950/50 p-3 text-sm text-sky-200">{notice}</div>}
      <section className="rounded-xl border border-amber-700/70 bg-amber-950/30 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h2 className="text-lg font-semibold text-amber-200">历史用户待确认 · 22,159人</h2><p className="mt-2 text-sm leading-6 text-amber-100/80">当前保留，不进入被封账号迁移名单。等后台账号完善、可用账号足够多后，再进入“公共召回池”重新联系用户。</p></div>
          <span className="rounded-full border border-amber-600 px-3 py-1 text-sm text-amber-200">暂停联系</span>
        </div>
        <p className="mt-3 border-t border-amber-800/60 pt-3 text-sm text-slate-300">召回规则：仅使用L2/L3/L4账号，按账号容量限速发送；不冒充原账号迁移。用户回复后再关联历史画像并重新核算视频顺序。</p>
      </section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">1. 选择账号和筛选用户</h2>
        <div className="grid gap-3 md:grid-cols-4"><select className="rounded bg-slate-950 p-2" value={source} onChange={e=>setSource(e.target.value)}><option value="">选择被封账号</option>{sources.map(a=><option key={a.id} value={a.id}>{a.display_name||a.phone} · {a.status}</option>)}</select><select className="rounded bg-slate-950 p-2" value={target} onChange={e=>setTarget(e.target.value)}><option value="">选择接管新账号（仅L2/L3/L4）</option>{targets.map(a=><option key={a.id} value={a.id}>{a.display_name||a.phone} · 接入{a.connection_days??"?"}天 · L{a.tier}</option>)}</select><input className="rounded bg-slate-950 p-2" placeholder="昵称 / Telegram ID" value={search} onChange={e=>setSearch(e.target.value)}/><select className="rounded bg-slate-950 p-2" value={activeDays} onChange={e=>setActiveDays(e.target.value)}><option value="">全部用户</option><option value="7">最近7天活跃</option><option value="30">最近30天活跃</option><option value="90">最近90天活跃</option></select></div>
        <button onClick={loadCandidates} disabled={!source||loading} className="mt-3 rounded bg-violet-600 px-4 py-2 disabled:opacity-40">筛选可迁移用户</button>
        {candidates.length>0&&<div className="mt-4 max-h-80 overflow-auto rounded border border-slate-800"><div className="sticky top-0 flex items-center gap-3 bg-slate-950 p-3"><input type="checkbox" checked={selectable.length>0&&selected.size===selectable.length} onChange={e=>setSelected(e.target.checked?new Set(selectable.map(x=>x.user_id)):new Set())}/><span>全选可迁移用户（已选 {selected.size} / {selectable.length}）</span></div>{candidates.map(u=><label key={u.user_id} className="flex items-center gap-3 border-t border-slate-800 p-3 text-sm"><input type="checkbox" disabled={u.already_migrating} checked={selected.has(u.user_id)} onChange={e=>setSelected(prev=>{const n=new Set(prev);if(e.target.checked){n.add(u.user_id);}else{n.delete(u.user_id);}return n;})}/><span className="w-48">{u.nickname||"未命名"}</span><span className="w-40 text-slate-400">{u.external_id}</span><span className="text-slate-500">{u.language||"未知语言"} · {u.risk_level||"无风险等级"}</span>{u.already_migrating&&<span className="ml-auto text-amber-300">已有迁移任务</span>}</label>)}</div>}
      </section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">2. 生成限速迁移任务</h2><div className="grid gap-3 md:grid-cols-3"><input className="rounded bg-slate-950 p-2" placeholder="迁移批次名称" value={name} onChange={e=>setName(e.target.value)}/><label className="text-sm">每分钟发送 <input type="number" min={1} max={30} className="ml-2 w-20 rounded bg-slate-950 p-2" value={rate} onChange={e=>setRate(Number(e.target.value))}/> 人</label><span className="text-sm text-slate-400">最多30人/分钟，失败自动退避重试3次</span></div><textarea className="mt-3 min-h-28 w-full rounded bg-slate-950 p-3" value={message} onChange={e=>setMessage(e.target.value)}/><button onClick={createCampaign} disabled={!source||!target||selected.size===0||loading} className="mt-3 rounded bg-emerald-600 px-4 py-2 disabled:opacity-40">生成迁移任务（暂不发送）</button></section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">3. 迁移批次与状态</h2><div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="p-2">批次</th><th>账号迁移</th><th>状态/限速</th><th>总数</th><th>已发送</th><th>成功</th><th>无法联系</th><th>被限制</th><th>待重试</th><th>操作</th></tr></thead><tbody>{campaigns.map(c=><tr key={c.id} className="border-t border-slate-800"><td className="p-2">{c.name}</td><td>{c.source_account} → {c.target_account}</td><td className={cardClass(c.status)}>{statusLabels[c.status]||c.status} · {c.rate_per_minute}/分</td><td>{c.total}</td><td className="text-sky-300">{c.sent}</td><td className="text-emerald-300">{c.success}</td><td className="text-rose-300">{c.unreachable}</td><td className="text-rose-300">{c.restricted}</td><td className="text-amber-300">{c.retry_wait}</td><td className="space-x-2"><button className="text-sky-300" onClick={()=>loadTasks(c.id)}>明细</button>{c.status==="draft"||c.status==="paused"?<button className="text-emerald-300" onClick={()=>action(c.id,"start")}>启动</button>:c.status==="running"?<button className="text-amber-300" onClick={()=>action(c.id,"pause")}>暂停</button>:null}</td></tr>)}</tbody></table></div></section>
      {activeCampaign&&<section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-4 text-lg font-semibold">4. 用户迁移明细</h2><div className="max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead><tr className="text-slate-400"><th className="p-2">用户</th><th>状态</th><th>尝试</th><th>已发送</th><th>已回复</th><th>原因</th><th>操作</th></tr></thead><tbody>{tasks.length===0?<tr><td colSpan={7} className="p-6 text-center text-slate-500">暂无迁移明细</td></tr>:tasks.map(t=><tr key={t.id} className="border-t border-slate-800"><td className="p-2">{t.nickname||"未命名"}<div className="text-xs text-slate-500">{t.external_id}</div></td><td className={cardClass(t.status)}>{statusLabels[t.status]||t.status}</td><td>{t.attempt_count}</td><td>{t.sent_at?new Date(t.sent_at).toLocaleString():"-"}</td><td>{t.replied_at?new Date(t.replied_at).toLocaleString():"-"}</td><td className="max-w-xs truncate text-slate-400">{t.failure_reason||"-"}</td><td>{["failed","unreachable","restricted","retry_wait"].includes(t.status)&&<button className="text-amber-300" onClick={()=>retry(t.id)}>重试</button>}</td></tr>)}</tbody></table></div></section>}
      <section className="overflow-hidden rounded-xl border border-sky-800/70 bg-slate-900">
        <div className="border-b border-slate-800 bg-gradient-to-r from-sky-950/70 to-slate-900 px-5 py-5">
          <h2 className="text-xl font-semibold text-sky-100">TG用户迁移分配与安全执行方案</h2>
          <p className="mt-2 text-sm leading-6 text-slate-300">当天受限账号一律不迁移；只有明确封禁的账号才作为迁移来源，并且只分配给当天健康、正常运行的TG账号。</p>
        </div>
        <div className="space-y-6 p-5 text-sm text-slate-300">
          <div>
            <h3 className="mb-3 text-base font-semibold text-white">1. 当前账号分配基准</h3>
            <div className="overflow-auto rounded-lg border border-slate-800"><table className="w-full min-w-[620px] text-left"><thead className="bg-slate-950 text-slate-400"><tr><th className="p-3">账号情况</th><th>数量</th><th>迁移角色</th><th>处理规则</th></tr></thead><tbody className="divide-y divide-slate-800"><tr><td className="p-3">健康、运行中</td><td className="font-semibold text-emerald-300">267</td><td>目标账号</td><td>通过当天健康检测后可接收迁移用户</td></tr><tr><td className="p-3">健康但已暂停</td><td>49</td><td>不参与</td><td>恢复正常运行前额度为0</td></tr><tr><td className="p-3">确认封禁</td><td className="text-rose-300">37</td><td>来源账号</td><td>保留原账号、Session、用户、画像和历史数据</td></tr><tr><td className="p-3">待复查</td><td className="text-amber-300">5</td><td>不参与</td><td>当天禁止迁移，等待下一次健康检测</td></tr></tbody></table></div>
            <p className="mt-2 text-xs text-slate-500">以上为方案制定时的当前核算基准；实际执行必须以当天实时健康状态为准。</p>
          </div>
          <div>
            <h3 className="mb-3 text-base font-semibold text-white">2. 按账号等级分配额度</h3>
            <div className="overflow-auto rounded-lg border border-slate-800"><table className="w-full min-w-[620px] text-left"><thead className="bg-slate-950 text-slate-400"><tr><th className="p-3">等级</th><th>当前可用账号</th><th>每小时上限</th><th>正式每日上限</th><th>第一阶段每日上限</th><th>最小间隔</th></tr></thead><tbody className="divide-y divide-slate-800"><tr><td className="p-3">T1</td><td>61</td><td>1人</td><td>10人</td><td className="text-emerald-300">3人</td><td>45–75分钟</td></tr><tr><td className="p-3">T2</td><td>157</td><td>2人</td><td>12人</td><td className="text-emerald-300">4人</td><td>25–45分钟</td></tr><tr><td className="p-3">T3</td><td>45</td><td>2人</td><td>14人</td><td className="text-emerald-300">5人</td><td>20–40分钟</td></tr><tr><td className="p-3">T4</td><td>4</td><td>3人</td><td>15人</td><td className="text-emerald-300">5人</td><td>15–30分钟</td></tr></tbody></table></div>
            <p className="mt-2 text-xs text-slate-500">理论正式容量为3,184人/天，不代表每天必须迁移这么多。第一阶段仅开放约30%容量，稳定运行3天且无集中限流后再逐步提升。</p>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4"><h3 className="font-semibold text-white">3. 允许执行时间</h3><p className="mt-3 leading-7">仅在北京时间 <span className="font-semibold text-sky-300">10:00–22:00</span> 执行。<span className="text-amber-300">17:30–18:30</span> 因18:00健康检测暂停迁移；TG运行服务重启后30分钟内也不执行。</p></div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4"><h3 className="font-semibold text-white">4. 用户分配顺序</h3><ol className="mt-3 list-decimal space-y-2 pl-5"><li>当天健康检测通过且正常运行。</li><li>当天没有任何限制或连续失败。</li><li>优先匹配用户国家、语言和平台。</li><li>当前小时和当天额度都未用完。</li><li>优先选择今日迁移量最少的账号，轮流均衡分配。</li></ol></div>
          </div>
          <div className="rounded-lg border border-rose-900/80 bg-rose-950/25 p-4">
            <h3 className="font-semibold text-rose-200">5. 当天受限立即禁止迁移</h3>
            <p className="mt-3 leading-7">TG账号出现 PeerFlood、FloodWait、Spam/Restricted、连续发送失败、会话断开、健康状态待复查，或发送结果无法确认时，该账号当天剩余迁移额度立即变为0。未发送任务可重新分配，已成功迁移的用户不得重复联系。</p>
          </div>
          <div className="rounded-lg border border-amber-800/80 bg-amber-950/25 p-4">
            <h3 className="font-semibold text-amber-200">6. 数据保留与失败处理</h3>
            <p className="mt-3 leading-7">迁移只重新分配用户归属和建立新联系，不转移Telegram原始聊天会话。被封账号、Session文件、用户资料、画像、历史消息和迁移记录全部保留。PeerIdInvalid、用户名失效、隐私限制或无法解析的用户进入待人工处理，不删除、不重复强制联系。</p>
          </div>
        </div>
      </section>
    </div>
  </AdminFrame>;
}

export default function TgUserMigrationPage(){return <AuthGate>{operator=><MigrationContent operator={operator}/>}</AuthGate>;}
