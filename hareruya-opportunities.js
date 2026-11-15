const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const norm = (s) => String(s ?? "").normalize("NFKC").toLowerCase();
const money = (v, digits=2) => Number(v).toLocaleString("zh-CN",{maximumFractionDigits:digits});
const date = (s) => s ? new Date(s).toLocaleString("zh-CN",{hour12:false}) : "未核实";
const WATCH_KEY = "hareruya-mtg-watch-v1";
function saved() { try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")); } catch { return new Set(); } }
const state = {data:null,catalog:[],catalogMap:new Map(),page:1,scope:"all",saved:saved()};
const reasons = {threshold:"CK 售价达到或超过晴屋收价",nmUnavailable:"CK NM 缺货 / 缺少 NM 报价",hareruyaUnavailable:"晴屋没有有效回收报价",hareruyaStale:"晴屋报价待更新 / 采集失败",ckStale:"CK 核价过期 / 不可用",fxStale:"汇率过期 / 不可用",identityMissing:"具体印刷版本待核实",identityMismatch:"版本 / 语言 / 闪别不符",ambiguousCK:"CK 多版本无法区分",ambiguousHareruya:"晴屋多版本无法区分",notObserved:"未取得对应商品报价",specialFinish:"特殊工艺 / 序列号 / 签名待核实",numberMissing:"收藏编号未确认",setUnknown:"系列或特殊版本未确认"};
const finishes = {foil:"普通闪",nonfoil:"不闪",special:"特殊工艺待核验",unknown:"闪别待核验"};

function fresh(s,hours) { const age=Date.now()-Date.parse(s);return Number.isFinite(age)&&age>=0&&age<=hours*3600000; }
function quoteStatus(r) { return r.quoteStatus==="current"&&!fresh(r.hareruyaCapturedAt,state.data.meta.maxAgeHours.hareruya)?"historical":r.quoteStatus; }
function currentComparison(r) {
  const m=state.data.meta;
  return r.matchStatus==="verified"&&r.ckNmQty>0&&r.ckRetailUsd>0&&r.hareruyaBuyJpy>0&&r.buyAvailable&&quoteStatus(r)==="current"&&fresh(r.ckCapturedAt,m.maxAgeHours.ck)&&fresh(m.fxAt,m.maxAgeHours.fx);
}
function searchText(r) { return norm([r.name,r.cn,r.nameJa,r.set,r.collectorNumber,r.ckSku,r.productId,r.hareruyaVariation].join(" ")); }
function currentItems() {
  if(!state.data||!fresh(state.data.meta.fxAt,state.data.meta.maxAgeHours.fx)) return [];
  const m=state.data.meta;
  return state.data.items.filter(r=>r.language==="EN"&&r.condition==="NM"&&r.ckNmQty>0&&r.ckRetailUsd>0&&r.hareruyaBuyJpy>0&&r.ckRetailUsd*m.usdJpy<r.hareruyaBuyJpy&&fresh(r.ckCapturedAt,m.maxAgeHours.ck)&&fresh(r.hareruyaCapturedAt,m.maxAgeHours.hareruya))
    .map(r=>{const c=state.catalogMap.get(`${r.productId}|EN`);return {...c,...r,_search:c?._search||searchText(r),matchStatus:"verified",quoteStatus:"current",buyAvailable:true};});
}
function scopedItems() {
  if(state.scope==="live") return currentItems();
  if(state.scope==="history") return state.catalog.filter(r=>quoteStatus(r)!=="current");
  if(state.scope==="unmatched") return state.catalog.filter(r=>r.matchStatus!=="verified");
  return state.catalog;
}
function compareNullable(a,b,ascending=false) {
  if(a==null) return b==null?0:1;
  if(b==null) return -1;
  return ascending?a-b:b-a;
}
function filteredItems() {
  const query=norm($("#opportunitySearch").value).split(/\s+/).filter(Boolean);
  const spread=Math.max(0,Number($("#minimumSpread").value)||0), percent=Math.max(0,Number($("#minimumPercent").value)||0);
  return scopedItems().filter(r=>(!$("#opportunityFinish").value||r.finish===$("#opportunityFinish").value)&&(!$("#opportunitySet").value||r.set===$("#opportunitySet").value)&&(!spread||(r.spreadJpy!=null&&r.spreadJpy>=spread))&&(!percent||(r.spreadPct!=null&&r.spreadPct>=percent))&&(!$("#positiveSpreadOnly").checked||r.spreadJpy>0)&&(!$("#opportunityWatched").checked||state.saved.has(`${r.productId}|EN`))&&query.every(q=>r._search.includes(q)))
    .sort((a,b)=>{const mode=$("#opportunitySort").value;return mode==="percent"?compareNullable(a.spreadPct,b.spreadPct):mode==="price"?compareNullable(a.ckRetailUsd,b.ckRetailUsd,true):mode==="buy"?compareNullable(a.hareruyaBuyJpy,b.hareruyaBuyJpy):mode==="floor"?compareNullable(a.observation?.floorSpreadJpy,b.observation?.floorSpreadJpy):mode==="coverage"?(b.observation?.observedDays||0)-(a.observation?.observedDays||0):compareNullable(a.spreadJpy,b.spreadJpy);});
}
function url(value, hosts) { try {const u=new URL(value);return u.protocol==="https:"&&hosts.includes(u.hostname)?u.href:"#";} catch{return "#";} }
function signed(v) { return `${v>0?"+":""}${money(v)}`; }
function rowMarkup(r) {
  const watch=`${r.productId}|EN`, watched=state.saved.has(watch), status=quoteStatus(r), current=currentComparison(r);
  const image=url(r.image,["cards.scryfall.io","files.hareruyamtg.com"]);
  const ck=url(r.ckUrl,["www.cardkingdom.com"]), h=url(r.hareruyaUrl,["www.hareruyamtg.com"]);
  const ckSearch=`https://www.cardkingdom.com/catalog/search?search=header&filter%5Bname%5D=${encodeURIComponent(r.name)}`;
  const thumbnail=image!=="#"?`<img src="${esc(image)}" alt="${esc(r.name)}" loading="lazy">`:'<span class="opportunity-no-image">无图</span>';
  const label=status==="current"?"最新核验":status==="failed"?"采集失败 · 保留旧价":status==="historical"?"历史报价 · 待更新":"报价时间待核验";
  const qty=r.ckNmQty==null?"未匹配":`${r.ckNmQty} 张`;
  const quote=r.hareruyaBuyJpy==null?"未记录":money(r.hareruyaBuyJpy,0);
  const price=r.ckRetailUsd==null?`<span>待核验</span><small><a href="${esc(ckSearch)}" target="_blank" rel="noreferrer">查 CK 版本</a></small>`:`<a href="${esc(ck)}" target="_blank" rel="noreferrer">$${r.ckRetailUsd.toFixed(2)}</a>${r.ckRetailJpy!=null?`<small>¥${money(r.ckRetailJpy)}</small>`:""}`;
  const spread=r.spreadJpy==null?"待匹配":`<strong class="${current&&r.spreadJpy>0?"spread-number":"reference-number"}">${signed(r.spreadJpy)}</strong><small>${current?"最新核验价差":"参考值 · 非当前可兑现"}</small>`;
  const percent=r.spreadPct==null?"—":`${r.spreadPct.toFixed(1)}%`;
  const o=r.observation||{observedDays:0,coverageComplete:false,minimumJpy:null};
  const observation=`<strong>${o.observedDays} / 30 天</strong><small>${o.coverageComplete?"30日有核价覆盖":"样本不足30天"}${o.stopObserved?" · 含停收记录":""}</small>${o.minimumJpy!=null?`<small>已观察最低 ¥${money(o.minimumJpy,0)}</small>`:""}`;
  const match=r.matchStatus!=="verified"?`<small class="opportunity-match-warning">${esc(reasons[r.matchStatus]||"版本待匹配")}</small>`:"";
  return `<tr data-product="${esc(r.productId)}" data-quote-status="${esc(status)}"><td><div class="rank-card">${thumbnail}<div><a href="${esc(ck!=="#"?ck:h)}" target="_blank" rel="noreferrer"><strong>${esc(r.name)}</strong></a>${r.cn||r.nameJa?`<small>${esc(r.cn||r.nameJa)}</small>`:""}<small>${esc(r.set||"系列待核验")} ${r.collectorNumber?`#${esc(r.collectorNumber)}`:"· 编号待核验"} · EN · NM · ${esc(finishes[r.finish]||finishes.unknown)}<span class="opportunity-mobile-stock"> · NM ${esc(qty)}</span></small><span class="quote-state ${status==="current"?"current":"pending"}">${esc(label)}</span>${match}<small>${r.ckSku?`CK ${esc(r.ckSku)} · `:""}晴屋 ${esc(r.productId)}</small><small>${r.ckCapturedAt?`CK ${esc(date(r.ckCapturedAt))}${!fresh(r.ckCapturedAt,state.data.meta.maxAgeHours.ck)?" · 待更新":""}<br>`:""}晴屋最后核价 ${esc(date(r.hareruyaCapturedAt))}</small></div></div></td><td data-label="CK NM 售价">${price}</td><td data-label="晴屋回收 ¥"><a href="${esc(h)}" target="_blank" rel="noreferrer">${quote}</a>${!r.buyAvailable?"<small>最近记录未收购</small>":""}</td><td data-label="参考价差 ¥">${spread}</td><td data-label="参考价差率">${percent}</td><td class="observation-cell" data-label="30日观察">${observation}</td><td>${esc(qty)}</td><td><button type="button" class="rank-star" data-watch="${esc(watch)}" title="${watched?"取消关注":"关注此版本"}" aria-label="${watched?"取消关注":"关注此版本"}">${watched?"★":"☆"}</button></td></tr>`;
}
function renderEvents() {
  const all=state.data.events||[], type=$("#eventFilter").value, events=all.filter(e=>!type||e.type===type);
  $("#eventCount").textContent=`（${all.length} 条）`;
  $("#opportunityEvents").innerHTML=events.length?events.slice(0,50).map(e=>`<div class="opportunity-event"><time>${esc(date(e.at))}</time><strong class="${e.type==="added"?"added":"removed"}">${e.type==="added"?"自动入榜":"自动移除"}</strong><div>${esc(e.name)}<small>${esc(e.version)}</small></div><div>${esc(e.reason)}</div></div>`).join(""):'<p class="rank-empty">尚无后续自动调整记录</p>';
}
function render() {
  if(!state.data) return;
  const rows=filteredItems(), live=currentItems(), pages=Math.max(1,Math.ceil(rows.length/25)), m=state.data.meta;
  state.page=Math.min(state.page,pages);
  $("#activeCount").textContent=money(state.catalog.length,0);
  $("#scopeAllCount").textContent=money(state.catalog.length,0);
  $("#scopeLiveCount").textContent=live.length;
  $("#scopeHistoryCount").textContent=money(state.catalog.filter(r=>quoteStatus(r)!=="current").length,0);
  $("#scopeUnmatchedCount").textContent=money(state.catalog.filter(r=>r.matchStatus!=="verified").length,0);
  for(const button of document.querySelectorAll("[data-scope]")) button.setAttribute("aria-pressed",String(button.dataset.scope===state.scope));
  $("#visibleCount").textContent=`${money(rows.length,0)} 条符合当前筛选`;
  $("#opportunityRows").innerHTML=rows.slice((state.page-1)*25,state.page*25).map(rowMarkup).join("");
  $("#opportunityEmpty").hidden=rows.length>0;
  $("#opportunityPage").textContent=`${state.page} / ${pages}`;
  $("#previousOpportunities").disabled=state.page===1;$("#nextOpportunities").disabled=state.page>=pages;
  $("#builtAt").textContent=`榜单生成 ${date(m.generatedAt)}`;
  $("#membershipSummary").textContent=`运输观察 30 天 · 实时价差 ${live.length} 条`;
  $("#opportunityStatus").textContent=`全部英文记录 ${money(state.catalog.length,0)} 条 · 含历史报价${m.status!=="ok"?" · 部分来源未更新":""}`;
  $("#ckQuoteTime").textContent=`CK 采集 ${date(m.ckCapturedAt)}`;
  $("#hareruyaQuoteTime").textContent=`晴屋采集批次 ${date(m.hareruyaDataAt)}`;
  $("#exchangeRate").textContent=`1 USD = ${money(m.usdJpy,6)} JPY · ${date(m.fxAt)}`;
  $("#excludedReasons").innerHTML=Object.entries(m.excluded||{}).sort((a,b)=>b[1]-a[1]).map(([reason,count])=>`<div><dt>${esc(reasons[reason]||reason)}</dt><dd>${money(count,0)}</dd></div>`).join("");
  renderEvents();
}
async function loadCatalog(path,generatedAt) {
  if(path!=="hareruya_opportunity_catalog.json.gz") throw new Error("全量报价路径不正确");
  const response=await fetch(`./${path}?v=${encodeURIComponent(generatedAt)}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`全量报价 HTTP ${response.status}`);
  if("DecompressionStream" in window&&response.body) {
    try{return await new Response(response.clone().body.pipeThrough(new DecompressionStream("gzip"))).json();}catch{}
  }
  const bytes=new Uint8Array(await response.arrayBuffer());
  return JSON.parse(bytes[0]===0x1f&&bytes[1]===0x8b?window.pako.inflate(bytes,{to:"string"}):new TextDecoder().decode(bytes));
}
async function load() {
  if($("#reloadOpportunities").disabled) return;
  $("#reloadOpportunities").disabled=true;
  try {
    const response=await fetch(`./hareruya_opportunities.json?v=${Date.now()}`,{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    if(!Array.isArray(data.items)||!data.meta?.catalog) throw new Error("全量报价格式尚未更新");
    if(state.data?.meta.generatedAt===data.meta.generatedAt){render();return;}
    const catalog=await loadCatalog(data.meta.catalog.path,data.meta.generatedAt);
    if(!Array.isArray(catalog.items)||catalog.meta?.generatedAt!==data.meta.generatedAt||catalog.items.length!==data.meta.screenedEnglish) throw new Error("全量报价与榜单批次不一致，请稍后刷新");
    const prepared=catalog.items.map(r=>({...r,_search:searchText(r)}));
    state.data=data;state.catalog=prepared;state.catalogMap=new Map(prepared.map(r=>[r.key,r]));
    const selected=$("#opportunitySet").value, sets=[...new Set(prepared.map(r=>r.set).filter(Boolean))].sort();
    $("#opportunitySet").replaceChildren(new Option("全部系列",""),...sets.map(s=>new Option(s,s)));
    $("#opportunitySet").value=sets.includes(selected)?selected:"";
    render();
  } catch(error) {render();$("#opportunityStatus").textContent=`暂未取得新榜单${state.data?"，保留上次完整报价":""}：${error.message}`;}
  finally {$("#reloadOpportunities").disabled=false;}
}
let searchTimer;
$("#opportunitySearch").addEventListener("input",()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;render();},150);});
for(const id of ["opportunitySort","opportunityFinish","opportunitySet","minimumSpread","minimumPercent","opportunityWatched","positiveSpreadOnly"]){$("#"+id).addEventListener("input",()=>{state.page=1;render();});}
for(const button of document.querySelectorAll("[data-scope]")) button.addEventListener("click",()=>{state.scope=button.dataset.scope;state.page=1;render();});
$("#eventFilter").addEventListener("input",()=>{if(state.data)renderEvents();});
$("#reloadOpportunities").addEventListener("click",load);
$("#previousOpportunities").addEventListener("click",()=>{state.page=Math.max(1,state.page-1);render();});
$("#nextOpportunities").addEventListener("click",()=>{state.page++;render();});
$("#opportunityRows").addEventListener("click",event=>{const button=event.target.closest("[data-watch]");if(!button)return;const key=button.dataset.watch;state.saved.has(key)?state.saved.delete(key):state.saved.add(key);localStorage.setItem(WATCH_KEY,JSON.stringify([...state.saved]));render();});
$("#opportunityRows").addEventListener("error",event=>{if(event.target.tagName!=="IMG")return;const placeholder=document.createElement("span");placeholder.className="opportunity-no-image";placeholder.textContent="无缩略图";event.target.replaceWith(placeholder);},true);
$("#exportOpportunities").addEventListener("click",()=>{
  if(!state.data)return;
  const cell=v=>typeof v==="number"?String(v):'"'+String(/^[=+@-]/.test(String(v))?"'"+v:v??"").replaceAll('"','""')+'"';
  const rows=[["英文名","中文名","系列","编号","闪别","语言","品相","CK SKU","晴屋ID","CK售价USD","CK折合JPY","晴屋回收JPY(含历史)","参考价差JPY","参考价差率%","NM库存","USDJPY","汇率时点","CK核价","晴屋最后核价","晴屋报价状态","版本匹配状态","当前可比","30日核价天数","30日已观察最低收价JPY","30日含停收记录","CK链接","晴屋链接"],...filteredItems().map(r=>[r.name,r.cn||r.nameJa,r.set,r.collectorNumber,finishes[r.finish],r.language,r.condition,r.ckSku,r.productId,r.ckRetailUsd,r.ckRetailJpy,r.hareruyaBuyJpy,r.spreadJpy,r.spreadPct,r.ckNmQty,state.data.meta.usdJpy,state.data.meta.fxAt,r.ckCapturedAt,r.hareruyaCapturedAt,quoteStatus(r),r.matchStatus,currentComparison(r)?"是":"否",r.observation?.observedDays??0,r.observation?.minimumJpy,r.observation?.stopObserved?"是":"否",r.ckUrl,r.hareruyaUrl])];
  const href=URL.createObjectURL(new Blob(["\ufeff"+rows.map(r=>r.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=href;a.download="CK-晴屋英文报价搜寻.csv";a.click();setTimeout(()=>URL.revokeObjectURL(href),500);
});
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")load();});
setInterval(()=>{if(document.visibilityState==="visible")load();},120000);
if(matchMedia("(max-width: 640px)").matches) document.querySelector('[aria-current="page"]').scrollIntoView({block:"nearest",inline:"center"});
load();
