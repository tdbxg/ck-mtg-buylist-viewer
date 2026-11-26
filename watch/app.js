const WATCHLIST_KEY = "ck-retail-watchlist-v1";
const SNAPSHOTS_KEY = "ck-retail-watch-snapshots-v1";
const EVENTS_KEY = "ck-retail-watch-events-v1";
const DEFAULTS_VERSION_KEY = "ck-retail-watch-defaults-version";
const EVENT_LIMIT = 200;

const state = {
  payload: null,
  cards: [],
  bySku: new Map(),
  byPrint: new Map(),
  imagesBySku: new Map(),
  watchlist: new Map(),
  snapshots: {},
  events: [],
  filter: "all",
  changedSkus: new Set(),
  loading: true,
};

const els = {
  trackedCount: document.querySelector("#trackedCount"),
  availableCount: document.querySelector("#availableCount"),
  changedCount: document.querySelector("#changedCount"),
  sourceDot: document.querySelector("#sourceDot"),
  sourceStatus: document.querySelector("#sourceStatus"),
  sourceMeta: document.querySelector("#sourceMeta"),
  refreshButton: document.querySelector("#refreshButton"),
  notificationButton: document.querySelector("#notificationButton"),
  loadFullButton: document.querySelector("#loadFullButton"),
  searchInput: document.querySelector("#searchInput"),
  searchHint: document.querySelector("#searchHint"),
  searchResults: document.querySelector("#searchResults"),
  watchGrid: document.querySelector("#watchGrid"),
  emptyState: document.querySelector("#emptyState"),
  emptySearchButton: document.querySelector("#emptySearchButton"),
  exportButton: document.querySelector("#exportButton"),
  importButton: document.querySelector("#importButton"),
  importInput: document.querySelector("#importInput"),
  clearEventsButton: document.querySelector("#clearEventsButton"),
  eventList: document.querySelector("#eventList"),
  eventEmpty: document.querySelector("#eventEmpty"),
  toast: document.querySelector("#toast"),
};

function readJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key));
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

function saveState() {
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...state.watchlist.values()]));
  localStorage.setItem(SNAPSHOTS_KEY, JSON.stringify(state.snapshots));
  localStorage.setItem(EVENTS_KEY, JSON.stringify(state.events.slice(0, EVENT_LIMIT)));
}

function normalize(value) {
  return String(value || "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatUsd(value) {
  const amount = Number(value || 0);
  return amount > 0 ? amount.toLocaleString("en-US", { style: "currency", currency: "USD" }) : "—";
}

function formatTime(value) {
  if (!value) return "未知";
  const date = new Date(value.includes?.("T") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

function debounce(fn, wait = 160) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function expandPayload(payload) {
  const fields = payload.fields || [];
  const cards = (payload.cards || []).map((packed) => {
    if (!Array.isArray(packed)) return packed;
    const card = {};
    fields.forEach((field, index) => { card[field] = packed[index]; });
    return card;
  });
  for (const card of cards) {
    card.qtyRetail = Math.max(0, Number(card.qtyRetail || 0));
    card.retailUsd = Number(card.retailUsd || 0);
    card.search = normalize([
      card.name, card.cn, card.edition, card.variation, card.scryfallSet,
      card.scryfallSetName, card.collectorNumber, card.sku,
    ].filter(Boolean).join(" "));
  }
  return { ...payload, cards };
}

async function loadGzipJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`库存目录请求失败 (${response.status})`);
  if ("DecompressionStream" in window && response.body) {
    try {
      const stream = response.clone().body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(stream).json();
    } catch (error) {
      console.warn("Native gzip decode failed; trying pako", error);
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
  if (window.pako?.inflate) return;
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "../pako_inflate.min.js?v=20260706-pako";
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
  if (!window.pako?.inflate) throw new Error("本地 gzip 解压库未加载");
}

function cardIdentity(card) {
  const print = [
    card.scryfallSet ? String(card.scryfallSet).toUpperCase() : "",
    card.collectorNumber ? `#${card.collectorNumber}` : "",
    card.foil ? "闪" : "非闪",
  ].filter(Boolean).join(" · ");
  return `${card.edition || card.scryfallSetName || "未知系列"}${card.variation ? ` · ${card.variation}` : ""}${print ? ` · ${print}` : ""}`;
}

function cardSnapshot(card, old = {}) {
  return {
    sourceAt: state.payload?.meta?.sourceAt || "",
    qty: Math.max(0, Number(card?.qtyRetail || 0)),
    price: Number(card?.retailUsd || 0),
    available: Number(card?.qtyRetail || 0) > 0 && Number(card?.retailUsd || 0) > 0,
    checkedAt: new Date().toISOString(),
    firstSeenAt: old.firstSeenAt || new Date().toISOString(),
  };
}

function eventForChange(card, previous, current) {
  const base = {
    sku: card.sku,
    at: new Date().toISOString(),
    sourceAt: current.sourceAt,
    name: card.name || card.sku,
    identity: cardIdentity(card),
  };
  if (!previous.available && current.available) {
    return { ...base, type: "listed", title: "已上架", detail: `库存 ${current.qty} · ${formatUsd(current.price)}` };
  }
  if (previous.available && !current.available) {
    return { ...base, type: "soldout", title: "已售罄", detail: `此前库存 ${previous.qty}` };
  }
  if (current.qty > previous.qty) {
    return { ...base, type: "restock", title: "补货", detail: `库存 ${previous.qty} → ${current.qty}` };
  }
  if (current.qty < previous.qty) {
    return { ...base, type: "stock", title: "库存减少", detail: `库存 ${previous.qty} → ${current.qty}` };
  }
  if (current.price !== previous.price) {
    return { ...base, type: "price", title: "价格变化", detail: `${formatUsd(previous.price)} → ${formatUsd(current.price)}` };
  }
  return null;
}

function reconcile() {
  state.changedSkus.clear();
  const sourceAt = state.payload?.meta?.sourceAt || "";
  for (const [originalSku, saved] of [...state.watchlist]) {
    let sku = originalSku;
    const card = exactCardFor(saved);
    if (!card) continue;
    if (card.sku !== sku) {
      const previousSnapshot = state.snapshots[card.sku] || state.snapshots[sku];
      const existing = state.watchlist.get(card.sku);
      state.watchlist.delete(sku);
      delete state.snapshots[sku];
      sku = card.sku;
      state.watchlist.set(sku, { ...saved, ...existing, ...identitySnapshot(card) });
      if (previousSnapshot) state.snapshots[sku] = previousSnapshot;
    }
    state.watchlist.set(sku, { ...saved, ...identitySnapshot(card) });
    const previous = state.snapshots[sku];
    const current = cardSnapshot(card, previous || {});
    if (previous && sourceAt && previous.sourceAt && previous.sourceAt !== sourceAt) {
      const event = eventForChange(card, previous, current);
      if (event && !state.events.some((item) => item.sku === sku && item.sourceAt === sourceAt && item.type === event.type)) {
        state.events.unshift(event);
        state.changedSkus.add(sku);
        notify(event);
      }
    }
    state.snapshots[sku] = current;
  }
  state.events = state.events.slice(0, EVENT_LIMIT);
  saveState();
}

function identitySnapshot(card) {
  return {
    sku: card.sku,
    scryfallId: card.scryfallId || "",
    name: card.name || card.sku,
    cn: card.cn || "",
    edition: card.edition || "",
    variation: card.variation || "",
    foil: Boolean(card.foil),
    scryfallSet: card.scryfallSet || "",
    scryfallSetName: card.scryfallSetName || "",
    collectorNumber: card.collectorNumber || "",
    ckUrl: card.ckUrl || "",
    image: card.image || "",
  };
}

function printKey(card) {
  const scryfallId = String(card?.scryfallId || "").trim();
  return scryfallId ? `${scryfallId}:${card?.foil ? "foil" : "nonfoil"}` : "";
}

function exactCardFor(item) {
  const sku = String(item?.sku || "").trim();
  const key = printKey(item);
  return (sku && state.bySku.get(sku)) || (key && state.byPrint.get(key)) || null;
}

function alreadyWatchingPrint(item) {
  const key = printKey(item);
  return key && [...state.watchlist.values()].some((saved) => printKey(saved) === key);
}

async function applyDefaultWatchlist() {
  const response = await fetch(`./defaults.json?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) return { added: 0, groups: 0 };
  const defaults = await response.json();
  const version = Number(defaults.version || 0);
  const appliedVersion = Number(localStorage.getItem(DEFAULTS_VERSION_KEY) || 0);
  const groups = [];
  if (Array.isArray(defaults.items)) {
    groups.push({ label: defaults.label || "默认监测清单", items: defaults.items });
  }
  if (Array.isArray(defaults.groups)) groups.push(...defaults.groups);
  if (!version || appliedVersion >= version || !groups.some((group) => Array.isArray(group.items))) {
    return { added: 0, groups: 0 };
  }
  for (const group of defaults.replaceDefaultGroups || []) {
    for (const [sku, item] of state.watchlist) {
      if (item.group === group) {
        state.watchlist.delete(sku);
        delete state.snapshots[sku];
      }
    }
  }
  let added = 0;
  const addedGroups = new Set();
  for (const group of groups) {
    if (!Array.isArray(group.items)) continue;
    for (const item of group.items) {
      const declaredSku = String(item?.sku || "").trim();
      const card = exactCardFor(item);
      const sku = String(card?.sku || declaredSku).trim();
      if (!sku || state.watchlist.has(sku) || alreadyWatchingPrint(item)) continue;
      const target = card || { ...item, sku, qtyRetail: 0, retailUsd: 0, missing: true };
      state.watchlist.set(sku, { ...identitySnapshot(target), group: group.label || "默认监测清单" });
      state.snapshots[sku] = cardSnapshot(target, state.snapshots[sku] || {});
      added += 1;
      addedGroups.add(group.label || "默认监测清单");
    }
  }
  localStorage.setItem(DEFAULTS_VERSION_KEY, String(version));
  return { added, groups: addedGroups.size };
}

function notify(event) {
  if (!(event.type === "listed" || event.type === "restock")) return;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  new Notification(`CK ${event.title}：${event.name}`, { body: `${event.identity}\n${event.detail}` });
}

function conditionText(card) {
  const conditions = card.conditions || {};
  const parts = [
    ["NM", conditions.nm_qty], ["EX", conditions.ex_qty],
    ["VG", conditions.vg_qty], ["G", conditions.g_qty],
  ].filter(([, qty]) => Number(qty || 0) > 0).map(([label, qty]) => `${label} ${qty}`);
  return parts.length ? `品相库存（完整快照）：${parts.join(" · ")}` : "品相库存：暂无可用明细";
}

// Curated exact-print images are separate from the hourly CK stock snapshot.
// Never infer artwork from a name alone or override a conflicting print ID.
function withVerifiedImage(card) {
  const art = state.imagesBySku.get(String(card.sku));
  if (!art || (card.scryfallId && card.scryfallId !== art.scryfallId) ||
      normalize(card.name) !== normalize(art.name) || Boolean(card.foil) !== art.foil ||
      normalize(card.scryfallSet) !== art.scryfallSet ||
      String(card.collectorNumber) !== art.collectorNumber) return card;
  return { ...card, scryfallId: art.scryfallId, image: art.image };
}

function currentCard(saved) {
  const card = exactCardFor(saved);
  return withVerifiedImage(card ? { ...saved, ...card, group: saved.group || "" } : { ...saved, qtyRetail: 0, retailUsd: 0, missing: true });
}

function renderSearch() {
  const query = normalize(els.searchInput.value);
  if (query.length < 2 || state.loading) {
    els.searchResults.hidden = true;
    els.searchResults.replaceChildren();
    return;
  }
  const terms = query.split(" ").filter(Boolean);
  const results = state.cards
    .filter((card) => terms.every((term) => card.search.includes(term)))
    .sort((a, b) => Number(b.qtyRetail > 0) - Number(a.qtyRetail > 0) || b.qtyRetail - a.qtyRetail || a.name.localeCompare(b.name))
    .slice(0, 40);

  if (!results.length) {
    els.searchResults.innerHTML = '<div class="search-row"><div></div><div class="card-title"><strong>没有找到精确版本</strong><small>可尝试英文牌名、CK 系列名或 SKU。</small></div></div>';
    els.searchResults.hidden = false;
    return;
  }
  els.searchResults.innerHTML = results.map((card) => {
    const added = state.watchlist.has(card.sku);
    const available = card.qtyRetail > 0 && card.retailUsd > 0;
    return `
      <article class="search-row">
        ${card.image ? `<img class="thumb" src="${escapeHtml(card.image)}" alt="" loading="lazy">` : '<span class="thumb"></span>'}
        <div class="card-title">
          <strong>${escapeHtml(card.name)}${card.cn ? ` · ${escapeHtml(card.cn)}` : ""}</strong>
          <small>${escapeHtml(cardIdentity(card))} · SKU ${escapeHtml(card.sku)}</small>
        </div>
        <div class="stock-inline ${available ? "" : "out"}"><strong>${available ? `库存 ${card.qtyRetail}` : "暂时无货"}</strong><small>${formatUsd(card.retailUsd)}</small></div>
        <button class="add-button ${added ? "added" : ""}" type="button" data-add="${escapeHtml(card.sku)}" ${added ? "disabled" : ""}>${added ? "已监测" : "＋ 监测"}</button>
      </article>`;
  }).join("");
  els.searchResults.hidden = false;
  els.searchHint.textContent = `显示 ${results.length} 个匹配版本；请核对系列、编号、闪卡和 SKU。`;
}

function renderWatchlist() {
  const rows = [...state.watchlist.values()].map(currentCard).filter((card) => {
    const available = card.qtyRetail > 0 && card.retailUsd > 0;
    if (state.filter === "available") return available;
    if (state.filter === "missing") return !available;
    if (state.filter === "changed") return state.changedSkus.has(card.sku);
    return true;
  }).sort((a, b) => Number(state.changedSkus.has(b.sku)) - Number(state.changedSkus.has(a.sku)) || Number(b.qtyRetail > 0) - Number(a.qtyRetail > 0) || a.name.localeCompare(b.name));

  els.watchGrid.innerHTML = rows.map((card) => {
    const available = card.qtyRetail > 0 && card.retailUsd > 0;
    const changed = state.changedSkus.has(card.sku);
    const snapshot = state.snapshots[card.sku] || {};
    return `
      <article class="watch-card">
        <div class="watch-art">
          ${card.image ? `<img src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name)}" loading="lazy">` : '<span class="art-placeholder">暂无此版本卡图<br>仍按精确版本监测</span>'}
          ${card.foil ? '<span class="foil-badge">FOIL</span>' : ""}
        </div>
        <div class="watch-body">
          <div class="watch-top">
            <div><span class="status-badge ${available ? "" : "out"} ${changed ? "changed" : ""}">${card.missing ? "目录中未找到" : available ? "已上架" : "暂时无货"}</span></div>
            <button class="remove-button" type="button" data-remove="${escapeHtml(card.sku)}" aria-label="移除 ${escapeHtml(card.name)}">移除</button>
          </div>
          <h3 class="watch-name">${escapeHtml(card.name)}</h3>
          ${card.group ? `<p class="watch-group">${escapeHtml(card.group)}</p>` : ""}
          <p class="watch-cn">${escapeHtml(card.cn || "")}</p>
          <p class="identity">${escapeHtml(cardIdentity(card))}<br><code>SKU ${escapeHtml(card.sku)}</code></p>
          <div class="stock-panel">
            <div><small>CK 当前售价</small><strong>${formatUsd(card.retailUsd)}</strong></div>
            <div><small>聚合库存</small><strong>${card.qtyRetail > 0 ? card.qtyRetail : "0"}</strong></div>
          </div>
          <p class="condition-line">${escapeHtml(conditionText(card))}</p>
          <div class="watch-actions">
            ${card.ckUrl ? `<a href="${escapeHtml(card.ckUrl)}" target="_blank" rel="noreferrer">打开 CK ↗</a>` : ""}
            <span class="muted">加入于 ${formatTime(snapshot.firstSeenAt)}</span>
          </div>
        </div>
      </article>`;
  }).join("");

  const noWatchItems = state.watchlist.size === 0;
  els.emptyState.hidden = !noWatchItems;
  els.watchGrid.hidden = noWatchItems;
  if (!noWatchItems && rows.length === 0) {
    els.watchGrid.hidden = false;
    els.watchGrid.innerHTML = '<div class="empty-state"><h3>当前筛选没有结果</h3><p>切换到“全部”查看完整监测清单。</p></div>';
  }
}

function renderEvents() {
  els.eventList.innerHTML = state.events.slice(0, 60).map((event) => `
    <article class="event ${escapeHtml(event.type)}">
      <span class="event-dot"></span>
      <div><strong>${escapeHtml(event.title)} · ${escapeHtml(event.name)}</strong><p>${escapeHtml(event.identity)} · ${escapeHtml(event.detail)}</p></div>
      <time datetime="${escapeHtml(event.at)}">${formatTime(event.sourceAt || event.at)}</time>
    </article>`).join("");
  els.eventEmpty.hidden = state.events.length > 0;
}

function renderStats() {
  const cards = [...state.watchlist.values()].map(currentCard);
  els.trackedCount.textContent = String(state.watchlist.size);
  els.availableCount.textContent = String(cards.filter((card) => card.qtyRetail > 0 && card.retailUsd > 0).length);
  els.changedCount.textContent = String(state.changedSkus.size);
}

function render() {
  renderStats();
  renderWatchlist();
  renderEvents();
  renderSearch();
  updateNotificationButton();
}

function addCard(sku) {
  const card = state.bySku.get(sku);
  if (!card || state.watchlist.has(sku)) return;
  state.watchlist.set(sku, identitySnapshot(card));
  state.snapshots[sku] = cardSnapshot(card, {});
  saveState();
  render();
  showToast(`已监测：${card.name} · ${cardIdentity(card)}`);
}

function removeCard(sku) {
  const card = state.watchlist.get(sku);
  if (!card) return;
  state.watchlist.delete(sku);
  delete state.snapshots[sku];
  saveState();
  render();
  showToast(`已移除：${card.name || sku}`);
}

function exportWatchlist() {
  const payload = {
    version: 1,
    exportedAt: new Date().toISOString(),
    sourceAt: state.payload?.meta?.sourceAt || "",
    items: [...state.watchlist.values()],
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `ck_retail_watchlist_${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function importWatchlist(file) {
  const payload = JSON.parse(await file.text());
  const items = Array.isArray(payload) ? payload : payload.items;
  if (!Array.isArray(items)) throw new Error("文件中没有 items 数组");
  let added = 0;
  for (const item of items) {
    const card = exactCardFor(item);
    const sku = String(card?.sku || item?.sku || "").trim();
    if (!sku || state.watchlist.has(sku)) continue;
    state.watchlist.set(sku, card ? identitySnapshot(card) : item);
    if (card) state.snapshots[sku] = cardSnapshot(card, state.snapshots[sku] || {});
    added += 1;
  }
  saveState();
  render();
  showToast(`已导入 ${added} 张监测牌`);
}

function showToast(message, error = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", error);
  els.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 3200);
}

function updateNotificationButton() {
  if (!("Notification" in window)) {
    els.notificationButton.textContent = "浏览器不支持提醒";
    els.notificationButton.disabled = true;
    return;
  }
  const labels = { granted: "上架提醒已开启", denied: "提醒已被浏览器阻止", default: "开启上架提醒" };
  els.notificationButton.textContent = labels[Notification.permission];
  els.notificationButton.disabled = Notification.permission === "denied";
}

async function requestNotifications() {
  if (!("Notification" in window)) return;
  const result = await Notification.requestPermission();
  updateNotificationButton();
  showToast(result === "granted" ? "上架与补货提醒已开启" : "未获得通知权限", result !== "granted");
}

async function loadCatalog() {
  state.loading = true;
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "载入中…";
  els.sourceDot.className = "source-dot loading";
  els.sourceStatus.textContent = "正在载入 CK 库存目录…";
  try {
    state.payload = expandPayload(await loadGzipJson("./catalog.json.gz"));
    try {
      const imagesResponse = await fetch("./images.json?v=20260905", { cache: "no-store" });
      if (!imagesResponse.ok) throw new Error("图片索引载入失败");
      const images = await imagesResponse.json();
      state.imagesBySku = new Map(images.items.map((item) => [item.sku, item]));
    } catch (error) {
      console.warn("补充卡图暂不可用，继续载入库存", error);
    }
    state.cards = state.payload.cards.map(withVerifiedImage);
    state.bySku = new Map(state.cards.map((card) => [String(card.sku), card]));
    state.byPrint = new Map();
    for (const card of state.cards) {
      const key = printKey(card);
      if (key && !state.byPrint.has(key)) state.byPrint.set(key, card);
    }
    state.loading = false;
    const defaultsResult = await applyDefaultWatchlist();
    reconcile();
    const meta = state.payload.meta || {};
    els.sourceDot.className = "source-dot";
    els.sourceStatus.textContent = `CK 状态采样：${formatTime(meta.sourceAt)}`;
    els.sourceMeta.textContent = `${Number(meta.cards || state.cards.length).toLocaleString("zh-CN")} 个精确版本 · ${Number(meta.activeRetailRows || 0).toLocaleString("zh-CN")} 个当前在售 · 页面载入 ${formatTime(new Date().toISOString())}`;
    els.searchHint.textContent = "输入至少 2 个字符。添加前请核对系列、编号、闪卡和 SKU。";
    render();
    if (defaultsResult.added) showToast(`已加入 ${defaultsResult.groups} 个新分组：${defaultsResult.added} 个精确版本`);
  } catch (error) {
    console.error(error);
    state.loading = false;
    els.sourceDot.className = "source-dot error";
    els.sourceStatus.textContent = "库存目录载入失败";
    els.sourceMeta.textContent = `${error.message}。请通过本地服务器打开，或等待监测目录生成。`;
    els.loadFullButton.hidden = false;
    showToast(error.message, true);
  } finally {
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "刷新状态";
  }
}

state.watchlist = new Map(readJson(WATCHLIST_KEY, []).filter((item) => item?.sku).map((item) => [String(item.sku), item]));
state.snapshots = readJson(SNAPSHOTS_KEY, {});
state.events = readJson(EVENTS_KEY, []);

els.searchInput.addEventListener("input", debounce(renderSearch));
els.searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const button = els.searchResults.querySelector("[data-add]:not(:disabled)");
    if (button) addCard(button.dataset.add);
  }
});
els.searchResults.addEventListener("click", (event) => {
  const button = event.target.closest("[data-add]");
  if (button) addCard(button.dataset.add);
});
els.watchGrid.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove]");
  if (button) removeCard(button.dataset.remove);
});
document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
  renderWatchlist();
}));
els.emptySearchButton.addEventListener("click", () => { els.searchInput.focus(); window.scrollTo({ top: 230, behavior: "smooth" }); });
els.refreshButton.addEventListener("click", loadCatalog);
els.loadFullButton.addEventListener("click", loadCatalog);
els.notificationButton.addEventListener("click", requestNotifications);
els.exportButton.addEventListener("click", exportWatchlist);
els.importButton.addEventListener("click", () => els.importInput.click());
els.importInput.addEventListener("change", async () => {
  const file = els.importInput.files?.[0];
  if (!file) return;
  try { await importWatchlist(file); } catch (error) { showToast(`导入失败：${error.message}`, true); }
  els.importInput.value = "";
});
els.clearEventsButton.addEventListener("click", () => {
  state.events = [];
  saveState();
  renderEvents();
  showToast("变化记录已清空");
});

render();
loadCatalog();
