const PAGE_SIZE = 60;
const RARE_SET = ["rare", "mythic", "special"];

const state = {
  payload: null,
  query: "",
  printQuery: "",
  language: "",
  category: "",
  rarity: "",
  set: "",
  minBuy: 0,
  sort: "buyDesc",
  foilOnly: false,
  withImageOnly: false,
  hotOnly: false,
  bothOnly: true,
  rareOnly: false,
  page: 1,
  results: [],
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  itemCount: document.querySelector("#itemCount"),
  hotCount: document.querySelector("#hotCount"),
  updatedAt: document.querySelector("#updatedAt"),
  searchInput: document.querySelector("#searchInput"),
  printSearchInput: document.querySelector("#printSearchInput"),
  languageSelect: document.querySelector("#languageSelect"),
  categorySelect: document.querySelector("#categorySelect"),
  raritySelect: document.querySelector("#raritySelect"),
  setSelect: document.querySelector("#setSelect"),
  minBuyInput: document.querySelector("#minBuyInput"),
  sortSelect: document.querySelector("#sortSelect"),
  foilOnly: document.querySelector("#foilOnly"),
  withImageOnly: document.querySelector("#withImageOnly"),
  hotOnly: document.querySelector("#hotOnly"),
  bothOnly: document.querySelector("#bothOnly"),
  rareOnly: document.querySelector("#rareOnly"),
  resetButton: document.querySelector("#resetButton"),
  filterSummary: document.querySelector("#filterSummary"),
  recentSetChips: document.querySelector("#recentSetChips"),
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

function rarityLabel(value) {
  return { common: "普通", uncommon: "非普通", rare: "稀有", mythic: "秘稀", special: "特殊" }[value] || value || "";
}

function categoryLabel(value) {
  return {
    "パイオニア以下": "先驱及以下",
    "foil系": "闪卡类",
    "スタンダード": "标准",
    "高額系": "高价值",
    "モダン以下最新弾": "现代及以下最新系列",
    "スタンダード最新弾": "标准最新系列",
  }[value] || value || "";
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
  state.printQuery = els.printSearchInput.value;
  state.language = els.languageSelect.value;
  state.category = els.categorySelect.value;
  state.rarity = els.raritySelect.value;
  state.set = els.setSelect.value;
  state.minBuy = Number(els.minBuyInput.value || 0);
  state.sort = els.sortSelect.value;
  state.foilOnly = els.foilOnly.checked;
  state.withImageOnly = els.withImageOnly.checked;
  state.hotOnly = els.hotOnly.checked;
  state.bothOnly = els.bothOnly.checked;
  state.rareOnly = els.rareOnly.checked;
}

function filterRows() {
  const query = normalize(state.query);
  const version = normalize(state.printQuery);
  state.results = (state.payload?.items || []).filter((row) => {
    if (query && !normalize([row.name, row.nameJa].join(" ")).includes(query)) return false;
    if (version) {
      const key = normalize([row.set, row.collectorNumber, row.scryfallId, row.packCode].join(" "));
      if (!key.includes(version)) return false;
    }
    if (state.language && row.language !== state.language) return false;
    if (state.category && row.displayCategory !== state.category) return false;
    if (state.rarity && row.rarity !== state.rarity) return false;
    if (state.set && row.set !== state.set) return false;
    if (state.foilOnly && !row.foil) return false;
    if (state.withImageOnly && !row.image) return false;
    if (state.hotOnly && !row.isHot) return false;
    if (state.bothOnly && row.hareruyaBuyJpy == null) return false;
    if (state.rareOnly && !RARE_SET.includes(row.rarity)) return false;
    if (Number(row.cardrushBuyJpy || 0) < state.minBuy) return false;
    return true;
  }).sort((a, b) => {
    if (state.sort === "buyAsc") return Number(a.cardrushBuyJpy || 0) - Number(b.cardrushBuyJpy || 0);
    if (state.sort === "nameAsc") return (a.name || "").localeCompare(b.name || "");
    if (state.sort === "newest") return String(b.releasedAt || "").localeCompare(String(a.releasedAt || ""));
    return Number(b.cardrushBuyJpy || 0) - Number(a.cardrushBuyJpy || 0);
  });
  const pages = Math.max(1, Math.ceil(state.results.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
}

function renderCard(row) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const imageBox = node.querySelector(".thumb");
  const image = node.querySelector("img");
  if (row.image) {
    image.src = row.image;
    image.alt = row.name || "";
    image.addEventListener("error", () => { image.remove(); imageBox.classList.add("empty"); }, { once: true });
  } else {
    image.remove();
    imageBox.classList.add("empty");
  }
  const zhName = (row.cn || "").trim();
  const enName = (row.name || "").trim();
  node.querySelector("h2").textContent = zhName || enName || "";
  const badge = node.querySelector(".badge");
  badge.textContent = row.foil ? "闪卡" : "平卡";
  if (row.isHot) badge.classList.add("hot");
  node.querySelector(".cn").textContent = zhName && enName && zhName !== enName ? enName : "";
  const setLabel = String(row.set || "").toUpperCase();
  const langLabel = row.language === "JP" ? "日文" : row.language === "EN" ? "英文" : row.language;
  const rarityText = rarityLabel(row.rarity);
  node.querySelector(".details").innerHTML = `
    <div>系列：<strong>${escapeHtml(setLabel)}</strong>${row.collectorNumber ? ` #${escapeHtml(row.collectorNumber)}` : ""} ｜ 语言：${escapeHtml(langLabel)}${rarityText ? ` ｜ 稀有度：${escapeHtml(rarityText)}` : ""}</div>
    <div>Card Rush 分类：${escapeHtml(categoryLabel(row.displayCategory) || "-")}${row.releasedAt ? ` ｜ 发售：${escapeHtml(row.releasedAt)}` : ""}</div>
  `;
  node.querySelector(".prices").innerHTML = `
    <div class="price ${row.isHot ? "hot-price" : ""}"><span>Card Rush 买取</span><strong>${yen(row.cardrushBuyJpy)}</strong><span>${row.isHot ? "高价求购" : "普通买取"}</span></div>
    <div class="price hareruya-price"><span>晴屋买取</span><strong>${yen(row.hareruyaBuyJpy)}</strong></div>
  `;
  const links = [];
  if (row.cardrushUrl) links.push(`<a href="${escapeHtml(row.cardrushUrl)}" target="_blank" rel="noreferrer">Card Rush 实时价 ↗</a>`);
  if (row.hareruyaUrl) links.push(`<a href="${escapeHtml(row.hareruyaUrl)}" target="_blank" rel="noreferrer">晴屋实时价 ↗</a>`);
  node.querySelector(".links").innerHTML = links.join("");
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
  updateFilterSummary();
}

function updateFilterSummary() {
  const count = [state.query, state.printQuery, state.language, state.category, state.rarity, state.set,
    state.minBuy > 0, state.foilOnly, state.withImageOnly, state.hotOnly, state.bothOnly, state.rareOnly]
    .filter(Boolean).length;
  els.filterSummary.textContent = count ? `${count} 项已筛选` : "默认筛选";
}

function populateControls() {
  const items = state.payload?.items || [];
  const categories = [...new Set(items.map((r) => r.displayCategory).filter(Boolean))].sort();
  els.categorySelect.replaceChildren(new Option("全部分类", ""), ...categories.map((v) => new Option(categoryLabel(v), v)));
  const rarities = [...new Set(items.map((r) => r.rarity).filter(Boolean))]
    .sort((a, b) => RARE_SET.indexOf(b) - RARE_SET.indexOf(a));
  els.raritySelect.replaceChildren(new Option("全部稀有度", ""), ...rarities.map((v) => new Option(rarityLabel(v), v)));
  const sets = [...new Set(items.map((r) => r.set).filter(Boolean))].sort();
  els.setSelect.replaceChildren(new Option("全部系列", ""), ...sets.map((v) => new Option(String(v).toUpperCase(), v)));
  renderRecentChips(items);
}

function renderRecentChips(items) {
  const bySet = new Map();
  for (const r of items) {
    if (!r.set) continue;
    const prev = bySet.get(r.set) || { set: r.set, releasedAt: "", count: 0 };
    prev.count += 1;
    if ((r.releasedAt || "") > prev.releasedAt) prev.releasedAt = r.releasedAt || "";
    bySet.set(r.set, prev);
  }
  const recent = [...bySet.values()]
    .filter((v) => v.releasedAt)
    .sort((a, b) => b.releasedAt.localeCompare(a.releasedAt))
    .slice(0, 8);
  els.recentSetChips.innerHTML = recent.map((v) => `
    <button class="set-chip ${state.set === v.set ? "active" : ""}" type="button" data-set="${escapeHtml(v.set)}">
      <span>${escapeHtml(String(v.set).toUpperCase())} · ${escapeHtml(v.releasedAt)}</span><small>${v.count}</small>
    </button>`).join("");
}

function bindEvents() {
  const rerender = () => { state.page = 1; readControls(); render(); };
  [els.searchInput, els.printSearchInput, els.languageSelect, els.categorySelect, els.raritySelect, els.setSelect,
    els.minBuyInput, els.sortSelect].forEach((e) => e.addEventListener("input", rerender));
  [els.foilOnly, els.withImageOnly, els.hotOnly, els.bothOnly, els.rareOnly].forEach((e) => e.addEventListener("change", rerender));
  els.recentSetChips.addEventListener("click", (event) => {
    const chip = event.target.closest(".set-chip");
    if (!chip) return;
    const set = chip.dataset.set;
    els.setSelect.value = state.set === set ? "" : set;
    state.page = 1;
    readControls();
    populateControls();
    render();
  });
  els.resetButton.addEventListener("click", () => {
    els.searchInput.value = "";
    els.printSearchInput.value = "";
    els.languageSelect.value = "";
    els.categorySelect.value = "";
    els.raritySelect.value = "";
    els.setSelect.value = "";
    els.minBuyInput.value = "0";
    els.sortSelect.value = "buyDesc";
    els.foilOnly.checked = false;
    els.withImageOnly.checked = false;
    els.hotOnly.checked = false;
    els.bothOnly.checked = true;
    els.rareOnly.checked = false;
    state.page = 1;
    readControls();
    populateControls();
    render();
  });
  els.prevButton.addEventListener("click", () => { state.page = Math.max(1, state.page - 1); render(); });
  els.nextButton.addEventListener("click", () => { state.page += 1; render(); });
}

async function init() {
  bindEvents();
  readControls();
  try {
    state.payload = await loadGzipJson("./cardrush_hareruya_compare.json.gz");
    const meta = state.payload.meta || {};
    const items = state.payload.items || [];
    els.itemCount.textContent = Number(meta.withHareruya || 0).toLocaleString("zh-CN");
    els.hotCount.textContent = Number(meta.items || items.length).toLocaleString("zh-CN");
    els.updatedAt.textContent = "Card Rush + 晴屋";
    els.metaLine.textContent = `Card Rush 精确匹配 ${Number(meta.items || 0).toLocaleString("zh-CN")} 条，其中 ${Number(meta.withHareruya || 0).toLocaleString("zh-CN")} 条有晴屋对应买取价，可并排对比`;
    populateControls();
    render();
  } catch (error) {
    els.metaLine.textContent = `对比数据加载失败：${error.message}`;
  }
}

init();
