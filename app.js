const PAGE_SIZE = 60;

const state = {
  data: null,
  source: "cards",
  query: "",
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
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  cardCount: document.querySelector("#cardCount"),
  sealedCount: document.querySelector("#sealedCount"),
  rate: document.querySelector("#rate"),
  searchInput: document.querySelector("#searchInput"),
  typeSelect: document.querySelector("#typeSelect"),
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
  resultCount: document.querySelector("#resultCount"),
  pageLine: document.querySelector("#pageLine"),
  prevButton: document.querySelector("#prevButton"),
  nextButton: document.querySelector("#nextButton"),
  cardsGrid: document.querySelector("#cardsGrid"),
  emptyState: document.querySelector("#emptyState"),
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

function debounce(fn, delay = 140) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
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
    option.textContent = `${item.name} (${String(item.code).toUpperCase()} · ${item.count})${item.releasedAt ? ` · ${item.releasedAt}` : ""}`;
    frag.appendChild(option);
  }
  els.setSelect.replaceChildren(frag);
}

function getRecentSets(limit = 10) {
  const bySet = new Map();
  for (const row of state.data.cards) {
    const code = row.scryfallSet || "";
    const name = row.scryfallSetName || "";
    if (!code || !name || /token/i.test(name)) continue;
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
  return [...bySet.values()]
    .filter((item) => item.count >= 5)
    .sort((a, b) => {
      const byDate = b.releasedAt.localeCompare(a.releasedAt);
      if (byDate) return byDate;
      return b.count - a.count;
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
    button.innerHTML = `<span>${item.name}</span><small>${item.releasedAt} · ${item.count}</small>`;
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
    cn.textContent = row.cn || "未匹配中文名";
    if (!row.cn) cn.style.color = "var(--danger)";
    details.innerHTML = `
      <div>CK版本：<strong>${row.edition || "-"}</strong></div>
      <div>Scryfall版本：<strong>${row.scryfallSetName || "-"}</strong>${row.scryfallSet ? ` (${String(row.scryfallSet).toUpperCase()}` : ""}${row.collectorNumber ? ` #${row.collectorNumber}` : ""}${row.scryfallSet ? ")" : ""}</div>
      <div>变体：${row.variation || "-"} ｜ SKU：${row.sku || "-"}</div>
      <div>稀有度：${row.rarity || "-"} ｜ 发售：${row.releasedAt || "-"} ｜ 工艺：${Array.isArray(row.finishes) && row.finishes.length ? row.finishes.join(", ") : "-"}</div>
      <div>收购数量：${row.qtyBuying.toLocaleString("zh-CN")} ｜ 零售库存：${row.qtyRetail.toLocaleString("zh-CN")}</div>
      <div>品相零售价：NM ${row.conditions?.nm_price || "-"} / EX ${row.conditions?.ex_price || "-"} / VG ${row.conditions?.vg_price || "-"} / G ${row.conditions?.g_price || "-"}</div>
    `;
    links.innerHTML = `
      <a href="${row.ckUrl}" target="_blank" rel="noreferrer">Card Kingdom</a>
      ${row.scryfallUrl ? `<a href="${row.scryfallUrl}" target="_blank" rel="noreferrer">Scryfall精确版本</a>` : ""}
    `;
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

function readControls() {
  state.source = els.typeSelect.value;
  state.query = els.searchInput.value;
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
  for (const el of [els.searchInput, els.typeSelect, els.setSelect, els.editionSelect, els.minPrice, els.foilOnly, els.withImageOnly, els.missingCnOnly, els.sortSelect]) {
    el.addEventListener("input", rerender);
    el.addEventListener("change", rerender);
  }
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
  els.resetButton.addEventListener("click", () => {
    els.searchInput.value = "";
    els.typeSelect.value = "cards";
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
}

async function init() {
  state.data = await loadData();
  const meta = state.data.meta;
  els.metaLine.textContent = `数据时间：${meta.cardKingdomCreatedAt} ｜ 中文未匹配 ${meta.missingCn.toLocaleString("zh-CN")} 张 ｜ 图片缺失 ${meta.missingImage.toLocaleString("zh-CN")} 张`;
  els.cardCount.textContent = meta.cards.toLocaleString("zh-CN");
  els.sealedCount.textContent = meta.sealed.toLocaleString("zh-CN");
  els.rate.textContent = Number(meta.usdCny).toFixed(4);
  populateSets();
  populateEditions();
  populateRecentSets();
  readControls();
  bindEvents();
  render();
}

init().catch((err) => {
  console.error(err);
  els.metaLine.textContent = "数据加载失败，请确认 data.json 与 index.html 在同一目录，并通过本地服务器打开。";
});

async function loadData() {
  const stamp = Date.now();
  if ("DecompressionStream" in window) {
    try {
      els.metaLine.textContent = "正在加载压缩数据...";
      const response = await fetch(`./data.json.gz?v=${stamp}`, { cache: "no-store" });
      if (!response.ok || !response.body) throw new Error(`gzip fetch failed: ${response.status}`);
      const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(stream).json();
    } catch (error) {
      console.warn("Falling back to uncompressed data.json", error);
    }
  }
  els.metaLine.textContent = "正在加载完整数据...";
  const response = await fetch(`./data.json?v=${stamp}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`data fetch failed: ${response.status}`);
  return await response.json();
}
