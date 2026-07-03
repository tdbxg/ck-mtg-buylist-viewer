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
  cardmarketLoaded: false,
};

const els = {
  metaLine: document.querySelector("#metaLine"),
  cardCount: document.querySelector("#cardCount"),
  sealedCount: document.querySelector("#sealedCount"),
  rate: document.querySelector("#rate"),
  searchInput: document.querySelector("#searchInput"),
  imageInput: document.querySelector("#imageInput"),
  imageDropZone: document.querySelector("#imageDropZone"),
  imageGuessInput: document.querySelector("#imageGuessInput"),
  imageGuessButton: document.querySelector("#imageGuessButton"),
  imageOcrStatus: document.querySelector("#imageOcrStatus"),
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
  const euPrice = state.source === "cards" ? bestCardmarketPrice(row) : null;
  const euCny = state.source === "cards" ? eurToCny(euPrice) : null;
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
      <div>Scryfall版本：<strong>${row.scryfallSetName || "-"}</strong>${row.scryfallSet ? ` (${String(row.scryfallSet).toUpperCase()}` : ""}${row.collectorNumber ? ` #${row.collectorNumber}` : ""}${row.scryfallSet ? ")" : ""}</div>
      ${skinName ? `<div>变体/皮肤：<strong>${skinName}</strong></div>` : ""}
      ${skinCnLine}
      ${ckNameLine}
      ${cnSourceLine}
      ${imageSourceLine}
      <div>SKU：${row.sku || "-"}</div>
      <div>稀有度：${row.rarity || "-"} ｜ 发售：${row.releasedAt || "-"} ｜ 工艺：${Array.isArray(row.finishes) && row.finishes.length ? row.finishes.join(", ") : "-"}</div>
      <div>状态：${row.activeBuying === false ? "暂不收购" : "当前收购"} ｜ 收购数量：${row.qtyBuying.toLocaleString("zh-CN")} ｜ 零售库存：${row.qtyRetail.toLocaleString("zh-CN")}</div>
      <div>品相零售价：NM ${row.conditions?.nm_price || "-"} / EX ${row.conditions?.ex_price || "-"} / VG ${row.conditions?.vg_price || "-"} / G ${row.conditions?.g_price || "-"}</div>
      <div>欧洲参考：<strong>${moneyEur(euPrice)}</strong>${euCny === null ? "" : ` / ${moneyCny(euCny)}`} ｜ CK现金-欧洲：<strong class="${spreadClass}">${spreadText}</strong></div>
    `;
    links.innerHTML = `
      <a href="${row.ckUrl}" target="_blank" rel="noreferrer">Card Kingdom</a>
      ${row.scryfallUrl ? `<a href="${row.scryfallUrl}" target="_blank" rel="noreferrer">Scryfall精确版本</a>` : ""}
      ${cardmarketLink}
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
  state.data = await loadData();
  await loadCardmarketData(state.data);
  const meta = state.data.meta;
  const generatedCn = Number(meta.generatedCnFilled || 0);
  const generatedLine = generatedCn ? ` ｜ 补充中文 ${generatedCn.toLocaleString("zh-CN")} 张` : "";
  const euLine = state.cardmarketLoaded ? ` ｜ 欧洲参考 ${Number(meta.cardmarketMatchedRows || 0).toLocaleString("zh-CN")} 条` : " ｜ 欧洲参考未加载";
  els.metaLine.textContent = `数据时间：${meta.cardKingdomCreatedAt} ｜ 中文未匹配 ${meta.missingCn.toLocaleString("zh-CN")} 张${generatedLine} ｜ 图片缺失 ${meta.missingImage.toLocaleString("zh-CN")} 张${euLine}`;
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
  if ("DecompressionStream" in window) {
    const response = await fetch(`./${baseName}.gz?v=${stamp}`, { cache: "no-store" });
    if (response.ok && response.body) {
      const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(stream).json();
    }
  }
  const response = await fetch(`./${baseName}?v=${stamp}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${baseName} fetch failed: ${response.status}`);
  return await response.json();
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
