const els = {
  metaLine: document.querySelector("#metaLine"),
  itemCount: document.querySelector("#itemCount"),
  jpyRate: document.querySelector("#jpyRate"),
  updatedAt: document.querySelector("#updatedAt"),
  queryInput: document.querySelector("#queryInput"),
  languageSelect: document.querySelector("#languageSelect"),
  sortSelect: document.querySelector("#sortSelect"),
  rows: document.querySelector("#hareruyaRows"),
  resultCount: document.querySelector("#resultCount"),
  emptyState: document.querySelector("#emptyState"),
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function cleanCardName(value) {
  return String(value || "").replace(/^.*《/, "").replace(/》.*$/, "").trim();
}

function priceCell(value, buy = false) {
  return `<td class="hareruya-price-cell${buy ? " hareruya-buy" : ""}"><strong>${yen(value)}</strong>${value === null || value === undefined ? "" : `<small>${cny(value)}</small>`}</td>`;
}

function renderRow(row) {
  const name = cleanCardName(row.name || row.nameJa) || "未命名商品";
  const japaneseName = cleanCardName(row.nameJa);
  const marker = [row.set ? String(row.set).toUpperCase() : "", row.collectorNumber ? `#${row.collectorNumber}` : "", `晴屋 #${row.productId}`].filter(Boolean).join(" · ");
  const language = row.language === "JP" ? "日文" : row.language === "EN" ? "英文" : row.language || "其他";
  const sale = row.sale?.[row.language] || {};
  const buy = row.buy?.[row.language] ?? null;
  return `<tr>
    <td><div class="hareruya-name">${escapeHtml(name)}${japaneseName && japaneseName !== name ? `<small>${escapeHtml(japaneseName)}</small>` : ""}<small>${escapeHtml(marker)}</small></div></td>
    <td class="hareruya-language">${escapeHtml(language)}</td>
    ${priceCell(buy, true)}
    ${priceCell(sale.NM ?? null)}
    ${priceCell(sale.SP ?? null)}
    ${priceCell(sale.MP ?? null)}
    ${priceCell(sale.HP ?? null)}
    <td><div class="hareruya-source">${row.saleUrl ? `<a href="${escapeHtml(row.saleUrl)}" target="_blank" rel="noreferrer">售价</a>` : ""}${row.buyUrl ? `<a href="${escapeHtml(row.buyUrl)}" target="_blank" rel="noreferrer">收购</a>` : ""}</div></td>
  </tr>`;
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
  els.rows.innerHTML = rows.map(renderRow).join("");
  els.resultCount.textContent = `显示 ${rows.length.toLocaleString("zh-CN")} 条商品`;
  els.emptyState.hidden = rows.length > 0;
}

async function load() {
  const response = await fetch("./hareruya_prices.json?v=20260731-hareruyamtg-table", { cache: "no-store" });
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
