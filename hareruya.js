const PAGE_SIZE = 60;
const CART_KEY = "hareruya-mtg-buylist-cart-v1";
const HISTORY_KEY = "hareruya-mtg-buylist-history-v1";
const HISTORY_LIMIT = 30;

const state = {
  payload: null,
  query: "",
  printQuery: "",
  language: "",
  set: "",
  minBuy: 0,
  withImageOnly: false,
  buyableOnly: false,
  sort: "buyRatioDesc",
  page: 1,
  results: [],
  cart: new Map(),
  cartQuery: "",
  cartSelected: new Set(),
  history: [],
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  itemCount: document.querySelector("#itemCount"),
  jpyRate: document.querySelector("#jpyRate"),
  updatedAt: document.querySelector("#updatedAt"),
  searchInput: document.querySelector("#searchInput"),
  printSearchInput: document.querySelector("#printSearchInput"),
  languageSelect: document.querySelector("#languageSelect"),
  minBuyInput: document.querySelector("#minBuyInput"),
  sortSelect: document.querySelector("#sortSelect"),
  withImageOnly: document.querySelector("#withImageOnly"),
  buyableOnly: document.querySelector("#buyableOnly"),
  setFinderInput: document.querySelector("#setFinderInput"),
  setSelect: document.querySelector("#setSelect"),
  filterSummary: document.querySelector("#filterSummary"),
  resetButton: document.querySelector("#resetButton"),
  resultCount: document.querySelector("#resultCount"),
  pageLine: document.querySelector("#pageLine"),
  prevButton: document.querySelector("#prevButton"),
  nextButton: document.querySelector("#nextButton"),
  cardsGrid: document.querySelector("#cardsGrid"),
  emptyState: document.querySelector("#emptyState"),
  template: document.querySelector("#cardTemplate"),
  cartSummary: document.querySelector("#cartSummary"),
  cartRows: document.querySelector("#cartRows"),
  cartEmpty: document.querySelector("#cartEmpty"),
  cartTableWrap: document.querySelector("#cartTableWrap"),
  cartSearchInput: document.querySelector("#cartSearchInput"),
  cartSelectVisible: document.querySelector("#cartSelectVisible"),
  removeSelectedCartButton: document.querySelector("#removeSelectedCartButton"),
  cartSelectionSummary: document.querySelector("#cartSelectionSummary"),
  exportCartButton: document.querySelector("#exportCartButton"),
  clearCartButton: document.querySelector("#clearCartButton"),
  historySummary: document.querySelector("#historySummary"),
  historyRows: document.querySelector("#historyRows"),
  historyEmpty: document.querySelector("#historyEmpty"),
  clearHistoryButton: document.querySelector("#clearHistoryButton"),
};

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+/g, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function cleanCardName(value) {
  return String(value || "").replace(/^.*《/, "").replace(/》.*$/, "").trim();
}

function rowKey(row) {
  return `${row.productId}|${row.language || ""}`;
}

function languageLabel(value) {
  return value === "JP" ? "日文" : value === "EN" ? "英文" : value || "其他";
}

function yen(value) {
  return value === null || value === undefined || value === "" ? "-" : `¥${Number(value).toLocaleString("ja-JP")}`;
}

function cny(value) {
  const rate = Number(state.payload?.meta?.jpyCny || 0);
  return value === null || value === undefined || !rate ? "" : `¥${(Number(value) * rate).toFixed(2)}`;
}

function buyPrice(row) {
  return row.buy?.[row.language] ?? null;
}

function salePrice(row, condition) {
  return row.sale?.[row.language]?.[condition] ?? null;
}

function buySaleRatio(row) {
  const buy = Number(buyPrice(row) || 0);
  const nm = Number(salePrice(row, "NM") || 0);
  return nm > 0 ? buy / nm : null;
}

function pct(value) {
  return value === null || value === undefined ? "-" : `${(Number(value) * 100).toFixed(1)}%`;
}

function displayedName(row) {
  return cleanCardName(row.name || row.nameJa) || "未命名商品";
}

function displayedJapaneseName(row) {
  return cleanCardName(row.nameJa);
}

function versionMarker(row) {
  return [row.set ? String(row.set).toUpperCase() : "", row.collectorNumber ? `#${row.collectorNumber}` : "", `晴屋 #${row.productId}`].filter(Boolean).join(" · ");
}

function rowSearch(row) {
  return normalize([displayedName(row), displayedJapaneseName(row), row.name, row.nameJa].join(" "));
}

function printSearch(row) {
  return normalize([row.set, row.collectorNumber, row.productId, row.language].join(" "));
}

function snapshot(row) {
  return {
    key: rowKey(row),
    productId: String(row.productId || ""),
    language: row.language || "",
    name: displayedName(row),
    nameJa: displayedJapaneseName(row),
    set: row.set || "",
    collectorNumber: row.collectorNumber || "",
    image: row.image || "",
    buyJpy: buyPrice(row),
    nmJpy: salePrice(row, "NM"),
    spJpy: salePrice(row, "SP"),
    mpJpy: salePrice(row, "MP"),
    hpJpy: salePrice(row, "HP"),
    saleUrl: row.saleUrl || "",
    buyUrl: row.buyUrl || "",
    qty: 1,
  };
}

function historySnapshot(row) {
  return { ...snapshot(row), viewedAt: new Date().toISOString() };
}

function loadPersisted() {
  try {
    const rows = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    state.cart = new Map(Array.isArray(rows) ? rows.map((row) => [row.key, row]) : []);
  } catch (error) {
    console.warn("Hareruya cart not loaded", error);
  }
  try {
    const rows = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    state.history = Array.isArray(rows) ? rows.slice(0, HISTORY_LIMIT) : [];
  } catch (error) {
    console.warn("Hareruya history not loaded", error);
  }
}

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify([...state.cart.values()]));
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history.slice(0, HISTORY_LIMIT)));
}

function openCart() {
  const panel = document.querySelector(".cart-panel");
  if (panel) panel.open = true;
}

function addToCart(row) {
  const key = rowKey(row);
  const current = state.cart.get(key);
  if (current) current.qty += 1;
  else state.cart.set(key, snapshot(row));
  addHistory(row);
  saveCart();
  renderCart();
  render();
  openCart();
}

function updateCartQty(key, qty) {
  const item = state.cart.get(key);
  if (!item) return;
  const next = Math.max(0, Math.floor(Number(qty || 0)));
  if (!next) {
    state.cart.delete(key);
    state.cartSelected.delete(key);
  } else item.qty = next;
  saveCart();
  renderCart();
  render();
}

function removeFromCart(key) {
  state.cart.delete(key);
  state.cartSelected.delete(key);
  saveCart();
  renderCart();
  render();
}

function clearCart() {
  if (!state.cart.size || window.confirm("清空晴屋回收车？")) {
    state.cart.clear();
    state.cartSelected.clear();
    saveCart();
    renderCart();
    render();
  }
}

function cartVisibleRows() {
  const query = normalize(state.cartQuery);
  return [...state.cart.values()].filter((row) => !query || normalize([row.name, row.nameJa, row.set, row.collectorNumber, row.productId].join(" ")).includes(query));
}

function removeSelectedCart() {
  if (!state.cartSelected.size) return;
  if (!window.confirm(`移除已选 ${state.cartSelected.size} 项？`)) return;
  for (const key of state.cartSelected) state.cart.delete(key);
  state.cartSelected.clear();
  saveCart();
  renderCart();
  render();
}

function exportCartCsv() {
  const headers = ["牌名", "日文名", "晴屋标记", "编号", "语言", "晴屋商品ID", "数量", "晴屋收购JPY", "晴屋收购CNY", "NM售价JPY", "SP售价JPY", "MP售价JPY", "HP售价JPY", "晴屋售价链接", "晴屋收购链接"];
  const lines = [...state.cart.values()].map((row) => [row.name, row.nameJa, row.set, row.collectorNumber, languageLabel(row.language), row.productId, row.qty, row.buyJpy, cny(row.buyJpy), row.nmJpy, row.spJpy, row.mpJpy, row.hpJpy, row.saleUrl, row.buyUrl]);
  const escapeCsv = (value) => {
    const text = String(value ?? "");
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const csv = [headers, ...lines].map((row) => row.map(escapeCsv).join(",")).join("\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `hareruya-buylist-cart-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function addHistory(row) {
  const next = historySnapshot(row);
  state.history = [next, ...state.history.filter((item) => item.key !== next.key)].slice(0, HISTORY_LIMIT);
  saveHistory();
  renderHistory();
}

function clearHistory() {
  state.history = [];
  saveHistory();
  renderHistory();
}

function renderCart() {
  const rows = cartVisibleRows();
  const allRows = [...state.cart.values()];
  const totalQty = allRows.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const totalBuy = allRows.reduce((sum, row) => sum + Number(row.buyJpy || 0) * Number(row.qty || 0), 0);
  const totalNm = allRows.reduce((sum, row) => sum + Number(row.nmJpy || 0) * Number(row.qty || 0), 0);
  const totalRatio = totalNm > 0 ? totalBuy / totalNm : null;
  els.cartSummary.textContent = `${allRows.length} 种 / ${totalQty} 张 / 收购 ${yen(totalBuy)} / ${cny(totalBuy)} ｜ NM ${yen(totalNm)} ｜ 收购/NM ${pct(totalRatio)}`;
  els.cartEmpty.hidden = allRows.length > 0;
  els.cartTableWrap.hidden = allRows.length === 0;
  els.cartRows.innerHTML = rows.map((row) => `<tr>
    <td class="cart-check-col"><input class="cart-select" type="checkbox" data-key="${escapeHtml(row.key)}" ${state.cartSelected.has(row.key) ? "checked" : ""}></td>
    <td><strong>${escapeHtml(row.name)}</strong>${row.nameJa && row.nameJa !== row.name ? `<small class="hareruya-cart-subtitle">${escapeHtml(row.nameJa)}</small>` : ""}</td>
    <td>${escapeHtml([row.set, row.collectorNumber ? `#${row.collectorNumber}` : "", `#${row.productId}`].filter(Boolean).join(" · "))}</td>
    <td>${escapeHtml(languageLabel(row.language))}</td>
    <td><input class="cart-qty" type="number" min="0" step="1" data-key="${escapeHtml(row.key)}" value="${Number(row.qty || 0)}"></td>
    <td><strong>${yen(row.buyJpy)}</strong><small class="hareruya-cart-subtitle">${cny(row.buyJpy)}</small></td>
    <td><strong>${yen(row.nmJpy)}</strong><small class="hareruya-cart-subtitle">${cny(row.nmJpy)}</small></td>
    <td><button class="remove-cart" type="button" data-key="${escapeHtml(row.key)}">移除</button></td>
  </tr>`).join("");
  const visibleKeys = rows.map((row) => row.key);
  els.cartSelectVisible.checked = visibleKeys.length > 0 && visibleKeys.every((key) => state.cartSelected.has(key));
  els.cartSelectionSummary.textContent = state.cartSelected.size ? `已选 ${state.cartSelected.size} 项` : "";
}

function renderHistory() {
  els.historyEmpty.hidden = state.history.length > 0;
  els.historyRows.hidden = state.history.length === 0;
  els.historySummary.textContent = state.history.length ? `最近 ${state.history.length} 条晴屋商品` : "最近看过的晴屋商品会显示在这里";
  els.historyRows.innerHTML = state.history.map((row) => `<button class="history-item" type="button" data-history-key="${escapeHtml(row.key)}"><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.nameJa || languageLabel(row.language))}</span><small>${escapeHtml(versionMarker(row))} ｜ ${yen(row.buyJpy)}</small></button>`).join("");
}

function populateSets() {
  const values = [...new Set((state.payload?.items || []).map((row) => String(row.set || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  els.setSelect.replaceChildren(new Option("全部标记", ""), ...values.map((value) => new Option(value.toUpperCase(), value)));
}

function readControls() {
  state.query = els.searchInput.value;
  state.printQuery = els.printSearchInput.value;
  state.language = els.languageSelect.value;
  state.minBuy = Number(els.minBuyInput.value || 0);
  state.set = els.setSelect.value;
  state.withImageOnly = els.withImageOnly.checked;
  state.buyableOnly = els.buyableOnly.checked;
  state.sort = els.sortSelect.value;
}

function applySetFinder() {
  const query = normalize(els.setFinderInput.value);
  if (!query) return;
  const option = [...els.setSelect.options].find((item) => normalize(item.value).includes(query));
  if (option) els.setSelect.value = option.value;
  state.page = 1;
  readControls();
  render();
}

function filterRows() {
  const query = normalize(state.query);
  const version = normalize(state.printQuery);
  state.results = (state.payload?.items || []).filter((row) => {
    if (query && !rowSearch(row).includes(query)) return false;
    if (version && !printSearch(row).includes(version)) return false;
    if (state.language && row.language !== state.language) return false;
    if (state.set && row.set !== state.set) return false;
    if (buyPrice(row) !== null && Number(buyPrice(row)) < state.minBuy) return false;
    if (state.minBuy && buyPrice(row) === null) return false;
    if (state.withImageOnly && !row.image) return false;
    if (state.buyableOnly && buyPrice(row) === null) return false;
    return true;
  }).sort((a, b) => {
    if (state.sort === "buyRatioDesc") return (buySaleRatio(b) ?? -1) - (buySaleRatio(a) ?? -1);
    if (state.sort === "saleDesc") return Number(salePrice(b, "NM") || 0) - Number(salePrice(a, "NM") || 0);
    if (state.sort === "saleAsc") return Number(salePrice(a, "NM") ?? Infinity) - Number(salePrice(b, "NM") ?? Infinity);
    if (state.sort === "nameAsc") return displayedName(a).localeCompare(displayedName(b));
    if (state.sort === "setAsc") return versionMarker(a).localeCompare(versionMarker(b));
    return Number(buyPrice(b) || 0) - Number(buyPrice(a) || 0);
  });
  state.page = Math.min(state.page, Math.max(1, Math.ceil(state.results.length / PAGE_SIZE)));
}

function updateFilterSummary() {
  const count = [state.query, state.printQuery, state.language, state.set, state.minBuy > 0, state.withImageOnly, state.buyableOnly].filter(Boolean).length;
  els.filterSummary.textContent = count ? `${count} 项已筛选` : "默认筛选";
}

function priceBlock(label, value, className = "") {
  return `<div class="price ${className}"><span>${label}</span><strong>${yen(value)}</strong><span>${cny(value) || "未报价"}</span></div>`;
}

function ratioBlock(row) {
  return `<div class="price ratio"><span>收购 / NM 售价</span><strong>${pct(buySaleRatio(row))}</strong><span>晴屋公开标价对比</span></div>`;
}

function renderCard(row) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const imageBox = node.querySelector(".thumb");
  const image = node.querySelector("img");
  const name = displayedName(row);
  const japaneseName = displayedJapaneseName(row);
  node.dataset.key = rowKey(row);
  node.querySelector("h2").textContent = name;
  node.querySelector(".badge").textContent = languageLabel(row.language);
  node.querySelector(".cn").textContent = japaneseName && japaneseName !== name ? japaneseName : `晴屋 ${languageLabel(row.language)}版`;
  if (row.image) {
    const imageVersion = encodeURIComponent(state.payload?.meta?.generatedAt || "latest");
    image.src = `${row.image}${row.image.includes("?") ? "&" : "?"}v=${imageVersion}`;
    image.alt = name;
    image.addEventListener("error", () => {
      image.remove();
      imageBox.classList.add("empty");
    }, { once: true });
  } else {
    image.remove();
    imageBox.classList.add("empty");
  }
  node.querySelector(".details").innerHTML = `
    <div>晴屋版本标记：<strong>${escapeHtml(row.set ? String(row.set).toUpperCase() : "-")}</strong>${row.collectorNumber ? ` #${escapeHtml(row.collectorNumber)}` : ""}</div>
    <div>晴屋商品 ID：<strong>#${escapeHtml(row.productId)}</strong> ｜ 语言：${escapeHtml(languageLabel(row.language))}</div>
    <div>图片：晴屋公开商品页 ｜ 价格采集：${escapeHtml(row.capturedAt || state.payload?.meta?.generatedAt || "-")}</div>
  `;
  node.querySelector(".prices").innerHTML = [
    priceBlock("晴屋收购", buyPrice(row)),
    priceBlock("晴屋售价 NM", salePrice(row, "NM"), "retail"),
    priceBlock("晴屋售价 SP", salePrice(row, "SP")),
    priceBlock("晴屋售价 MP", salePrice(row, "MP")),
    priceBlock("晴屋售价 HP", salePrice(row, "HP")),
    ratioBlock(row),
  ].join("");
  node.querySelector(".links").innerHTML = `${row.saleUrl ? `<a href="${escapeHtml(row.saleUrl)}" target="_blank" rel="noreferrer">晴屋售价页</a>` : ""}${row.buyUrl ? `<a href="${escapeHtml(row.buyUrl)}" target="_blank" rel="noreferrer">晴屋收购页</a>` : ""}`;
  const cart = state.cart.get(rowKey(row));
  const controls = document.createElement("div");
  controls.className = "cart-controls";
  controls.innerHTML = `<button class="add-cart ${cart ? "in-cart" : ""}" type="button" data-key="${escapeHtml(rowKey(row))}">${cart ? `已加入 ×${cart.qty}` : "加入晴屋回收车"}</button>`;
  node.querySelector(".links").after(controls);
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

function bindEvents() {
  const rerender = () => {
    state.page = 1;
    readControls();
    render();
  };
  [els.searchInput, els.printSearchInput, els.languageSelect, els.minBuyInput, els.sortSelect, els.withImageOnly, els.buyableOnly, els.setSelect].forEach((element) => {
    element.addEventListener("input", rerender);
    element.addEventListener("change", rerender);
  });
  els.setFinderInput.addEventListener("change", applySetFinder);
  els.setFinderInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applySetFinder();
  });
  els.resetButton.addEventListener("click", () => {
    els.searchInput.value = "";
    els.printSearchInput.value = "";
    els.languageSelect.value = "";
    els.minBuyInput.value = "0";
    els.sortSelect.value = "buyRatioDesc";
    els.withImageOnly.checked = false;
    els.buyableOnly.checked = false;
    els.setFinderInput.value = "";
    els.setSelect.value = "";
    state.page = 1;
    readControls();
    render();
  });
  els.prevButton.addEventListener("click", () => {
    state.page = Math.max(1, state.page - 1);
    render();
  });
  els.nextButton.addEventListener("click", () => {
    state.page += 1;
    render();
  });
  els.cardsGrid.addEventListener("click", (event) => {
    const button = event.target.closest(".add-cart");
    if (button) {
      const row = state.results.find((item) => rowKey(item) === button.dataset.key);
      if (row) addToCart(row);
      return;
    }
    const card = event.target.closest(".hareruya-card");
    if (!card) return;
    const row = state.results.find((item) => rowKey(item) === card.dataset.key);
    if (row) addHistory(row);
  });
  els.cartRows.addEventListener("input", (event) => {
    const input = event.target.closest(".cart-qty");
    if (input) updateCartQty(input.dataset.key, input.value);
  });
  els.cartRows.addEventListener("click", (event) => {
    const button = event.target.closest(".remove-cart");
    if (button) removeFromCart(button.dataset.key);
  });
  els.cartRows.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".cart-select");
    if (!checkbox) return;
    if (checkbox.checked) state.cartSelected.add(checkbox.dataset.key);
    else state.cartSelected.delete(checkbox.dataset.key);
    renderCart();
  });
  els.cartSearchInput.addEventListener("input", () => {
    state.cartQuery = els.cartSearchInput.value;
    renderCart();
  });
  els.cartSelectVisible.addEventListener("change", () => {
    cartVisibleRows().forEach((row) => {
      if (els.cartSelectVisible.checked) state.cartSelected.add(row.key);
      else state.cartSelected.delete(row.key);
    });
    renderCart();
  });
  els.removeSelectedCartButton.addEventListener("click", removeSelectedCart);
  els.exportCartButton.addEventListener("click", exportCartCsv);
  els.clearCartButton.addEventListener("click", clearCart);
  els.clearHistoryButton.addEventListener("click", clearHistory);
  els.historyRows.addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-key]");
    if (!button) return;
    const row = state.history.find((item) => item.key === button.dataset.historyKey);
    if (!row) return;
    els.searchInput.value = row.name;
    els.printSearchInput.value = "";
    state.page = 1;
    readControls();
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

async function init() {
  loadPersisted();
  const response = await fetch(`./hareruya_prices.json?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.payload = await response.json();
  const meta = state.payload.meta || {};
  els.itemCount.textContent = Number(meta.items || state.payload.items?.length || 0).toLocaleString("zh-CN");
  els.jpyRate.textContent = meta.jpyCny ? Number(meta.jpyCny).toFixed(4) : "-";
  els.updatedAt.textContent = meta.generatedAt ? String(meta.generatedAt).replace("T", " ").slice(0, 16) : "-";
  const verifiedRetail = Number(meta.verifiedRetailItems || 0).toLocaleString("zh-CN");
  els.metaLine.textContent = `晴屋公开回收列表 ｜ 收购 ${Number(meta.items || 0).toLocaleString("zh-CN")} 条 ｜ 已验证品相售价 ${verifiedRetail} 条 ｜ 图片 ${Number(meta.images || 0).toLocaleString("zh-CN")} 张 ｜ 更新 ${meta.generatedAt || "未更新"}`;
  populateSets();
  readControls();
  bindEvents();
  render();
  renderCart();
  renderHistory();
}

init().catch((error) => {
  console.error(error);
  els.metaLine.textContent = "晴屋价格快照加载失败，请稍后刷新。";
});
