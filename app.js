const PAGE_SIZE = 60;
const CART_KEY = "ck-mtg-buylist-cart-v1";
const HISTORY_KEY = "ck-mtg-buylist-history-v1";
const HISTORY_LIMIT = 30;

const state = {
  data: null,
  source: "cards",
  query: "",
  category: "",
  rarity: "",
  edition: "",
  setCode: "",
  recentSet: "",
  minPrice: 0,
  foilOnly: false,
  withImageOnly: false,
  missingCnOnly: false,
  sort: "cashDesc",
  page: 1,
  results: [],
  cardmarketLoaded: false,
  fullDataLoaded: false,
  view: "query",
  movers: null,
  moversPeriod: "daily",
  moversBasis: "percent",
  moversFormat: "all",
  moversQuery: "",
  cart: new Map(),
  history: [],
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  cardCount: document.querySelector("#cardCount"),
  sealedCount: document.querySelector("#sealedCount"),
  rate: document.querySelector("#rate"),
  queryTab: document.querySelector("#queryTab"),
  moversTab: document.querySelector("#moversTab"),
  queryView: document.querySelector("#queryView"),
  moversView: document.querySelector("#moversView"),
  moversMeta: document.querySelector("#moversMeta"),
  moversCurrent: document.querySelector("#moversCurrent"),
  moversDaily: document.querySelector("#moversDaily"),
  moversWeekly: document.querySelector("#moversWeekly"),
  moversSearch: document.querySelector("#moversSearch"),
  moversWinnersTitle: document.querySelector("#moversWinnersTitle"),
  moversLosersTitle: document.querySelector("#moversLosersTitle"),
  moversWinnersCount: document.querySelector("#moversWinnersCount"),
  moversLosersCount: document.querySelector("#moversLosersCount"),
  moversWinners: document.querySelector("#moversWinners"),
  moversLosers: document.querySelector("#moversLosers"),
  searchInput: document.querySelector("#searchInput"),
  imageInput: document.querySelector("#imageInput"),
  imageDropZone: document.querySelector("#imageDropZone"),
  imageGuessInput: document.querySelector("#imageGuessInput"),
  imageGuessButton: document.querySelector("#imageGuessButton"),
  imageOcrStatus: document.querySelector("#imageOcrStatus"),
  typeSelect: document.querySelector("#typeSelect"),
  categoryField: document.querySelector("#categoryField"),
  categorySelect: document.querySelector("#categorySelect"),
  rarityField: document.querySelector("#rarityField"),
  raritySelect: document.querySelector("#raritySelect"),
  editionField: document.querySelector("#editionField"),
  editionSelect: document.querySelector("#editionSelect"),
  setField: document.querySelector("#setField"),
  setSelect: document.querySelector("#setSelect"),
  recentSetsField: document.querySelector("#recentSetsField"),
  recentSets: document.querySelector("#recentSets"),
  minPrice: document.querySelector("#minPrice"),
  foilOnly: document.querySelector("#foilOnly"),
  withImageOnly: document.querySelector("#withImageOnly"),
  missingCnOnly: document.querySelector("#missingCnOnly"),
  sortSelect: document.querySelector("#sortSelect"),
  resetButton: document.querySelector("#resetButton"),
  fullDataButton: document.querySelector("#fullDataButton"),
  fastModeNotice: document.querySelector("#fastModeNotice"),
  resultCount: document.querySelector("#resultCount"),
  pageLine: document.querySelector("#pageLine"),
  prevButton: document.querySelector("#prevButton"),
  nextButton: document.querySelector("#nextButton"),
  cardsGrid: document.querySelector("#cardsGrid"),
  emptyState: document.querySelector("#emptyState"),
  cartSummary: document.querySelector("#cartSummary"),
  cartRows: document.querySelector("#cartRows"),
  cartEmpty: document.querySelector("#cartEmpty"),
  cartTableWrap: document.querySelector("#cartTableWrap"),
  exportCartButton: document.querySelector("#exportCartButton"),
  clearCartButton: document.querySelector("#clearCartButton"),
  historySummary: document.querySelector("#historySummary"),
  historyRows: document.querySelector("#historyRows"),
  historyEmpty: document.querySelector("#historyEmpty"),
  clearHistoryButton: document.querySelector("#clearHistoryButton"),
  template: document.querySelector("#cardTemplate"),
};

function normalize(text) {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^0-9a-z\u4e00-\u9fff]+/g, "");
}

function moneyUsd(value) {
  return `$${Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function moneyCny(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function moneyEur(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `€${Number(value || 0).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function rowCardmarketKey(row) {
  return [
    normalize(row.name),
    normalize(row.scryfallSet),
    normalize(row.collectorNumber),
  ].join("|");
}

function bestCardmarketPrice(row) {
  const market = row.cardmarket || {};
  if (row.foil && market.eurFoil !== null && market.eurFoil !== undefined) return market.eurFoil;
  if (market.eur !== null && market.eur !== undefined) return market.eur;
  if (market.eurFoil !== null && market.eurFoil !== undefined) return market.eurFoil;
  if (market.eurEtched !== null && market.eurEtched !== undefined) return market.eurEtched;
  return null;
}

function eurToCny(value) {
  const rate = Number(state.data?.meta?.eurCny || 0);
  return rate && value !== null && value !== undefined ? round2(Number(value) * rate) : null;
}

function round2(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function pct(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function valueRatio(value, base) {
  const numerator = Number(value || 0);
  const denominator = Number(base || 0);
  return denominator ? numerator / denominator : null;
}

function debounce(fn, delay = 140) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function buildSearch(row) {
  return normalize([
    row.name,
    row.ckName,
    row.flavorName,
    row.cn,
    row.edition,
    row.variation,
    row.scryfallSetName,
    row.collectorNumber,
    row.sku,
  ].filter(Boolean).join(" "));
}

function rowKey(row) {
  return row.sku || `${row.name}|${row.edition}|${row.collectorNumber}|${row.foil ? "foil" : "normal"}`;
}

function classifyRow(row) {
  const text = `${row.edition || ""} ${row.scryfallSetName || ""} ${row.scryfallSet || ""} ${row.variation || ""} ${row.flavorName || ""}`.toLowerCase();
  if (/token|helper|oversized/.test(text)) return "token";
  if (/secret lair|sld/.test(text)) return "secret";
  if (/mystery booster|the list|plist/.test(text)) return "list";
  if (/universes beyond|warhammer|doctor who|fallout|lord of the rings|marvel|spider-man|final fantasy|avatar/.test(text)) return "ub";
  if (/promo|promotional|promo pack|prerelease|media and collaboration|spotlight|wizards play network/.test(text)) return "promo";
  if (/commander|edh/.test(text)) return "commander";
  return "standard";
}

function rarityMatches(row, rarity) {
  if (!rarity) return true;
  const value = String(row.rarity || "").toLowerCase();
  if (rarity === "bulk") return value === "common" || value === "uncommon";
  if (rarity === "mythic") return value === "mythic" || value === "mythic rare";
  return value === rarity;
}

function escapeCsv(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function wantsFullData() {
  const params = new URLSearchParams(window.location.search);
  return params.get("full") === "1" || params.get("mode") === "full";
}

function cartSnapshot(row) {
  return {
    key: rowKey(row),
    sku: row.sku || "",
    name: row.name || "",
    cn: row.cn || "",
    edition: row.edition || "",
    scryfallSetName: row.scryfallSetName || "",
    scryfallSet: row.scryfallSet || "",
    collectorNumber: row.collectorNumber || "",
    variation: row.flavorName || row.variation || "",
    foil: !!row.foil,
    cashUsd: Number(row.cashUsd || 0),
    cashCny: Number(row.cashCny || 0),
    creditUsd: Number(row.creditUsd || 0),
    creditCny: Number(row.creditCny || 0),
    retailUsd: Number(row.retailUsd || row.conditions?.nm_price || 0),
    retailCny: Number(row.retailCny || 0),
    qtyBuying: Number(row.qtyBuying || 0),
    releasedAt: row.releasedAt || "",
    rarity: row.rarity || "",
    ckUrl: row.ckUrl || "",
    scryfallUrl: row.scryfallUrl || "",
    qty: 1,
  };
}

function historySnapshot(row) {
  return {
    key: rowKey(row),
    sku: row.sku || "",
    name: row.name || "",
    cn: row.cn || "",
    edition: row.edition || "",
    scryfallSetName: row.scryfallSetName || "",
    scryfallSet: row.scryfallSet || "",
    collectorNumber: row.collectorNumber || "",
    foil: !!row.foil,
    cashUsd: Number(row.cashUsd || 0),
    creditUsd: Number(row.creditUsd || 0),
    retailUsd: Number(row.retailUsd || 0),
    ckUrl: row.ckUrl || "",
    viewedAt: new Date().toISOString(),
  };
}

function expandPackedData(payload) {
  if (!Array.isArray(payload.fields)) return payload;
  const cardFields = payload.fields;
  const sealedFields = payload.sealedFields || [];
  const expand = (row, fields) => {
    const item = {};
    fields.forEach((field, index) => {
      item[field] = row[index];
    });
    item.cashUsd = Number(item.cashUsd || 0);
    item.cashCny = Number(item.cashCny || 0);
    item.creditUsd = Number(item.creditUsd || 0);
    item.creditCny = Number(item.creditCny || 0);
    item.retailUsd = Number(item.retailUsd || 0);
    item.retailCny = Number(item.retailCny || 0);
    item.qtyBuying = Number(item.qtyBuying || 0);
    item.qtyRetail = Number(item.qtyRetail || 0);
    item.conditions = {};
    item.finishes = [];
    item.search = buildSearch(item);
    return item;
  };
  return {
    meta: payload.meta || {},
    editions: payload.editions || [],
    sets: payload.sets || [],
    cards: (payload.cards || []).map((row) => expand(row, cardFields)),
    sealed: (payload.sealed || []).map((row) => expand(row, sealedFields)),
  };
}

function populateEditions() {
  const frag = document.createDocumentFragment();
  const first = document.createElement("option");
  first.value = "";
  first.textContent = "全部CK版本";
  frag.appendChild(first);
  for (const item of state.data.editions.slice(0, 800)) {
    const option = document.createElement("option");
    option.value = item.name;
    const date = item.latestReleasedAt ? ` · ${item.latestReleasedAt}` : "";
    option.textContent = `${item.name} (${item.count})${date}`;
    frag.appendChild(option);
  }
  els.editionSelect.replaceChildren(frag);
}

function getSets() {
  if (Array.isArray(state.data.sets) && state.data.sets.length) {
    return [...state.data.sets].sort((a, b) => {
      const byDate = String(b.releasedAt || "").localeCompare(String(a.releasedAt || ""));
      if (byDate) return byDate;
      return Number(b.maxCashUsd || 0) - Number(a.maxCashUsd || 0);
    });
  }
  const bySet = new Map();
  for (const row of state.data.cards) {
    const code = row.scryfallSet || "";
    const name = row.scryfallSetName || "";
    if (!code || !name) continue;
    const current = bySet.get(code) || {
      code,
      name,
      releasedAt: row.releasedAt || "",
      count: 0,
      maxCash: 0,
    };
    current.count += 1;
    current.maxCash = Math.max(current.maxCash, row.cashUsd || 0);
    if ((row.releasedAt || "") > current.releasedAt) current.releasedAt = row.releasedAt || "";
    bySet.set(code, current);
  }
  return [...bySet.values()].sort((a, b) => {
    const byDate = b.releasedAt.localeCompare(a.releasedAt);
    if (byDate) return byDate;
    return b.maxCash - a.maxCash;
  });
}

function populateSets() {
  const frag = document.createDocumentFragment();
  const first = document.createElement("option");
  first.value = "";
  first.textContent = "全部系列";
  frag.appendChild(first);
  for (const item of getSets()) {
    const option = document.createElement("option");
    option.value = item.code;
    option.textContent = `${String(item.code).toUpperCase()} · ${item.name} (${item.count})${item.releasedAt ? ` · ${item.releasedAt}` : ""}`;
    frag.appendChild(option);
  }
  els.setSelect.replaceChildren(frag);
}

function getRecentSets(limit = 18) {
  return getSets()
    .filter((item) => item.count >= 5)
    .sort((a, b) => {
      const byDate = String(b.releasedAt || "").localeCompare(String(a.releasedAt || ""));
      if (byDate) return byDate;
      return Number(b.count || 0) - Number(a.count || 0);
    })
    .slice(0, limit);
}

function populateRecentSets() {
  const frag = document.createDocumentFragment();
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "set-chip active";
  clear.dataset.set = "";
  clear.innerHTML = "<span>全部近期/旧系列</span><small>清除</small>";
  frag.appendChild(clear);

  for (const item of getRecentSets()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "set-chip";
    button.dataset.set = item.code;
    button.innerHTML = `<span>${String(item.code).toUpperCase()} · ${item.name}</span><small>${item.releasedAt || "-"} · ${item.count}</small>`;
    frag.appendChild(button);
  }
  els.recentSets.replaceChildren(frag);
}

function updateRecentSetButtons() {
  for (const button of els.recentSets.querySelectorAll(".set-chip")) {
    button.classList.toggle("active", button.dataset.set === state.recentSet);
  }
}

function applySort(rows) {
  const sorters = {
    cashDesc: (a, b) => b.cashUsd - a.cashUsd,
    cashAsc: (a, b) => a.cashUsd - b.cashUsd,
    qtyDesc: (a, b) => b.qtyBuying - a.qtyBuying,
    euDesc: (a, b) => (bestCardmarketPrice(b) || 0) - (bestCardmarketPrice(a) || 0),
    spreadDesc: (a, b) => {
      const ae = eurToCny(bestCardmarketPrice(a));
      const be = eurToCny(bestCardmarketPrice(b));
      return ((b.cashCny || 0) - (be || 0)) - ((a.cashCny || 0) - (ae || 0));
    },
    nameAsc: (a, b) => a.name.localeCompare(b.name),
    editionAsc: (a, b) => (a.edition || "").localeCompare(b.edition || ""),
  };
  return rows.sort(sorters[state.sort] || sorters.cashDesc);
}

function filterRows() {
  const rows = state.source === "cards" ? state.data.cards : state.data.sealed;
  const query = normalize(state.query);
  const minPrice = Number(state.minPrice || 0);
  let next = rows.filter((row) => {
    if (query && !row.search.includes(query)) return false;
    if (state.source === "cards" && state.category && classifyRow(row) !== state.category) return false;
    if (state.source === "cards" && !rarityMatches(row, state.rarity)) return false;
    if (state.source === "cards" && state.recentSet && row.scryfallSet !== state.recentSet) return false;
    if (state.source === "cards" && state.setCode && row.scryfallSet !== state.setCode) return false;
    if (state.edition && row.edition !== state.edition) return false;
    if (row.cashUsd < minPrice) return false;
    if (state.source === "cards" && state.foilOnly && !row.foil) return false;
    if (state.withImageOnly && !row.image) return false;
    if (state.source === "cards" && state.missingCnOnly && row.cn) return false;
    return true;
  });
  state.results = applySort(next);
  state.page = Math.min(state.page, Math.max(1, Math.ceil(state.results.length / PAGE_SIZE)));
}

function renderCard(row) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const imgBox = node.querySelector(".thumb");
  const img = node.querySelector("img");
  const h2 = node.querySelector("h2");
  const badge = node.querySelector(".badge");
  const cn = node.querySelector(".cn");
  const details = node.querySelector(".details");
  const prices = node.querySelector(".prices");
  const links = node.querySelector(".links");
  node.dataset.key = rowKey(row);
  const euPrice = state.source === "cards" ? bestCardmarketPrice(row) : null;
  const euCny = state.source === "cards" ? eurToCny(euPrice) : null;
  const ckRetailUsd = Number(row.retailUsd || row.conditions?.nm_price || 0);
  const ckRetailCny = Number(row.retailCny || 0);
  const cashRetailRatio = valueRatio(row.cashUsd, ckRetailUsd);
  const creditRetailRatio = valueRatio(row.creditUsd, ckRetailUsd);
  const spreadCny = euCny === null ? null : round2((row.cashCny || 0) - euCny);
  const spreadClass = spreadCny === null ? "" : spreadCny >= 0 ? "good" : "bad";
  const spreadText = spreadCny === null ? "-" : `${spreadCny >= 0 ? "+" : ""}${moneyCny(spreadCny)}`;

  h2.textContent = row.name;
  if (row.image) {
    img.src = row.image;
    img.alt = row.cn ? `${row.cn} / ${row.name}` : row.name;
  } else {
    img.remove();
    imgBox.classList.add("empty");
  }

  if (state.source === "cards") {
    badge.textContent = row.foil ? "Foil" : "Normal";
    badge.classList.toggle("foil", row.foil);
    if (row.activeBuying === false) {
      badge.textContent = "暂不收购";
      badge.classList.add("inactive");
    }
    cn.textContent = row.cn || "未匹配中文名";
    if (!row.cn) cn.style.color = "var(--danger)";
    const skinName = row.flavorName || row.variation || "";
    const skinCnLine = row.flavorCn ? `<div>皮肤中文：<strong>${row.flavorCn}</strong></div>` : "";
    const ckNameLine = row.ckName && row.ckName !== row.name ? `<div>CK名称：${row.ckName}</div>` : "";
    const cnSource = row.cnSource || row.match || "";
    const cnSourceLine = cnSource === "placeholder"
      ? `<div>中文来源：<strong>暂缺官方中文</strong></div>`
      : cnSource.startsWith("generated_")
        ? `<div>中文来源：<strong>补充翻译</strong></div>`
        : "";
    const imageSourceLine = row.imageSource === "name_fallback" ? `<div>图片：同名参考图</div>` : "";
    const cardmarketLink = row.cardmarket?.cardmarketUrl
      ? `<a href="${row.cardmarket.cardmarketUrl}" target="_blank" rel="noreferrer">Cardmarket/价格走势</a>`
      : "";
    details.innerHTML = `
      <div>CK版本：<strong>${row.edition || "-"}</strong></div>
      <div>Scryfall版本：<strong>${row.scryfallSet ? String(row.scryfallSet).toUpperCase() : "-"}</strong>${row.collectorNumber ? ` #${row.collectorNumber}` : ""}${row.scryfallSetName ? ` · ${row.scryfallSetName}` : ""}</div>
      ${skinName ? `<div>变体/皮肤：<strong>${skinName}</strong></div>` : ""}
      ${skinCnLine}
      ${ckNameLine}
      ${cnSourceLine}
      ${imageSourceLine}
      <div>SKU：${row.sku || "-"}</div>
      <div>稀有度：${row.rarity || "-"} ｜ 发售：${row.releasedAt || "-"} ｜ 工艺：${Array.isArray(row.finishes) && row.finishes.length ? row.finishes.join(", ") : "-"}</div>
      <div>状态：${row.activeBuying === false ? "暂不收购" : "当前收购"} ｜ 收购数量：${row.qtyBuying.toLocaleString("zh-CN")} ｜ 零售库存：${row.qtyRetail.toLocaleString("zh-CN")}</div>
      <div>品相零售价：NM ${row.conditions?.nm_price || "-"} / EX ${row.conditions?.ex_price || "-"} / VG ${row.conditions?.vg_price || "-"} / G ${row.conditions?.g_price || "-"}</div>
      <div>CK正常售价：<strong>${ckRetailUsd ? moneyUsd(ckRetailUsd) : "-"}</strong>${ckRetailCny ? ` / ${moneyCny(ckRetailCny)}` : ""} ｜ 欧洲参考：<strong>${moneyEur(euPrice)}</strong>${euCny === null ? "" : ` / ${moneyCny(euCny)}`}</div>
      <div>现金/售价：<strong>${pct(cashRetailRatio)}</strong> ｜ 积分/售价：<strong>${pct(creditRetailRatio)}</strong> ｜ CK现金-欧洲：<strong class="${spreadClass}">${spreadText}</strong></div>
    `;
    links.innerHTML = `
      <a href="${row.ckUrl}" target="_blank" rel="noreferrer">Card Kingdom</a>
      ${row.scryfallUrl ? `<a href="${row.scryfallUrl}" target="_blank" rel="noreferrer">Scryfall精确版本</a>` : ""}
      ${cardmarketLink}
    `;
    const controls = document.createElement("div");
    controls.className = "cart-controls";
    const cartItem = state.cart.get(rowKey(row));
    controls.innerHTML = `
      <button class="add-cart ${cartItem ? "in-cart" : ""}" type="button" data-key="${rowKey(row)}">${cartItem ? `已加入 ×${cartItem.qty}` : "加入回收车"}</button>
    `;
    links.after(controls);
  } else {
    badge.textContent = row.shipsInternationally ? "Intl" : "US";
    cn.textContent = "密封产品";
    details.innerHTML = `
      <div>版本：<strong>${row.edition || "-"}</strong></div>
      <div>收购数量：${row.qtyBuying.toLocaleString("zh-CN")} ｜ 零售库存：${row.qtyRetail.toLocaleString("zh-CN")}</div>
      <div>可国际运输：${row.shipsInternationally ? "是" : "否"}</div>
    `;
    links.innerHTML = `<a href="${row.ckUrl}" target="_blank" rel="noreferrer">Card Kingdom</a>`;
  }

  prices.innerHTML = `
    <div class="price"><span>现金回收</span><strong>${moneyUsd(row.cashUsd)}</strong><span>${moneyCny(row.cashCny)}</span></div>
    <div class="price"><span>店铺积分估算</span><strong>${moneyUsd(row.creditUsd)}</strong><span>${moneyCny(row.creditCny)}</span></div>
    <div class="price retail"><span>CK正常售价</span><strong>${ckRetailUsd ? moneyUsd(ckRetailUsd) : "-"}</strong><span>${ckRetailCny ? moneyCny(ckRetailCny) : "见CK链接"}</span></div>
    <div class="price ratio"><span>回收/售价</span><strong>现金 ${pct(cashRetailRatio)}</strong><span>积分 ${pct(creditRetailRatio)}</span></div>
    <div class="price market"><span>欧洲参考</span><strong>${moneyEur(bestCardmarketPrice(row))}</strong><span>${eurToCny(bestCardmarketPrice(row)) === null ? "未加载" : moneyCny(eurToCny(bestCardmarketPrice(row)))}</span></div>
    <div class="price market"><span>CK现金-欧洲</span><strong class="${spreadClass}">${spreadText}</strong><span>${row.cardmarket ? "参考价" : "无数据"}</span></div>
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
  els.emptyState.hidden = total !== 0;
  els.cardsGrid.hidden = total === 0;

  const frag = document.createDocumentFragment();
  for (const row of rows) frag.appendChild(renderCard(row));
  els.cardsGrid.replaceChildren(frag);
  updateRecentSetButtons();
}

function moversPct(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(1)}%`;
}

function moverFormat(row) {
  const text = `${row.edition || ""} ${row.setName || ""} ${row.setCode || ""}`.toLowerCase();
  if (/token|helper|oversized|secret lair|sld|promo|promotional|promo pack|prerelease|commander|edh|mystery booster|the list|plist|universes beyond|warhammer|doctor who|fallout|lord of the rings|marvel|spider-man|final fantasy|avatar/.test(text)) {
    return "special";
  }
  const released = row.releasedAt || "";
  if (released >= "2023-09-08") return "standard";
  if (released >= "2012-10-05") return "pioneer";
  if (released >= "2003-07-26") return "modern";
  return "legacy";
}

const MOVER_FORMAT_LABELS = {
  all: "全部",
  standard: "标准",
  pioneer: "先驱",
  modern: "摩登",
  legacy: "薪传",
  special: "特选",
};

function moversRows() {
  if (!state.movers) return { winners: [], losers: [] };
  const periodData = state.movers[state.moversPeriod] || {};
  const scopedData = state.moversFormat === "all"
    ? periodData
    : (periodData.formats?.[state.moversFormat] || periodData);
  const source = state.moversBasis === "dollar"
    ? { winners: scopedData.dollarsUp || [], losers: scopedData.dollarsDown || [] }
    : { winners: scopedData.winners || [], losers: scopedData.losers || [] };
  const query = normalize(state.moversQuery);
  const matches = (row) => !query || normalize([
    row.name,
    row.cn,
    row.edition,
    row.setName,
    row.setCode,
    row.collectorNumber,
    row.sku,
  ].join(" ")).includes(query);
  const usesServerFormat = state.moversFormat === "all" || !!periodData.formats?.[state.moversFormat];
  const inFormat = (row) => usesServerFormat || moverFormat(row) === state.moversFormat;
  return {
    winners: source.winners.filter((row) => matches(row) && inFormat(row)).slice(0, 50),
    losers: source.losers.filter((row) => matches(row) && inFormat(row)).slice(0, 50),
  };
}

function renderMoverRow(row, index) {
  const up = Number(row.changeUsd || 0) > 0;
  const setText = [row.setCode, row.collectorNumber ? `#${row.collectorNumber}` : ""].filter(Boolean).join(" ");
  return `
    <tr>
      <td class="mover-rank">${index + 1}</td>
      <td class="mover-card-cell">
        <div>
          <strong>${row.name || "-"}</strong>
          <span>${row.cn || "未匹配中文"}</span>
        </div>
      </td>
      <td>
        <strong>${setText || "-"}</strong>
        <span>${row.setName || row.edition || "-"}</span>
      </td>
      <td class="mover-num">${moneyUsd(row.previousCashUsd)}</td>
      <td class="mover-num">${moneyUsd(row.cashUsd)}</td>
      <td class="mover-num mover-change ${up ? "up" : "down"}">
        <span>${up ? "↑" : "↓"}${moneyUsd(Math.abs(Number(row.changeUsd || 0)))}</span>
        <small>${moversPct(row.changePct)}</small>
      </td>
    </tr>
  `;
}

function renderMovers() {
  if (!state.movers) return;
  const rows = moversRows();
  const basisText = state.moversBasis === "percent" ? "%" : "$";
  const formatText = MOVER_FORMAT_LABELS[state.moversFormat] || "全部";
  els.moversWinnersTitle.textContent = `${formatText}上涨榜 by ${basisText}`;
  els.moversLosersTitle.textContent = `${formatText}下跌榜 by ${basisText}`;
  els.moversWinnersCount.textContent = `${rows.winners.length} cards`;
  els.moversLosersCount.textContent = `${rows.losers.length} cards`;
  els.moversWinners.innerHTML = rows.winners.map(renderMoverRow).join("");
  els.moversLosers.innerHTML = rows.losers.map(renderMoverRow).join("");
}

function wantsMoversView() {
  const params = new URLSearchParams(window.location.search);
  return window.location.hash === "#movers" || params.get("view") === "movers";
}

async function loadMovers() {
  if (state.movers) {
    renderMovers();
    return;
  }
  els.moversMeta.textContent = "正在载入价格变动数据...";
  const response = await fetch(`./movers.json?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`movers fetch failed: ${response.status}`);
  state.movers = await response.json();
  const meta = state.movers.meta || {};
  els.moversCurrent.textContent = meta.currentDataAt || "-";
  els.moversDaily.textContent = Number(state.movers.daily?.changedRows || 0).toLocaleString("zh-CN");
  els.moversWeekly.textContent = Number(state.movers.weekly?.changedRows || 0).toLocaleString("zh-CN");
  els.moversMeta.textContent = `当前：${meta.currentDataAt || "-"} ｜ Daily 对比：${meta.dailyPreviousDataAt || "-"} ｜ Weekly 对比：${meta.weeklyPreviousDataAt || "-"}`;
  renderMovers();
}

function switchView(view, updateHash = true) {
  state.view = view === "movers" ? "movers" : "query";
  const movers = state.view === "movers";
  els.queryView.hidden = movers;
  els.moversView.hidden = !movers;
  document.body.classList.toggle("movers-mode", movers);
  els.queryTab.classList.toggle("active", !movers);
  els.moversTab.classList.toggle("active", movers);
  if (updateHash) history.replaceState(null, "", movers ? "#movers" : "#query");
  if (movers) {
    loadMovers().catch((error) => {
      console.error(error);
      els.moversMeta.textContent = "价格变动数据加载失败，请稍后刷新。";
    });
  }
}

function readControls() {
  state.source = els.typeSelect.value;
  state.query = els.searchInput.value;
  state.category = state.source === "cards" ? els.categorySelect.value : "";
  state.rarity = state.source === "cards" ? els.raritySelect.value : "";
  if (state.source !== "cards") state.recentSet = "";
  const selectedSet = state.source === "cards" ? els.setSelect.value : "";
  if (selectedSet !== state.recentSet) state.recentSet = "";
  state.setCode = selectedSet;
  state.edition = state.source === "cards" ? els.editionSelect.value : "";
  state.minPrice = Number(els.minPrice.value || 0);
  state.foilOnly = els.foilOnly.checked;
  state.withImageOnly = els.withImageOnly.checked;
  state.missingCnOnly = els.missingCnOnly.checked;
  state.sort = els.sortSelect.value;
  els.recentSetsField.style.display = state.source === "cards" ? "" : "none";
  els.categoryField.style.display = state.source === "cards" ? "" : "none";
  els.rarityField.style.display = state.source === "cards" ? "" : "none";
  els.setField.style.display = state.source === "cards" ? "" : "none";
  els.editionField.style.display = state.source === "cards" ? "" : "none";
  els.foilOnly.closest("label").style.display = state.source === "cards" ? "" : "none";
  els.missingCnOnly.closest("label").style.display = state.source === "cards" ? "" : "none";
}

function bindEvents() {
  const rerender = debounce(() => {
    state.page = 1;
    readControls();
    render();
  });
  els.queryTab.addEventListener("click", () => switchView("query"));
  els.moversTab.addEventListener("click", () => switchView("movers"));
  els.moversSearch.addEventListener("input", debounce(() => {
    state.moversQuery = els.moversSearch.value;
    renderMovers();
  }));
  document.querySelectorAll("[data-movers-period]").forEach((button) => {
    button.addEventListener("click", () => {
      state.moversPeriod = button.dataset.moversPeriod;
      document.querySelectorAll("[data-movers-period]").forEach((item) => item.classList.toggle("active", item === button));
      renderMovers();
    });
  });
  document.querySelectorAll("[data-movers-basis]").forEach((button) => {
    button.addEventListener("click", () => {
      state.moversBasis = button.dataset.moversBasis;
      document.querySelectorAll("[data-movers-basis]").forEach((item) => item.classList.toggle("active", item === button));
      renderMovers();
    });
  });
  document.querySelectorAll("[data-movers-format]").forEach((button) => {
    button.addEventListener("click", () => {
      state.moversFormat = button.dataset.moversFormat;
      document.querySelectorAll("[data-movers-format]").forEach((item) => item.classList.toggle("active", item === button));
      renderMovers();
    });
  });
  for (const el of [els.searchInput, els.typeSelect, els.categorySelect, els.raritySelect, els.setSelect, els.editionSelect, els.minPrice, els.foilOnly, els.withImageOnly, els.missingCnOnly, els.sortSelect]) {
    el.addEventListener("input", rerender);
    el.addEventListener("change", rerender);
  }
  els.sortSelect.addEventListener("change", () => {
    if ((els.sortSelect.value === "euDesc" || els.sortSelect.value === "spreadDesc") && !state.cardmarketLoaded) {
      els.metaLine.textContent = "正在按需加载欧洲参考价...";
      loadCardmarketData(state.data).then(() => {
        updateMetaLine();
        render();
      });
    }
  });
  els.fullDataButton.addEventListener("click", loadFullData);
  els.recentSets.addEventListener("click", (event) => {
    const button = event.target.closest(".set-chip");
    if (!button) return;
    els.typeSelect.value = "cards";
    els.setSelect.value = button.dataset.set || "";
    els.editionSelect.value = "";
    state.source = "cards";
    state.edition = "";
    state.setCode = button.dataset.set || "";
    state.recentSet = button.dataset.set || "";
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
    if (!button) return;
    const row = state.results.find((item) => rowKey(item) === button.dataset.key);
    if (!row) return;
    addToCart(row);
  });
  els.cardsGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".card");
    if (!card) return;
    const row = state.results.find((item) => rowKey(item) === card.dataset.key);
    if (!row) return;
    addHistory(row);
  });
  els.cartRows.addEventListener("input", (event) => {
    const input = event.target.closest(".cart-qty");
    if (!input) return;
    updateCartQty(input.dataset.key, Number(input.value || 0));
  });
  els.cartRows.addEventListener("click", (event) => {
    const button = event.target.closest(".remove-cart");
    if (!button) return;
    removeFromCart(button.dataset.key);
  });
  els.exportCartButton.addEventListener("click", exportCartCsv);
  els.clearCartButton.addEventListener("click", clearCart);
  els.clearHistoryButton.addEventListener("click", clearHistory);
  els.historyRows.addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-key]");
    if (!button) return;
    const row = state.history.find((item) => item.key === button.dataset.historyKey);
    if (!row) return;
    els.typeSelect.value = "cards";
    els.searchInput.value = row.name;
    state.page = 1;
    readControls();
    render();
  });
  els.resetButton.addEventListener("click", () => {
    els.searchInput.value = "";
    els.typeSelect.value = "cards";
    els.categorySelect.value = "";
    els.raritySelect.value = "";
    els.setSelect.value = "";
    els.editionSelect.value = "";
    state.setCode = "";
    state.recentSet = "";
    els.minPrice.value = "0";
    els.foilOnly.checked = false;
    els.withImageOnly.checked = false;
    els.missingCnOnly.checked = false;
    els.sortSelect.value = "cashDesc";
    state.page = 1;
    readControls();
    render();
  });
  els.imageInput.addEventListener("change", () => handleImageFile(els.imageInput.files && els.imageInput.files[0]));
  els.imageGuessButton.addEventListener("click", () => applyImageGuess(els.imageGuessInput.value));
  els.imageGuessInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyImageGuess(els.imageGuessInput.value);
  });
  for (const eventName of ["dragenter", "dragover"]) {
    els.imageDropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.imageDropZone.classList.add("dragover");
    });
    document.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.imageDropZone.classList.add("dragover");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    els.imageDropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.imageDropZone.classList.remove("dragover");
    });
    document.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (eventName === "drop") return;
      els.imageDropZone.classList.remove("dragover");
    });
  }
  els.imageDropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    handleImageFile(file);
  });
  document.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) handleImageFile(file);
  });
}

async function init() {
  loadCart();
  loadHistory();
  if (wantsMoversView()) {
    switchView("movers", false);
  }
  state.data = await loadData(wantsFullData());
  state.fullDataLoaded = state.data.meta?.mode !== "fast";
  const meta = state.data.meta;
  updateMetaLine();
  els.cardCount.textContent = (meta.fullCards || meta.cards).toLocaleString("zh-CN");
  els.sealedCount.textContent = (meta.sealed || 0).toLocaleString("zh-CN");
  els.rate.textContent = Number(meta.usdCny).toFixed(4);
  populateSets();
  populateEditions();
  populateRecentSets();
  readControls();
  bindEvents();
  render();
  renderCart();
  renderHistory();
  if (wantsMoversView()) {
    switchView("movers", false);
  } else {
    switchView("query", false);
  }
}

function updateMetaLine() {
  const meta = state.data.meta;
  const generatedCn = Number(meta.generatedCnFilled || 0);
  const generatedLine = generatedCn ? ` ｜ 补充中文 ${generatedCn.toLocaleString("zh-CN")} 张` : "";
  const euLine = state.cardmarketLoaded ? ` ｜ 欧洲参考 ${Number(meta.cardmarketMatchedRows || 0).toLocaleString("zh-CN")} 条` : " ｜ 欧洲参考按需加载";
  const modeLine = meta.mode === "fast"
    ? ` ｜ 快速版 ${Number(meta.cards || 0).toLocaleString("zh-CN")} / 全量 ${Number(meta.fullCards || meta.cards || 0).toLocaleString("zh-CN")} 张`
    : " ｜ 全量版";
  els.metaLine.textContent = `数据时间：${meta.cardKingdomCreatedAt}${modeLine} ｜ 中文未匹配 ${Number(meta.missingCn || 0).toLocaleString("zh-CN")} 张${generatedLine} ｜ 图片缺失 ${Number(meta.missingImage || 0).toLocaleString("zh-CN")} 张${euLine}`;
  els.fastModeNotice.textContent = meta.mode === "fast"
    ? "快速版只预载高价牌和最近系列；搜不到低价旧牌时点“加载全量低价牌”。"
    : "当前已加载全量数据。";
  els.fullDataButton.disabled = meta.mode !== "fast";
  els.fullDataButton.textContent = meta.mode === "fast" ? "加载全量低价牌" : "已是全量";
}

function loadCart() {
  try {
    const rows = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    state.cart = new Map(rows.map((row) => [row.key, row]));
  } catch (error) {
    console.warn("Cart not loaded", error);
    state.cart = new Map();
  }
}

function loadHistory() {
  try {
    const rows = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    state.history = Array.isArray(rows) ? rows.slice(0, HISTORY_LIMIT) : [];
  } catch (error) {
    console.warn("History not loaded", error);
    state.history = [];
  }
}

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify([...state.cart.values()]));
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history.slice(0, HISTORY_LIMIT)));
}

function addHistory(row) {
  if (!row || state.source !== "cards") return;
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

function addToCart(row) {
  const key = rowKey(row);
  const current = state.cart.get(key);
  if (current) {
    current.qty += 1;
  } else {
    state.cart.set(key, cartSnapshot(row));
  }
  addHistory(row);
  saveCart();
  renderCart();
  render();
}

function updateCartQty(key, qty) {
  const item = state.cart.get(key);
  if (!item) return;
  const nextQty = Math.max(0, Math.floor(Number(qty || 0)));
  if (nextQty <= 0) {
    state.cart.delete(key);
  } else {
    item.qty = nextQty;
  }
  saveCart();
  renderCart();
  render();
}

function removeFromCart(key) {
  state.cart.delete(key);
  saveCart();
  renderCart();
  render();
}

function clearCart() {
  if (!state.cart.size) return;
  state.cart.clear();
  saveCart();
  renderCart();
  render();
}

function renderCart() {
  const rows = [...state.cart.values()].sort((a, b) => b.cashUsd - a.cashUsd);
  const totalQty = rows.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const totalCash = rows.reduce((sum, row) => sum + Number(row.qty || 0) * Number(row.cashUsd || 0), 0);
  const totalCredit = rows.reduce((sum, row) => sum + Number(row.qty || 0) * Number(row.creditUsd || 0), 0);
  const totalRetail = rows.reduce((sum, row) => sum + Number(row.qty || 0) * Number(row.retailUsd || 0), 0);
  els.cartSummary.textContent = `${rows.length.toLocaleString("zh-CN")} 种 / ${totalQty.toLocaleString("zh-CN")} 张 / 现金 ${moneyUsd(totalCash)} (${pct(valueRatio(totalCash, totalRetail))}) / 积分 ${moneyUsd(totalCredit)} (${pct(valueRatio(totalCredit, totalRetail))}) / CK售价 ${moneyUsd(totalRetail)}`;
  els.cartEmpty.hidden = rows.length !== 0;
  els.cartTableWrap.hidden = rows.length === 0;
  els.exportCartButton.disabled = rows.length === 0;
  els.clearCartButton.disabled = rows.length === 0;

  const frag = document.createDocumentFragment();
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${row.name}</strong><br><span>${row.cn || ""}${row.foil ? " / Foil" : ""}</span></td>
      <td>${row.edition || "-"}<br><span>${String(row.scryfallSet || "").toUpperCase()}${row.collectorNumber ? ` #${row.collectorNumber}` : ""}${row.scryfallSetName ? ` · ${row.scryfallSetName}` : ""}</span></td>
      <td>${row.collectorNumber || "-"}<br><span>${row.sku || ""}</span></td>
      <td><input class="cart-qty" data-key="${row.key}" type="number" min="0" step="1" value="${row.qty}"></td>
      <td>${moneyUsd(row.cashUsd)}<br><span>积分 ${moneyUsd(row.creditUsd)}</span></td>
      <td><button class="remove-cart" data-key="${row.key}" type="button">移除</button></td>
    `;
    frag.appendChild(tr);
  }
  els.cartRows.replaceChildren(frag);
}

function renderHistory() {
  const rows = state.history || [];
  els.historySummary.textContent = rows.length
    ? `最近 ${rows.length.toLocaleString("zh-CN")} 条`
    : "最近看过的单卡会显示在这里";
  els.historyEmpty.hidden = rows.length !== 0;
  els.historyRows.hidden = rows.length === 0;
  els.clearHistoryButton.disabled = rows.length === 0;

  const frag = document.createDocumentFragment();
  for (const row of rows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.historyKey = row.key;
    const setLine = `${String(row.scryfallSet || "").toUpperCase()}${row.collectorNumber ? ` #${row.collectorNumber}` : ""}${row.scryfallSetName ? ` · ${row.scryfallSetName}` : ""}`;
    button.innerHTML = `
      <strong>${row.name || "-"}</strong>
      <span>${row.cn || ""}${row.foil ? " / Foil" : ""}</span>
      <small>${setLine || row.edition || "-"} · ${moneyUsd(row.cashUsd)}</small>
    `;
    frag.appendChild(button);
  }
  els.historyRows.replaceChildren(frag);
}

function exportCartCsv() {
  const rows = [...state.cart.values()].sort((a, b) => b.cashUsd - a.cashUsd);
  if (!rows.length) return;
  const headers = [
    "英文名",
    "中文名",
    "CK版本",
    "Scryfall系列",
    "系列代码",
    "编号",
    "变体/皮肤",
    "闪卡",
    "数量",
    "现金回收USD",
    "现金回收CNY",
    "现金小计USD",
    "店铺积分USD",
    "店铺积分小计USD",
    "CK正常售价USD",
    "CK正常售价小计USD",
    "现金/售价比例",
    "积分/售价比例",
    "收购数量",
    "发售日",
    "稀有度",
    "Card Kingdom链接",
    "Scryfall链接",
    "SKU",
  ];
  const lines = [headers.map(escapeCsv).join(",")];
  for (const row of rows) {
    const qty = Number(row.qty || 0);
    lines.push([
      row.name,
      row.cn,
      row.edition,
      row.scryfallSetName,
      String(row.scryfallSet || "").toUpperCase(),
      row.collectorNumber,
      row.variation,
      row.foil ? "是" : "否",
      qty,
      row.cashUsd,
      row.cashCny,
      round2(qty * Number(row.cashUsd || 0)),
      row.creditUsd,
      round2(qty * Number(row.creditUsd || 0)),
      row.retailUsd,
      round2(qty * Number(row.retailUsd || 0)),
      valueRatio(row.cashUsd, row.retailUsd),
      valueRatio(row.creditUsd, row.retailUsd),
      row.qtyBuying,
      row.releasedAt,
      row.rarity,
      row.ckUrl,
      row.scryfallUrl,
      row.sku,
    ].map(escapeCsv).join(","));
  }
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  link.href = url;
  link.download = `ck_buylist_cart_${stamp}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function loadFullData() {
  if (state.fullDataLoaded) return;
  els.fullDataButton.disabled = true;
  els.fullDataButton.textContent = "正在加载全量...";
  els.metaLine.textContent = "正在加载全量数据，低性能浏览器可能需要等待...";
  state.data = await loadData(true);
  state.fullDataLoaded = true;
  if (state.cardmarketLoaded) state.cardmarketLoaded = false;
  populateSets();
  populateEditions();
  populateRecentSets();
  readControls();
  updateMetaLine();
  render();
}

init().catch((err) => {
  console.error(err);
  els.metaLine.textContent = "数据加载失败，请确认 data.json 与 index.html 在同一目录，并通过本地服务器打开。";
});

async function loadData(full = false) {
  const stamp = Date.now();
  const fastName = full ? "data.json.gz" : "data_fast.json.gz";
  try {
    els.metaLine.textContent = full ? "正在加载全量压缩数据..." : "正在加载快速数据...";
    return expandPackedData(await loadGzipJson(`./${fastName}?v=${stamp}`, fastName));
  } catch (error) {
    console.warn("Falling back to uncompressed data.json", error);
  }
  els.metaLine.textContent = "正在加载完整数据...";
  const response = await fetch(`./data.json?v=${stamp}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`data fetch failed: ${response.status}`);
  return await response.json();
}

async function loadCardmarketData(data) {
  try {
    const payload = await loadJsonMaybeGzip("cardmarket_prices.json");
    const prices = payload.prices || {};
    let matched = 0;
    for (const row of data.cards || []) {
      const record = prices[`id:${row.scryfallId}`] || prices[`key:${rowCardmarketKey(row)}`];
      if (!record) continue;
      row.cardmarket = record;
      matched += 1;
    }
    data.meta.cardmarketMatchedRows = matched;
    data.meta.cardmarketGeneratedAt = payload.meta?.generatedAt || "";
    if (payload.meta?.eurCny) data.meta.eurCny = payload.meta.eurCny;
    state.cardmarketLoaded = true;
  } catch (error) {
    console.warn("Cardmarket reference data not loaded", error);
    state.cardmarketLoaded = false;
  }
}

async function loadJsonMaybeGzip(baseName) {
  const stamp = Date.now();
  try {
    return await loadGzipJson(`./${baseName}.gz?v=${stamp}`, `${baseName}.gz`);
  } catch (error) {
    console.warn(`${baseName}.gz not loaded, trying plain json`, error);
  }
  const response = await fetch(`./${baseName}?v=${stamp}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${baseName} fetch failed: ${response.status}`);
  return await response.json();
}

async function loadGzipJson(url, label) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${label} fetch failed: ${response.status}`);
  if ("DecompressionStream" in window && response.body) {
    try {
      const stream = response.clone().body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(stream).json();
    } catch (error) {
      console.warn(`${label} native gzip decode failed, trying pako`, error);
    }
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) {
    return JSON.parse(new TextDecoder("utf-8").decode(bytes));
  }
  await ensurePako();
  return JSON.parse(window.pako.inflate(bytes, { to: "string" }));
}

async function ensurePako() {
  if (window.pako && typeof window.pako.inflate === "function") return;
  await loadScript("./pako_inflate.min.js?v=20260706-pako");
  if (!window.pako || typeof window.pako.inflate !== "function") {
    throw new Error("本地 gzip 解压库未加载");
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if ([...document.scripts].some((script) => script.src === src)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

function pickCardNameFromOcr(text) {
  const lines = String(text || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => /^[A-Za-z0-9,'’\-: ]{3,}$/.test(line))
    .filter((line) => !/^(legendary|creature|artifact|instant|sorcery|enchantment|land|planeswalker)\b/i.test(line));
  return lines[0] || "";
}

function applyImageGuess(guess) {
  const value = String(guess || "").trim();
  if (!value) {
    els.imageOcrStatus.textContent = "请输入牌名再搜索。";
    return;
  }
  els.searchInput.value = value;
  els.typeSelect.value = "cards";
  els.imageOcrStatus.textContent = `按牌名搜索：${value}`;
  state.page = 1;
  readControls();
  render();
}

async function handleImageFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    els.imageOcrStatus.textContent = "请拖入图片文件。";
    return;
  }
  els.imageOcrStatus.textContent = `已收到图片：${file.name || "未命名"}，正在加载 OCR...`;
  try {
    await loadScript("https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js");
    if (!window.Tesseract) throw new Error("Tesseract 未加载");
    els.imageOcrStatus.textContent = "OCR 已加载，正在识别英文牌名...";
    const result = await window.Tesseract.recognize(file, "eng");
    const guess = pickCardNameFromOcr(result.data?.text || "");
    if (!guess) {
      els.imageGuessInput.value = "";
      els.imageOcrStatus.textContent = "没有识别到可靠英文牌名。可以换清晰正面图，或在上方手动输入牌名。";
      return;
    }
    els.imageGuessInput.value = guess;
    applyImageGuess(guess);
  } catch (error) {
    console.error(error);
    els.imageOcrStatus.textContent = `OCR 加载或识别失败：${error.message || error}。当前 file:// 或网络环境可能拦截 OCR 脚本；请用 http://127.0.0.1:8787 打开，或在上方手动输入牌名。`;
  }
}
