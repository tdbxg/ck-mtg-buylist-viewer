const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const norm = (s) => String(s ?? "").normalize("NFKC").toLowerCase();
const money = (v,d=2) => Number(v).toLocaleString("zh-CN",{maximumFractionDigits:d});
const date = (s) => s?new Date(s).toLocaleString("zh-CN",{hour12:false}):"未核实";
const WATCH_KEY="hareruya-mtg-watch-v1", COST_KEY="hareruya-spread-cost-cny-v1";
function saved(){try{return new Set(JSON.parse(localStorage.getItem(WATCH_KEY)||"[]"));}catch{return new Set();}}
const state={data:null,catalog:[],catalogMap:new Map(),page:1,scope:"live",direction:"forward",saved:saved()};
const reasons={threshold:"CK 售价达到或超过晴屋收价",nmUnavailable:"CK NM 缺货 / 缺少 NM 报价",hareruyaUnavailable:"晴屋没有有效回收报价",hareruyaStale:"晴屋报价待更新 / 采集失败",ckStale:"CK 核价过期",fxStale:"汇率过期",identityMissing:"具体印刷版本待核实",identityMismatch:"版本 / 语言 / 闪别不符",ambiguousCK:"CK 多版本无法区分",ambiguousHareruya:"晴屋多版本无法区分",notObserved:"未取得对应商品报价",specialFinish:"特殊工艺 / 序列号 / 签名待核实",numberMissing:"收藏编号未确认",setUnknown:"系列或特殊版本未确认",ambiguousPrint:"同系列存在多种印刷，不能仅按牌名对齐"};
const finishes={foil:"普通闪",nonfoil:"不闪",special:"特殊工艺",unknown:"待核验"};
function fresh(s,h){const age=Date.now()-Date.parse(s);return Number.isFinite(age)&&age>=0&&age<=h*3600000;}
function searchText(r){return norm([r.name,r.cn,r.nameJa,r.set,r.collectorNumber,r.ckSku,r.productId,r.hareruyaVariation].join(" "));}
function currentFx(){return state.data&&fresh(state.data.meta.fxAt,state.data.meta.maxAgeHours.fx)&&state.data.meta.usdJpy>0;}
function currentCK(r){return fresh(r.ckCapturedAt,state.data.meta.maxAgeHours.ck);}
function forwardEligible(r,live){return r.matchStatus==="verified"&&r.language==="EN"&&r.condition==="NM"&&r.ckNmQty>0&&r.ckRetailUsd>0&&r.hareruyaBuyJpy>0&&r.buyAvailable&&r.ckRetailUsd*state.data.meta.usdJpy<r.hareruyaBuyJpy&&currentCK(r)&&(!live||(r.quoteStatus==="current"&&fresh(r.hareruyaCapturedAt,state.data.meta.maxAgeHours.hareruya)));}
function reverseEligible(r,live){return r.matchStatus==="verified"&&r.language==="EN"&&r.condition==="NM"&&r.hareruyaSaleJpy>0&&r.hareruyaNmQty>0&&r.ckCashUsd>0&&r.ckBuyingQty>0&&r.reverseBufferJpy>0&&currentCK(r)&&(!live||(r.reverseCurrent&&!r.saleCaptureError&&fresh(r.saleCapturedAt,state.data.meta.maxAgeHours.hareruya)));}
function currentItems(){
  if(!currentFx())return [];
  if(state.direction==="reverse"){const published=new Set(state.data.reverseItems.map(r=>r.key));return state.catalog.filter(r=>published.has(r.key)&&reverseEligible(r,true));}
  const published=new Set(state.data.items.map(r=>`${r.productId}|EN`));
  return state.catalog.filter(r=>published.has(r.key)&&forwardEligible(r,true));
}
function historicalItems(){
  if(!currentFx())return [];
  return state.catalog.filter(r=>state.direction==="reverse"?reverseEligible(r,false)&&!reverseEligible(r,true):forwardEligible(r,false)&&!forwardEligible(r,true));
}
function scopedItems(){return state.scope==="live"?currentItems():historicalItems();}
function values(r){
  const reverse=state.direction==="reverse",m=state.data.meta;
  const cost=reverse?r.hareruyaSaleJpy:r.ckRetailUsd*m.usdJpy;
  const proceeds=reverse?r.ckCashUsd*m.usdJpy:r.hareruyaBuyJpy;
  const cny=Math.max(0,Number($("#additionalCostCny").value)||0);
  const fee=cny>0?(m.usdCny>0?cny/m.usdCny*m.usdJpy:Infinity):0;
  return {cost,proceeds,fee,spread:proceeds-cost-fee,percent:(proceeds-cost-fee)/cost*100};
}
function filteredItems(){
  const query=norm($("#opportunitySearch").value).split(/\s+/).filter(Boolean);
  const min=Math.max(0,Number($("#minimumSpread").value)||0),pct=Math.max(0,Number($("#minimumPercent").value)||0);
  return scopedItems().filter(r=>{const v=values(r);return v.spread>0&&v.spread>=min&&v.percent>=pct&&(!$("#opportunityFinish").value||r.finish===$("#opportunityFinish").value)&&(!$("#opportunitySet").value||r.set===$("#opportunitySet").value)&&(!$("#opportunityWatched").checked||state.saved.has(r.key))&&query.every(q=>r._search.includes(q));})
    .sort((a,b)=>{const mode=$("#opportunitySort").value;return mode==="percent"?values(b).percent-values(a).percent:mode==="price"?values(a).cost-values(b).cost:mode==="coverage"?(b.observation?.observedDays||0)-(a.observation?.observedDays||0):mode==="floor"?(b.observation?.floorSpreadJpy??-Infinity)-(a.observation?.floorSpreadJpy??-Infinity):values(b).spread-values(a).spread;});
}
function url(v,hosts){try{const u=new URL(v);return u.protocol==="https:"&&hosts.includes(u.hostname)?u.href:"#";}catch{return "#";}}
function rowMarkup(r){
  const reverse=state.direction==="reverse",v=values(r),live=state.scope==="live",watched=state.saved.has(r.key);
  const ck=url(r.ckUrl,["www.cardkingdom.com"]),h=url(reverse?r.hareruyaSaleUrl:r.hareruyaUrl,["www.hareruyamtg.com"]);
  const image=url(r.image,["cards.scryfall.io","files.hareruyamtg.com"]);
  const thumb=image!=="#"?`<img src="${esc(image)}" alt="${esc(r.name)}" loading="lazy">`:'<span class="opportunity-no-image">无图</span>';
  const first=reverse?`<a href="${esc(h)}" target="_blank" rel="noreferrer">¥${money(r.hareruyaSaleJpy,0)}</a>`:`<a href="${esc(ck)}" target="_blank" rel="noreferrer">$${r.ckRetailUsd.toFixed(2)}</a><small>¥${money(v.cost)}</small>`;
  const second=reverse?`<a href="https://www.cardkingdom.com/purchasing/mtg_singles" target="_blank" rel="noreferrer">$${r.ckCashUsd.toFixed(2)}</a><small>¥${money(v.proceeds)}</small><small>70% 阈值 ¥${money(v.proceeds*0.7)}</small>`:`<a href="${esc(h)}" target="_blank" rel="noreferrer">¥${money(r.hareruyaBuyJpy,0)}</a>`;
  const qty=reverse?Math.min(r.hareruyaNmQty,r.ckBuyingQty):r.ckNmQty;
  const o=r.observation||{},observation=reverse?'<strong>CK 现金收价</strong><small>30天稳定性未确认</small>':`<strong>${o.observedDays||0} / 30 天</strong><small>${o.coverageComplete?"30日有核价覆盖":"样本不足30天"}${o.stopObserved?" · 含停收记录":""}</small>${o.minimumJpy!=null?`<small>已观察最低 ¥${money(o.minimumJpy,0)}</small>`:""}`;
  const proof=r.identityMethod==="uniqueScryfallPrint"?"编号经唯一印刷核验":"标题编号核验";
  const time=reverse?r.saleCapturedAt:r.hareruyaCapturedAt;
  return `<tr data-product="${esc(r.productId)}" data-direction="${state.direction}"><td><div class="rank-card">${thumb}<div><a href="${esc(reverse?h:ck)}" target="_blank" rel="noreferrer"><strong>${esc(r.name)}</strong></a>${r.cn||r.nameJa?`<small>${esc(r.cn||r.nameJa)}</small>`:""}<small>${esc(r.set)} #${esc(r.collectorNumber)} · EN · NM · ${esc(finishes[r.finish])}</small><span class="quote-state ${live?"current":"pending"}">${live?"最新核价候选":"历史参考 · 待核价"}</span><small>${proof} · CK ${esc(r.ckSku)} · 晴屋 ${esc(r.productId)}</small><small>CK ${esc(date(r.ckCapturedAt))}<br>晴屋${reverse?"售价":"收价"} ${esc(date(time))}</small><small class="opportunity-mobile-stock">可交易 ${qty} 张${reverse?` · 晴屋有 ${r.hareruyaNmQty} / CK 收 ${r.ckBuyingQty}`:""}</small></div></div></td><td data-label="${reverse?"晴屋 NM 售价":"CK NM 售价"}">${first}</td><td data-label="${reverse?"CK 现金回收":"晴屋回收"}">${second}</td><td data-label="费用后价差 ¥"><strong class="${live?"spread-number":"reference-number"}">+${money(v.spread)}</strong><small>CNY ${money(v.spread/state.data.meta.usdJpy*state.data.meta.usdCny)}</small><small>${v.fee>0?`已扣费用 ¥${money(v.fee)}`:"毛价差 · 未计附加费用"}</small></td><td data-label="价差率">${v.percent.toFixed(1)}%</td><td class="observation-cell" data-label="30日观察">${observation}</td><td>${qty} 张${reverse?`<small>晴屋有 ${r.hareruyaNmQty}<br>CK 收 ${r.ckBuyingQty}</small>`:""}</td><td><button type="button" class="rank-star" data-watch="${esc(r.key)}" aria-label="${watched?"取消关注":"关注此版本"}" title="${watched?"取消关注":"关注此版本"}">${watched?"★":"☆"}</button></td></tr>`;
}
function renderEvents(){
  const all=state.data.events||[],type=$("#eventFilter").value,events=all.filter(e=>!type||e.type===type);
  $("#eventCount").textContent=`（${all.length} 条 · CK买入方向）`;
  $("#opportunityEvents").innerHTML=events.length?events.slice(0,50).map(e=>`<div class="opportunity-event"><time>${esc(date(e.at))}</time><strong class="${e.type==="added"?"added":"removed"}">${e.type==="added"?"自动入榜":"自动移除"}</strong><div>${esc(e.name)}<small>${esc(e.version)}</small></div><div>${esc(e.reason)}</div></div>`).join(""):'<p class="rank-empty">尚无后续自动调整记录</p>';
}
function render(){
  if(!state.data)return;
  for(const option of $("#opportunitySort").options)if(["floor","coverage"].includes(option.value))option.disabled=state.direction==="reverse";
  if(state.direction==="reverse"&&["floor","coverage"].includes($("#opportunitySort").value))$("#opportunitySort").value="spread";
  const rows=filteredItems(),live=currentItems().filter(r=>values(r).spread>0),historical=historicalItems().filter(r=>values(r).spread>0),m=state.data.meta,reverse=state.direction==="reverse";
  const pages=Math.max(1,Math.ceil(rows.length/25));state.page=Math.min(state.page,pages);
  $("#activeCount").textContent=money(live.length,0);$("#scopeLiveCount").textContent=live.length;$("#scopeHistoryCount").textContent=historical.length;
  for(const b of document.querySelectorAll("[data-scope]"))b.setAttribute("aria-pressed",String(b.dataset.scope===state.scope));
  for(const b of document.querySelectorAll("[data-direction]"))if(b.tagName==="BUTTON")b.setAttribute("aria-pressed",String(b.dataset.direction===state.direction));
  $("#directionRule").textContent=reverse?"晴屋 EN / NM 售价 < CK 现金回收价折合日元 × 70%，且费用后价差为正":"CK EN / NM 售价折合日元 + 已填费用 < 晴屋英文 NM 回收价";
  $("#costHeading").textContent=reverse?"晴屋 NM 售价（日元）":"CK NM 售价";$("#buyHeading").textContent=reverse?"CK NM 现金回收":"晴屋 NM 回收（日元）";
  $("#visibleCount").textContent=`${money(rows.length,0)} 条正价差${state.scope==="history"?"历史参考":"候选"}`;
  $("#opportunityRows").innerHTML=rows.slice((state.page-1)*25,state.page*25).map(rowMarkup).join("");
  $("#opportunityEmpty").hidden=rows.length>0;$("#opportunityEmpty").textContent=reverse?"当前没有同时满足精确版本、EN/NM现货、CK现金回收额度及70%阈值的记录":"当前没有符合精确版本、EN/NM现货及费用后正价差条件的记录";
  $("#opportunityPage").textContent=`${state.page} / ${pages}`;$("#previousOpportunities").disabled=state.page===1;$("#nextOpportunities").disabled=state.page>=pages;
  $("#builtAt").textContent=`榜单生成 ${date(m.generatedAt)}`;$("#membershipSummary").textContent=`运输观察 30 天 · ${live.length} 条最新候选`;
  $("#opportunityStatus").textContent=`仅精确版本 · EN / NM · 有货 · ${m.status==="ok"?"按已发布报价筛选":"部分来源待更新"}`;
  $("#ckQuoteTime").textContent=`CK 采集 ${date(m.ckCapturedAt)}`;$("#hareruyaQuoteTime").textContent=`晴屋核验批次 ${date(m.hareruyaDataAt)}`;$("#exchangeRate").textContent=`1 USD = ${money(m.usdJpy,6)} JPY · ${date(m.fxAt)}`;
  const matched=state.catalog.filter(r=>r.matchStatus==="verified").length,stocked=state.catalog.filter(r=>r.hareruyaNmQty>0&&r.saleCapturedAt).length;
  $("#coverageSummary").textContent=`（全部 ${money(state.catalog.length,0)} 条英文记录，已对齐 ${money(matched,0)} 条）`;
  $("#reverseCoverage").textContent=`已取得英文 NM 正库存记录 ${money(stocked,0)} 条。未匹配、旧价及零库存记录仍保留在全量核验明细中，不作为当前盈利候选。`;
  const rotation=m.catalogRotation||{},coverage=m.catalog||{};
  $("#captureProgress").textContent=rotation.series?`英文系列轮换：${money(rotation.completedSeries,0)} / ${money(rotation.series,0)} 个分区完成首轮 · 本轮 ${money(rotation.lastRunPages,0)} 页 / ${money(rotation.lastRunRows,0)} 条报价 · 接续 ${rotation.nextSeries} 第 ${rotation.nextPage} 页${rotation.blockedUntil?` · 采集暂停至 ${date(rotation.blockedUntil)}`:""}`:"英文系列轮换待开始";
  const listMarkup=entries=>entries.map(([label,n])=>`<div><dt>${esc(label)}</dt><dd>${money(n,0)}</dd></div>`).join("");
  $("#identityReasons").innerHTML=listMarkup(Object.entries(coverage.identityReasons||{}).sort((a,b)=>b[1]-a[1]).map(([r,n])=>[r==="verified"?"已对齐精确印刷":reasons[r]||r,n]));
  $("#quoteCoverage").innerHTML=listMarkup([["24小时内已核价",coverage.current||0],["历史报价待更新",coverage.historical||0],["最近采集失败",coverage.failed||0],["缺少核价时间",coverage.unknown||0]]);
  $("#excludedReasons").innerHTML=Object.entries(m.excluded||{}).sort((a,b)=>b[1]-a[1]).map(([r,n])=>`<div><dt>${esc(reasons[r]||r)}</dt><dd>${money(n,0)}</dd></div>`).join("");renderEvents();
}
async function loadCatalog(path,at){
  if(path!=="hareruya_opportunity_catalog.json.gz")throw Error("全量报价路径不正确");
  const response=await fetch(`./${path}?v=${encodeURIComponent(at)}`,{cache:"no-store"});if(!response.ok)throw Error(`全量报价 HTTP ${response.status}`);
  if("DecompressionStream" in window&&response.body){try{return await new Response(response.clone().body.pipeThrough(new DecompressionStream("gzip"))).json();}catch{}}
  const b=new Uint8Array(await response.arrayBuffer());return JSON.parse(b[0]===0x1f&&b[1]===0x8b?window.pako.inflate(b,{to:"string"}):new TextDecoder().decode(b));
}
async function load(){
  if($("#reloadOpportunities").disabled)return;$("#reloadOpportunities").disabled=true;
  try{const response=await fetch(`./hareruya_opportunities.json?v=${Date.now()}`,{cache:"no-store"});if(!response.ok)throw Error(`HTTP ${response.status}`);const data=await response.json();
    if(!Array.isArray(data.items)||!Array.isArray(data.reverseItems)||!data.meta?.catalog)throw Error("双向报价数据尚未更新");
    if(state.data?.meta.generatedAt===data.meta.generatedAt){render();return;}
    const c=await loadCatalog(data.meta.catalog.path,data.meta.generatedAt);if(c.meta?.generatedAt!==data.meta.generatedAt||c.items?.length!==data.meta.screenedEnglish)throw Error("全量报价与榜单批次不一致");
    const prepared=c.items.map(r=>({...r,_search:searchText(r)}));state.data=data;state.catalog=prepared;state.catalogMap=new Map(prepared.map(r=>[r.key,r]));
    const selected=$("#opportunitySet").value,sets=[...new Set(prepared.filter(r=>r.matchStatus==="verified").map(r=>r.set))].sort();$("#opportunitySet").replaceChildren(new Option("全部系列",""),...sets.map(s=>new Option(s,s)));$("#opportunitySet").value=sets.includes(selected)?selected:"";render();
  }catch(e){render();$("#opportunityStatus").textContent=`暂未取得新榜单${state.data?"，保留上次完整报价":""}：${e.message}`;}finally{$("#reloadOpportunities").disabled=false;}
}
function download(rows,name){const cell=v=>typeof v==="number"?String(v):'"'+String(/^[=+@-]/.test(String(v))?"'"+v:v??"").replaceAll('"','""')+'"';const href=URL.createObjectURL(new Blob(["\ufeff"+rows.map(r=>r.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=href;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(href),500);}
$("#exportOpportunities").addEventListener("click",()=>{if(!state.data)return;download([["方向","英文名","系列","编号","闪别","CK SKU","晴屋ID","买入JPY","回收JPY","附加费用JPY","费用后价差JPY","价差率%","CK NM有货","晴屋NM有货","CK现金回收USD","CK回收额度","晴屋售价JPY","晴屋收价JPY","CK核价","晴屋售价核价","晴屋收价核价","核验方式","范围","CK链接","晴屋链接"],...filteredItems().map(r=>{const v=values(r);return[state.direction,r.name,r.set,r.collectorNumber,r.finish,r.ckSku,r.productId,v.cost,v.proceeds,v.fee,v.spread,v.percent,r.ckNmQty,r.hareruyaNmQty,r.ckCashUsd,r.ckBuyingQty,r.hareruyaSaleJpy,r.hareruyaBuyJpy,r.ckCapturedAt,r.saleCapturedAt,r.hareruyaCapturedAt,r.identityMethod,state.scope,r.ckUrl,state.direction==="reverse"?r.hareruyaSaleUrl:r.hareruyaUrl];})],"CK-晴屋双向正价差.csv");});
$("#exportAudit").addEventListener("click",()=>{if(!state.data)return;download([["晴屋ID","英文名","系列","编号","闪别","语言","匹配状态","报价状态","历史回收JPY","最后回收核价","NM售价JPY","NM库存","售价核价","CK SKU","CK NM售价USD","CK现金回收USD","CK回收额度","CK核价","晴屋原始版本标题","版本核验方式","Scryfall印刷ID","晴屋版本来源","Scryfall版本链接","CK商品链接"],...state.catalog.map(r=>[r.productId,r.name,r.set,r.collectorNumber,r.finish,r.language,r.matchStatus,r.quoteStatus,r.hareruyaBuyJpy,r.hareruyaCapturedAt,r.hareruyaSaleJpy,r.hareruyaNmQty,r.saleCapturedAt,r.ckSku,r.ckRetailUsd,r.ckCashUsd,r.ckBuyingQty,r.ckCapturedAt,r.hareruyaVariation,r.identityMethod,r.scryfallId,r.identitySource,r.scryfallUrl,r.ckUrl])],"晴屋全部英文核验明细.csv");});
let timer;$("#opportunitySearch").addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(()=>{state.page=1;render();},150);});
for(const id of["opportunitySort","opportunityFinish","opportunitySet","minimumSpread","minimumPercent","opportunityWatched","additionalCostCny"])$("#"+id).addEventListener("input",()=>{if(id==="additionalCostCny")try{localStorage.setItem(COST_KEY,String(Math.max(0,Number($("#additionalCostCny").value)||0)));}catch{}state.page=1;render();});
for(const b of document.querySelectorAll("[data-scope]"))b.addEventListener("click",()=>{state.scope=b.dataset.scope;state.page=1;render();});
for(const b of document.querySelectorAll("[data-direction]"))b.addEventListener("click",()=>{state.direction=b.dataset.direction;state.scope="live";state.page=1;render();});
$("#eventFilter").addEventListener("input",()=>{if(state.data)renderEvents();});$("#reloadOpportunities").addEventListener("click",load);
$("#previousOpportunities").addEventListener("click",()=>{state.page=Math.max(1,state.page-1);render();});$("#nextOpportunities").addEventListener("click",()=>{state.page++;render();});
$("#opportunityRows").addEventListener("click",e=>{const b=e.target.closest("[data-watch]");if(!b)return;state.saved.has(b.dataset.watch)?state.saved.delete(b.dataset.watch):state.saved.add(b.dataset.watch);localStorage.setItem(WATCH_KEY,JSON.stringify([...state.saved]));render();});
$("#opportunityRows").addEventListener("error",e=>{if(e.target.tagName!=="IMG")return;const p=document.createElement("span");p.className="opportunity-no-image";p.textContent="无缩略图";e.target.replaceWith(p);},true);
try{$("#additionalCostCny").value=String(Math.max(0,Number(localStorage.getItem(COST_KEY))||0));}catch{}
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")load();});setInterval(()=>{if(document.visibilityState==="visible")load();},120000);
if(matchMedia("(max-width: 640px)").matches)document.querySelector('[aria-current="page"]').scrollIntoView({block:"nearest",inline:"center"});load();
