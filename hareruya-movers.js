const $ = (s) => document.querySelector(s);
const escapeText = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const normalize = (s) => String(s ?? "").normalize("NFKC").toLowerCase();
const money = (v) => Number(v).toLocaleString("ja-JP");
const time = (v) => v ? new Date(v).toLocaleString("zh-CN", {hour12:false}) : "尚未核价";
const WATCH_KEY = "hareruya-mtg-watch-v1";
function savedKeys() { try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")); } catch { return new Set(); } }
const initialPeriod = new URLSearchParams(location.search).get("period");
const state = { data: null, period: ["hour","day","threeDay","week"].includes(initialPeriod) ? initialPeriod : "day", pages: {rising:1,falling:1}, saved: savedKeys() };

function currentRows() {
  const metric = $("#metricSelect").value;
  const rows = state.data?.periods?.[state.period]?.[metric]?.items || [];
  const query = normalize($("#rankSearch").value).split(/\s+/).filter(Boolean);
  const language = $("#languageFilter").value;
  const set = $("#setFilter").value;
  const finish = $("#finishFilter").value;
  const amount = Math.max(0, Number($("#minDelta").value) || 0);
  const pct = Math.max(0, Number($("#minPct").value) || 0);
  return rows.filter((r) => {
    const c = state.data.cards[r.key];
    if (!c || (language && c.language !== language) || (set && c.set !== set)) return false;
    if (finish && c.foil !== (finish === "foil")) return false;
    if (Math.abs(r.deltaJpy) < amount || Math.abs(r.deltaPct) < pct) return false;
    if ($("#watchedOnly").checked && !state.saved.has(r.key)) return false;
    return query.every((q) => normalize([c.name,c.nameJa,c.set,c.collectorNumber,c.productId,c.variation,c.language].join(" ")).includes(q));
  }).sort((a,b) => $("#rankSort").value === "percent" ? Math.abs(b.deltaPct)-Math.abs(a.deltaPct) : Math.abs(b.deltaJpy)-Math.abs(a.deltaJpy));
}

function rowMarkup(r) {
  const c = state.data.cards[r.key];
  const name = c.name || c.nameJa || `晴屋 #${c.productId}`;
  const lang = c.language === "JP" ? "日文" : "英文";
  const finish = c.foil === true ? "闪卡" : c.foil === false ? "非闪" : "闪别未标注";
  const number = /^(?:\d[\da-zA-Z*-]*|[a-zA-Z]\d[\da-zA-Z*-]*)$/.test(String(c.collectorNumber || "")) ? `#${c.collectorNumber}` : "";
  const version = [c.set,number,lang,finish,`ID ${c.productId}`].filter(Boolean).join(" · ");
  const url = `https://www.hareruyamtg.com/ja/${$("#metricSelect").value === "buy" ? "purchase" : "products"}/detail/${encodeURIComponent(c.productId)}?lang=${encodeURIComponent(c.language)}`;
  const image = c.image?.startsWith("https://files.hareruyamtg.com/") ? `<img src="${escapeText(c.image)}" alt="${escapeText(name)}" loading="lazy">` : '<span></span>';
  const cls = r.deltaJpy > 0 ? "delta-up" : "delta-down";
  return `<tr><td><div class="rank-card">${image}<div><a href="${url}" target="_blank" rel="noreferrer"><strong>${escapeText(name)}</strong></a>${c.nameJa && c.nameJa !== name ? `<small>${escapeText(c.nameJa)}</small>` : ""}<small>${escapeText(version)}</small><small>${escapeText(time(r.previousAt))}<br>→ ${escapeText(time(r.currentAt))}</small></div></div></td><td data-label="前价 ¥">${money(r.previousJpy)}</td><td data-label="末价 ¥">${money(r.currentJpy)}</td><td data-label="变动 ¥" class="${cls}">${r.deltaJpy>0?"+":""}${money(r.deltaJpy)}</td><td data-label="幅度" class="${cls}">${r.deltaPct>0?"+":""}${r.deltaPct.toFixed(1)}%</td><td><button class="rank-star" data-watch="${escapeText(r.key)}" title="${state.saved.has(r.key)?"取消关注":"关注此版本"}" aria-label="${state.saved.has(r.key)?"取消关注":"关注此版本"}">${state.saved.has(r.key)?"★":"☆"}</button></td></tr>`;
}

function render() {
  if (!state.data) return;
  const rows = currentRows();
  const metric = $("#metricSelect").value;
  const label = metric === "buy" ? "回收价" : "NM 售价";
  $("h1").textContent = `晴屋${label}变动`;
  $(".rank-method").textContent = `${metric === "buy" ? "晴屋官网统一收价" : "晴屋官网 NM 售价，仅覆盖单独核验过的品相报价"} · 窗口内首次有效报价 → 末次有效报价 · 实际比较时间见每张牌。停收、缺价不计为降价。`;
  document.querySelectorAll("[data-period]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.period === state.period)));
  $("#comparisonCount").textContent = `${Number(state.data.periods[state.period][metric].comparable).toLocaleString("zh-CN")} 个版本已有窗口内有效对比 · 筛选后 ${rows.length} 个变动`;
  for (const side of ["rising","falling"]) {
    const group = rows.filter((r) => side === "rising" ? r.deltaJpy > 0 : r.deltaJpy < 0);
    const pages = Math.max(1,Math.ceil(group.length/25));
    state.pages[side] = Math.min(state.pages[side],pages);
    $("#"+side+"Title").textContent = label + (side === "rising" ? "上涨" : "下跌");
    $("#"+side+"Count").textContent = `${group.length} 张`;
    $("#"+side+"Rows").innerHTML = group.slice((state.pages[side]-1)*25,state.pages[side]*25).map(rowMarkup).join("");
    $("#"+side+"Empty").hidden = group.length>0;
    $("#"+side+"Page").textContent = `${state.pages[side]} / ${pages}`;
    document.querySelector(`[data-page="${side}"][data-step="-1"]`).disabled = state.pages[side]===1;
    document.querySelector(`[data-page="${side}"][data-step="1"]`).disabled = state.pages[side]>=pages;
  }
}

async function load() {
  $("#reloadRank").disabled = true;
  try {
    const response = await fetch(`./hareruya_movers.json?v=${Date.now()}`,{cache:"no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data.cards || !data.periods?.day?.buy) throw new Error("榜单格式不正确");
    state.data = data;
    $("#rankStatus").textContent = `晴屋官网统一报价 · 每30分钟分批核价 · 已保存 ${Number(data.meta.observations).toLocaleString("zh-CN")} 条核价记录`;
    $("#captureTime").textContent = `最近采集 ${time(data.meta.latestCaptureAt)}${data.meta.captureStatus === "partial" ? " · 部分采集失败" : ""}`;
    const selected = $("#setFilter").value;
    const sets = [...new Set(Object.values(data.cards).map((r)=>r.set).filter(Boolean))].sort();
    $("#setFilter").replaceChildren(new Option("全部系列",""),...sets.map((s)=>new Option(s,s)));
    $("#setFilter").value = sets.includes(selected) ? selected : "";
    render();
  } catch(error) { $("#rankStatus").textContent = `榜单暂不可用，保留已加载结果：${error.message}`; }
  finally { $("#reloadRank").disabled = false; }
}

document.querySelectorAll("[data-period]").forEach((b)=>b.addEventListener("click",()=>{
  state.period=b.dataset.period;state.pages={rising:1,falling:1};
  const url=new URL(location.href);url.searchParams.set("period",state.period);history.replaceState(null,"",url);render();
}));
["rankSearch","metricSelect","languageFilter","setFilter","finishFilter","minDelta","minPct","rankSort","watchedOnly"].forEach((id)=>$("#"+id).addEventListener("input",()=>{state.pages={rising:1,falling:1};render();}));
$("#reloadRank").addEventListener("click",load);
$(".rank-boards").addEventListener("click",(event)=>{
  const star=event.target.closest("[data-watch]");
  if(star){const key=star.dataset.watch;state.saved.has(key)?state.saved.delete(key):state.saved.add(key);localStorage.setItem(WATCH_KEY,JSON.stringify([...state.saved]));render();return;}
  const pager=event.target.closest("[data-page]");
  if(pager){state.pages[pager.dataset.page]=Math.max(1,state.pages[pager.dataset.page]+Number(pager.dataset.step));render();}
});
$("#exportRank").addEventListener("click",()=>{
  const cell=(s)=>typeof s === "number" ? String(s) : '"'+String(/^[=+@-]/.test(String(s))?"'"+s:s??"").replaceAll('"','""')+'"';
  const rows=[["牌名","日文牌名","晴屋商品ID","语言","系列","编号","闪别","价格类型","前价JPY","末价JPY","变动JPY","涨跌幅%","前次核价","末次核价"],...currentRows().map((r)=>{const c=state.data.cards[r.key];return[c.name,c.nameJa,c.productId,c.language,c.set,c.collectorNumber,c.foil===true?"foil":c.foil===false?"nonfoil":"",$("#metricSelect").value,r.previousJpy,r.currentJpy,r.deltaJpy,r.deltaPct,r.previousAt,r.currentAt];})];
  const url=URL.createObjectURL(new Blob(["\ufeff"+rows.map((r)=>r.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));
  const a=document.createElement("a");a.href=url;a.download="晴屋价格变动榜.csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
});
load();
