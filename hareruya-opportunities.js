const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const norm = (s) => String(s ?? "").normalize("NFKC").toLowerCase();
const money = (v, digits=2) => Number(v).toLocaleString("zh-CN",{maximumFractionDigits:digits});
const date = (s) => s ? new Date(s).toLocaleString("zh-CN",{hour12:false}) : "未核实";
const WATCH_KEY = "hareruya-mtg-watch-v1";
function saved() { try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")); } catch { return new Set(); } }
const state = {data:null,page:1,saved:saved()};
const reasons = {threshold:"CK 售价达到或超过晴屋收价",nmUnavailable:"CK NM 缺货 / 缺少 NM 报价",hareruyaUnavailable:"晴屋没有有效回收报价",hareruyaStale:"晴屋核价过期 / 采集失败",ckStale:"CK 核价过期 / 不可用",fxStale:"汇率过期 / 不可用",identityMissing:"具体印刷版本待核实",identityMismatch:"版本 / 语言 / 闪别不符",ambiguousCK:"CK 多版本无法区分",ambiguousHareruya:"晴屋多版本无法区分",notObserved:"未取得对应商品报价",specialFinish:"特殊工艺 / 序列号 / 签名待核实",numberMissing:"收藏编号未确认",setUnknown:"系列或特殊版本未确认"};

function fresh(s,hours) { const age=Date.now()-Date.parse(s);return Number.isFinite(age)&&age>=0&&age<=hours*3600000; }
function currentItems() {
  if(!state.data) return [];
  const m=state.data.meta;
  if(!fresh(m.fxAt,m.maxAgeHours.fx)) return [];
  return state.data.items.filter(r => r.language==="EN"&&r.condition==="NM"&&r.ckNmQty>0&&r.ckRetailUsd>0&&r.hareruyaBuyJpy>0&&r.ckRetailUsd*m.usdJpy<r.hareruyaBuyJpy&&fresh(r.ckCapturedAt,m.maxAgeHours.ck)&&fresh(r.hareruyaCapturedAt,m.maxAgeHours.hareruya));
}
function filteredItems() {
  const query=norm($("#opportunitySearch").value).split(/\s+/).filter(Boolean);
  return currentItems().filter(r => (!$("#opportunityFinish").value||r.finish===$("#opportunityFinish").value)&&(!$("#opportunitySet").value||r.set===$("#opportunitySet").value)&&r.spreadJpy>=Math.max(0,Number($("#minimumSpread").value)||0)&&r.spreadPct>=Math.max(0,Number($("#minimumPercent").value)||0)&&(!$("#opportunityWatched").checked||state.saved.has(`${r.productId}|EN`))&&query.every(q=>norm([r.name,r.cn,r.nameJa,r.set,r.collectorNumber,r.ckSku,r.hareruyaVariation].join(" ")).includes(q)))
    .sort((a,b)=>$("#opportunitySort").value==="percent"?b.spreadPct-a.spreadPct:$("#opportunitySort").value==="price"?a.ckRetailUsd-b.ckRetailUsd:b.spreadJpy-a.spreadJpy);
}
function url(value, hosts) { try {const u=new URL(value);return u.protocol==="https:"&&hosts.includes(u.hostname)?u.href:"#";} catch{return "#";} }
function rowMarkup(r) {
  const watch=`${r.productId}|EN`, watched=state.saved.has(watch);
  const image=url(r.image,["cards.scryfall.io"]);
  const ck=url(r.ckUrl,["www.cardkingdom.com"]), h=url(r.hareruyaUrl,["www.hareruyamtg.com"]);
  const cny=r.spreadJpy/state.data.meta.usdJpy*state.data.meta.usdCny;
  const thumbnail=image!=="#"?`<img src="${esc(image)}" alt="${esc(r.name)}" loading="lazy">`:"<span></span>";
  return `<tr><td><div class="rank-card">${thumbnail}<div><a href="${esc(ck)}" target="_blank" rel="noreferrer"><strong>${esc(r.name)}</strong></a>${r.cn?`<small>${esc(r.cn)}</small>`:""}<small>${esc(r.set)} #${esc(r.collectorNumber)} · EN · NM · ${r.finish==="foil"?"普通闪":"不闪"}<span class="opportunity-mobile-stock"> · NM ${r.ckNmQty} 张</span></small><small>CK ${esc(r.ckSku)} · 晴屋 ${esc(r.productId)}</small><small>CK ${esc(date(r.ckCapturedAt))}<br>晴屋 ${esc(date(r.hareruyaCapturedAt))}</small></div></div></td><td data-label="CK NM 售价"><a href="${esc(ck)}" target="_blank" rel="noreferrer">$${r.ckRetailUsd.toFixed(2)}</a><small>¥${money(r.ckRetailJpy)}</small></td><td data-label="晴屋回收 ¥"><a href="${esc(h)}" target="_blank" rel="noreferrer">${money(r.hareruyaBuyJpy,0)}</a></td><td data-label="价差 ¥"><strong class="spread-number">+${r.spreadJpy<0.01?"<0.01":money(r.spreadJpy)}</strong><small>CNY ${money(cny)}</small></td><td data-label="价差率"><strong class="spread-number">${r.spreadPct.toFixed(1)}%</strong></td><td>${r.ckNmQty} 张</td><td><button type="button" class="rank-star" data-watch="${esc(watch)}" title="${watched?"取消关注":"关注此版本"}" aria-label="${watched?"取消关注":"关注此版本"}">${watched?"★":"☆"}</button></td></tr>`;
}
function renderEvents() {
  const all=state.data.events||[], type=$("#eventFilter").value, events=all.filter(e=>!type||e.type===type);
  $("#eventCount").textContent=`（${all.length} 条）`;
  $("#opportunityEvents").innerHTML=events.length?events.slice(0,50).map(e=>`<div class="opportunity-event"><time>${esc(date(e.at))}</time><strong class="${e.type==="added"?"added":"removed"}">${e.type==="added"?"自动入榜":"自动移除"}</strong><div>${esc(e.name)}<small>${esc(e.version)}</small></div><div>${esc(e.reason)}</div></div>`).join(""):'<p class="rank-empty">尚无后续自动调整记录</p>';
}
function render() {
  if(!state.data) return;
  const rows=filteredItems(), all=currentItems(), pages=Math.max(1,Math.ceil(rows.length/25)), m=state.data.meta;
  state.page=Math.min(state.page,pages);
  $("#activeCount").textContent=all.length;
  $("#visibleCount").textContent=`${rows.length} 张符合当前筛选`;
  $("#opportunityRows").innerHTML=rows.slice((state.page-1)*25,state.page*25).map(rowMarkup).join("");
  $("#opportunityEmpty").hidden=rows.length>0;
  $("#opportunityPage").textContent=`${state.page} / ${pages}`;
  $("#previousOpportunities").disabled=state.page===1;$("#nextOpportunities").disabled=state.page>=pages;
  $("#builtAt").textContent=`榜单生成 ${date(m.generatedAt)}`;
  $("#membershipSummary").textContent=m.initialBaseline?"首次建榜 · 后续随报价自动增删":`最近更新：新增 ${m.lastRunAdded} · 移除 ${m.lastRunRemoved}`;
  $("#opportunityStatus").textContent=`同版本报价筛选 · 约每30分钟分批更新${m.status!=="ok"?" · 部分来源未更新":""}${all.length<m.items?" · 已隐藏过期报价":""}`;
  $("#ckQuoteTime").textContent=`CK 采集 ${date(m.ckCapturedAt)}`;
  $("#hareruyaQuoteTime").textContent=`晴屋批次 ${date(m.hareruyaDataAt)}`;
  $("#exchangeRate").textContent=`1 USD = ${money(m.usdJpy,6)} JPY · ${date(m.fxAt)}`;
  $("#excludedReasons").innerHTML=Object.entries(m.excluded||{}).sort((a,b)=>b[1]-a[1]).map(([reason,count])=>`<div><dt>${esc(reasons[reason]||reason)}</dt><dd>${money(count,0)}</dd></div>`).join("");
  renderEvents();
}
async function load() {
  $("#reloadOpportunities").disabled=true;
  try {
    const response=await fetch(`./hareruya_opportunities.json?v=${Date.now()}`,{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    if(!Array.isArray(data.items)||!data.meta?.maxAgeHours) throw new Error("报价格式不正确");
    state.data=data;
    const selected=$("#opportunitySet").value, sets=[...new Set(data.items.map(r=>r.set))].sort();
    $("#opportunitySet").replaceChildren(new Option("全部系列",""),...sets.map(s=>new Option(s,s)));
    $("#opportunitySet").value=sets.includes(selected)?selected:"";
    render();
  } catch(error) {render();$("#opportunityStatus").textContent=`暂未取得新榜单，旧结果仍按核价时间过期：${error.message}`;}
  finally {$("#reloadOpportunities").disabled=false;}
}
for(const id of ["opportunitySearch","opportunitySort","opportunityFinish","opportunitySet","minimumSpread","minimumPercent","opportunityWatched"]){$("#"+id).addEventListener("input",()=>{state.page=1;render();});}
$("#eventFilter").addEventListener("input",()=>{if(state.data)renderEvents();});
$("#reloadOpportunities").addEventListener("click",load);
$("#previousOpportunities").addEventListener("click",()=>{state.page=Math.max(1,state.page-1);render();});
$("#nextOpportunities").addEventListener("click",()=>{state.page++;render();});
$("#opportunityRows").addEventListener("click",event=>{const button=event.target.closest("[data-watch]");if(!button)return;const key=button.dataset.watch;state.saved.has(key)?state.saved.delete(key):state.saved.add(key);localStorage.setItem(WATCH_KEY,JSON.stringify([...state.saved]));render();});
$("#exportOpportunities").addEventListener("click",()=>{
  if(!state.data)return;
  const cell=v=>typeof v==="number"?String(v):'"'+String(/^[=+@-]/.test(String(v))?"'"+v:v??"").replaceAll('"','""')+'"';
  const rows=[["英文名","中文名","系列","编号","闪别","语言","品相","CK SKU","晴屋ID","CK售价USD","CK折合JPY","晴屋回收JPY","价差JPY","价差率%","NM库存","USDJPY","汇率时点","CK核价","晴屋核价","CK链接","晴屋链接"],...filteredItems().map(r=>[r.name,r.cn,r.set,r.collectorNumber,r.finish,r.language,r.condition,r.ckSku,r.productId,r.ckRetailUsd,r.ckRetailJpy,r.hareruyaBuyJpy,r.spreadJpy,r.spreadPct,r.ckNmQty,state.data.meta.usdJpy,state.data.meta.fxAt,r.ckCapturedAt,r.hareruyaCapturedAt,r.ckUrl,r.hareruyaUrl])];
  const href=URL.createObjectURL(new Blob(["\ufeff"+rows.map(r=>r.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=href;a.download="CK-晴屋英文NM价差榜.csv";a.click();setTimeout(()=>URL.revokeObjectURL(href),500);
});
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")load();});
setInterval(()=>{if(document.visibilityState==="visible")load();},120000);
if(matchMedia("(max-width: 640px)").matches) document.querySelector('[aria-current="page"]').scrollIntoView({block:"nearest",inline:"center"});
load();
