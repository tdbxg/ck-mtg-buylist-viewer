const els = {
  metaLine: document.querySelector("#metaLine"),
  itemCount: document.querySelector("#itemCount"),
  jpyRate: document.querySelector("#jpyRate"),
  updatedAt: document.querySelector("#updatedAt"),
  queryInput: document.querySelector("#queryInput"),
  languageSelect: document.querySelector("#languageSelect"),
  sortSelect: document.querySelector("#sortSelect"),
  cards: document.querySelector("#cards"),
  emptyState: document.querySelector("#emptyState"),
  template: document.querySelector("#cardTemplate"),
};

const state = { payload: null, query: "", language: "", sort: "buyDesc" };

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+/g, "");
}

function yen(value) {
  return value === null || value === undefined ? "-" : `¥${Number(value).toLocaleString("ja-JP")}`;
}

function cny(value) {
  if (value === null || value === undefined || !state.payload?.meta?.jpyCny) return "";
  return `¥${(Number(value) * state.payload.meta.jpyCny).toFixed(2)}`;
}

function conditionPrice(row, condition) {
  const price = row.sale?.[row.language]?.[condition];
  return `<div class="hareruya-price"><span>售价 ${condition}</span><strong>${yen(price)}</strong><small>${cny(price)}</small></div>`;
}

function renderCard(row) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const image = node.querySelector(".hareruya-image");
  image.src = row.image || "";
  image.alt = row.name || "";
  image.hidden = !row.image;
  node.querySelector("h2").textContent = row.name || row.nameJa || "未命名商品";
  node.querySelector(".badge").textContent = row.language === "JP" ? "日文" : row.language === "EN" ? "英文" : "其他";
  node.querySelector(".hareruya-subtitle").textContent = `${row.nameJa || row.name || "-"} · 晴屋 #${row.productId}`;
  node.querySelector(".hareruya-details").innerHTML = [
    `系列：<strong>${String(row.set || "-").toUpperCase()}${row.collectorNumber ? ` #${row.collectorNumber}` : ""}</strong>`,
    `晴屋语言：<strong>${row.language === "JP" ? "日文" : row.language === "EN" ? "英文" : row.language || "-"}</strong>`,
    `采集时间：${row.capturedAt || "-"}`,
  ].map(value => `<div>${value}</div>`).join("");
  const buy = row.buy?.[row.language] ?? null;
  node.querySelector(".hareruya-prices").innerHTML = [
    `<div class="hareruya-price buy"><span>晴屋收购</span><strong>${yen(buy)}</strong><small>${cny(buy)}</small></div>`,
    conditionPrice(row, "NM"),
    conditionPrice(row, "SP"),
    conditionPrice(row, "MP"),
    conditionPrice(row, "HP"),
  ].join("");
  node.querySelector(".hareruya-links").innerHTML = [
    row.saleUrl ? `<a href="${row.saleUrl}" target="_blank" rel="noreferrer">晴屋售价页</a>` : "",
    row.buyUrl ? `<a href="${row.buyUrl}" target="_blank" rel="noreferrer">晴屋收购页</a>` : "",
  ].join("");
  return node;
}

function render() {
  const query = normalize(state.query);
  const rows = (state.payload?.items || []).filter(row => {
    const search = normalize([row.name, row.nameJa, row.set, row.collectorNumber, row.productId].join(" "));
    return (!query || search.includes(query)) && (!state.language || row.language === state.language);
  }).sort((a, b) => {
    if (state.sort === "saleAsc") return (a.sale?.[a.language]?.NM ?? Infinity) - (b.sale?.[b.language]?.NM ?? Infinity);
    if (state.sort === "nameAsc") return (a.name || a.nameJa || "").localeCompare(b.name || b.nameJa || "");
    return (b.buy?.[b.language] || 0) - (a.buy?.[a.language] || 0);
  });
  els.cards.replaceChildren(...rows.map(renderCard));
  els.emptyState.hidden = rows.length > 0;
}

async function load() {
  const response = await fetch("./hareruya_prices.json?v=20260730-hareruyamtg", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.payload = await response.json();
  const meta = state.payload.meta || {};
  els.itemCount.textContent = Number(meta.items || state.payload.items?.length || 0).toLocaleString("zh-CN");
  els.jpyRate.textContent = meta.jpyCny ? Number(meta.jpyCny).toFixed(4) : "-";
  els.updatedAt.textContent = meta.generatedAt ? String(meta.generatedAt).replace("T", " ").slice(0, 16) : "-";
  els.metaLine.textContent = `晴屋公开商品页与收购页快照 · ${meta.generatedAt || "未更新"}`;
  render();
}

for (const element of [els.queryInput, els.languageSelect, els.sortSelect]) {
  element.addEventListener("input", () => { state.query = els.queryInput.value; state.language = els.languageSelect.value; state.sort = els.sortSelect.value; render(); });
  element.addEventListener("change", () => { state.query = els.queryInput.value; state.language = els.languageSelect.value; state.sort = els.sortSelect.value; render(); });
}

load().catch(error => {
  console.error(error);
  els.metaLine.textContent = "晴屋价格快照加载失败，请稍后刷新。";
});
