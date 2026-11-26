const PAGE_SIZE = 60;

const state = {
  payload: null,
  query: "",
  language: "",
  sort: "buyDesc",
  minBuy: 0,
  hotOnly: false,
  page: 1,
  results: [],
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  itemCount: document.querySelector("#itemCount"),
  hotCount: document.querySelector("#hotCount"),
  updatedAt: document.querySelector("#updatedAt"),
  searchInput: document.querySelector("#searchInput"),
  languageSelect: document.querySelector("#languageSelect"),
  sortSelect: document.querySelector("#sortSelect"),
  minBuyInput: document.querySelector("#minBuyInput"),
  hotOnly: document.querySelector("#hotOnly"),
  resultCount: document.querySelector("#resultCount"),
  pageLine: document.querySelector("#pageLine"),
  prevButton: document.querySelector("#prevButton"),
  nextButton: document.querySelector("#nextButton"),
  cardsGrid: document.querySelector("#cardsGrid"),
  emptyState: document.querySelector("#emptyState"),
  template: document.querySelector("#cardTemplate"),
};

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+/g, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[c]);
}

function yen(value) {
  return value === null || value === undefined ? "-" : `¥${Number(value).toLocaleString("ja-JP")}`;
}

async function ensurePako() {
  if (window.pako?.inflate) return;
  await new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "./pako_inflate.min.js?v=20260706-pako";
    s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  if (!window.pako?.inflate) throw new Error("本地 gzip 解压库未加载");
}

async function loadGzipJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  if ("DecompressionStream" in window && response.body) {
    try {
      const stream = response.clone().body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(stream).json();
    } catch (error) { console.warn("原生 gzip 解压失败，回退 pako", error); }
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return JSON.parse(new TextDecoder("utf-8").decode(bytes));
  await ensurePako();
  return JSON.parse(window.pako.inflate(bytes, { to: "string" }));
}

function readControls() {
  state.query = els.searchInput.value;
  state.language = els.languageSelect.value;
  state.sort = els.sortSelect.value;
  state.minBuy = Number(els.minBuyInput.value || 0);
  state.hotOnly = els.hotOnly.checked;
}

function filterRows() {
  const query = normalize(state.query);
  state.results = (state.payload?.items || []).filter((row) => {
    if (query && !normalize([row.name, row.nameJa].join(" ")).includes(query)) return false;
    if (state.language && row.language !== state.language) return false;
    if (Number(row.buyPriceJpy || 0) < state.minBuy) return false;
    if (state.hotOnly && !row.isHot) return false;
    return true;
  }).sort((a, b) => {
    if (state.sort === "buyAsc") return Number(a.buyPriceJpy || 0) - Number(b.buyPriceJpy || 0);
    if (state.sort === "nameAsc") return (a.name || "").localeCompare(b.name || "");
    return Number(b.buyPriceJpy || 0) - Number(a.buyPriceJpy || 0);
  });
  const pages = Math.max(1, Math.ceil(state.results.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
}

function renderCard(row) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  node.querySelector("h2").textContent = row.name || "";
  const badge = node.querySelector(".badge");
  badge.textContent = row.foil ? "闪卡" : "平卡";
  if (row.isHot) badge.classList.add("hot");
  node.querySelector(".cn").textContent = row.nameJa && row.nameJa !== row.name ? row.nameJa : "";
  const setLabel = String(row.set || "").toUpperCase();
  node.querySelector(".details").innerHTML = `
    <div>系列：<strong>${escapeHtml(setLabel)}</strong>${row.collectorNumber ? ` #${escapeHtml(row.collectorNumber)}` : ""} ｜ 语言：${escapeHtml(row.language || "")}</div>
    <div>Card Rush 系列码：${escapeHtml(row.packCode || "")}${row.displayCategory ? ` ｜ ${escapeHtml(row.displayCategory)}` : ""}</div>
  `;
  node.querySelector(".prices").innerHTML = `
    <div class="price ${row.isHot ? "hot-price" : ""}"><span>Card Rush 买取价</span><strong>${yen(row.buyPriceJpy)}</strong><span>${row.isHot ? "高价求购" : "普通买取"}</span></div>
  `;
  return node;
}

function render() {
  filterRows();
  const total = state.results.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const start = (state.page - 1) * PAGE_SIZE;
  const rows = state.results.slice(start, start + PAGE_SIZE);
  els.resultCount.textContent = total.toLocaleString("zh-CN");
  els.pageLine.textContent = `${state.page} / ${pages}`;
  els.prevButton.disabled = state.page <= 1;
  els.nextButton.disabled = state.page >= pages;
  els.emptyState.hidden = total > 0;
  els.cardsGrid.hidden = total === 0;
  const fragment = document.createDocumentFragment();
  rows.forEach((row) => fragment.appendChild(renderCard(row)));
  els.cardsGrid.replaceChildren(fragment);
}

function bindEvents() {
  const rerender = () => { state.page = 1; readControls(); render(); };
  [els.searchInput, els.languageSelect, els.sortSelect, els.minBuyInput].forEach((e) => e.addEventListener("input", rerender));
  els.hotOnly.addEventListener("change", rerender);
  els.prevButton.addEventListener("click", () => { state.page = Math.max(1, state.page - 1); render(); });
  els.nextButton.addEventListener("click", () => { state.page += 1; render(); });
}

async function init() {
  bindEvents();
  readControls();
  try {
    state.payload = await loadGzipJson("./cardrush_buylist_matched.json.gz");
    const meta = state.payload.meta || {};
    const items = state.payload.items || [];
    els.itemCount.textContent = Number(meta.matchedItems || items.length).toLocaleString("zh-CN");
    els.hotCount.textContent = items.filter((r) => r.isHot).length.toLocaleString("zh-CN");
    els.updatedAt.textContent = items[0]?.updatedAt ? new Date(items[0].updatedAt).toLocaleString("zh-CN", { hour12: false }) : "-";
    els.metaLine.textContent = `Card Rush 全量 ${Number(meta.rawItems || 0).toLocaleString("zh-CN")} 条，精确匹配 ${Number(meta.matchedItems || items.length).toLocaleString("zh-CN")} 条（同系列多印次无法唯一确定的不计入）`;
    render();
  } catch (error) {
    els.metaLine.textContent = `买取价加载失败：${error.message}`;
  }
}

init();
