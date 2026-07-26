const state = { products: [], filtered: [], page: 1, pageSize: 50 };
const $ = (id) => document.getElementById(id);
const money = (value) => Number.isFinite(Number(value)) ? `¥${Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 2})}` : "—";
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);

function link(label, url) {
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}</a>` : "";
}

function applyFilters(resetPage = true) {
  const query = $("search").value.trim().toLowerCase();
  const category = $("category").value;
  const status = $("status").value;
  const sort = $("sort").value;
  state.filtered = state.products.filter((p) => {
    const haystack = [p.name_cn, p.name_en, p.title, p.sku, p.product_id, p.series, p.category, p.ck_name].join(" ").toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (category && p.category !== category) return false;
    if (status === "below-ck" && !p.below_ck_buylist) return false;
    if (status === "ck-exact" && p.ck_match_status !== "已精确连接") return false;
    if (status === "link-issue" && !p.external_link_issue) return false;
    if (status === "critical" && p.risk_level !== "严重问题") return false;
    if (status === "review" && p.risk_level !== "待复核") return false;
    if (status === "below-external" && !p.below_external) return false;
    return true;
  });
  const numeric = (field) => (a, b) => (Number(b[field]) || 0) - (Number(a[field]) || 0);
  if (sort === "ck-gap") state.filtered.sort(numeric("ck_buylist_gap"));
  if (sort === "price-desc") state.filtered.sort(numeric("selling_price"));
  if (sort === "price-asc") state.filtered.sort((a, b) => (Number(a.selling_price) || Infinity) - (Number(b.selling_price) || Infinity));
  if (sort === "stock") state.filtered.sort(numeric("stock"));
  if (resetPage) state.page = 1;
  renderRows();
}

function renderRows() {
  const totalPages = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const start = (state.page - 1) * state.pageSize;
  const rows = state.filtered.slice(start, start + state.pageSize);
  $("resultCount").textContent = `当前筛选 ${state.filtered.length.toLocaleString("zh-CN")} 条`;
  $("pageInfo").textContent = `第 ${state.page} / ${totalPages} 页`;
  $("prev").disabled = state.page <= 1;
  $("next").disabled = state.page >= totalPages;
  if (!rows.length) {
    $("rows").innerHTML = '<tr><td colspan="8" class="empty">没有符合条件的商品</td></tr>';
    return;
  }
  $("rows").innerHTML = rows.map((p) => {
    const exact = p.ck_match_status === "已精确连接";
    const riskClass = p.risk_level === "严重问题" ? "danger" : p.risk_level === "待复核" ? "review" : "";
    const refs = p.reference_links || {};
    return `<tr>
      <td><strong>${esc(p.name_cn || p.title || p.name_en || p.sku || "未命名商品")}</strong>${p.name_en ? `<small>${esc(p.name_en)}</small>` : ""}<small>${esc(p.sku || "")}</small><small>ID ${esc(p.product_id || "—")}</small></td>
      <td><strong>${esc(p.category || "—")}</strong><small>${esc(p.series || "")}</small></td>
      <td class="money">${esc(p.stock ?? "—")}</td>
      <td class="money">${money(p.cost)}</td>
      <td class="money">${money(p.selling_price)}${p.external_price_live_usd ? `<small>外网 $${Number(p.external_price_live_usd).toFixed(2)}</small>` : p.external_price ? `<small>表内参考 ${money(p.external_price)}</small>` : ""}</td>
      <td class="ck-price">${exact ? `<strong>${money(p.ck_cash_cny)}</strong><small>$${Number(p.ck_cash_usd || 0).toFixed(2)} · 收 ${esc(p.ck_qty_buying ?? "—")}</small><small>${esc(p.ck_name || "")}</small>${p.below_ck_buylist ? `<small class="gap">本店低 ${money(p.ck_buylist_gap)}</small>` : ""}` : `<span>—</span><small>${esc(p.ck_match_status || "无精确匹配")}</small>`}</td>
      <td><span class="badge ${riskClass}">${esc(p.risk_level || "正常")}</span>${p.below_ck_buylist ? '<span class="badge opportunity">低于 CK 回收价</span>' : ""}${p.external_link_issue ? `<small class="bad">外链：${esc(p.external_link_issue)}</small>` : ""}${(p.risk_reasons || []).filter((r) => r !== p.external_link_issue).slice(0, 2).map((r) => `<small>${esc(r)}</small>`).join("")}</td>
      <td><div class="links">${link("淘宝", p.taobao_url)}${link("TCG", refs.tcgplayer)}${link("原外链", !refs.tcgplayer && refs.original)}${link("CK 回收", refs.cardkingdom)}${link("CM", refs.cardmarket)}${link("eBay 已售", refs.ebay_sold)}</div></td>
    </tr>`;
  }).join("");
}

async function init() {
  try {
    const [metaResponse, productsResponse] = await Promise.all([fetch("./data/meta.json", {cache:"no-store"}), fetch("./data/products.json", {cache:"no-store"})]);
    if (!metaResponse.ok || !productsResponse.ok) throw new Error("数据请求失败");
    const [meta, products] = await Promise.all([metaResponse.json(), productsResponse.json()]);
    state.products = products.filter((product) => Number(product.stock) > 0);
    $("checkedAt").textContent = `检查于 ${meta.checked_at || "—"}`;
    $("sourceFile").textContent = meta.source_file || "电商总表";
    $("ckTime").textContent = `CK 快照 ${meta.ck_generated_at || "—"}`;
    $("productCount").textContent = state.products.length.toLocaleString("zh-CN");
    $("ckExact").textContent = state.products.filter((p) => p.ck_match_status === "已精确连接" && Number(p.ck_cash_usd) > 0).length.toLocaleString("zh-CN");
    $("ckBelow").textContent = state.products.filter((p) => p.below_ck_buylist).length.toLocaleString("zh-CN");
    $("linkIssues").textContent = state.products.filter((p) => p.external_link_issue).length.toLocaleString("zh-CN");
    [...new Set(state.products.map((p) => p.category).filter(Boolean))].sort().forEach((value) => $("category").insertAdjacentHTML("beforeend", `<option value="${esc(value)}">${esc(value)}</option>`));
    applyFilters();
  } catch (error) {
    $("rows").innerHTML = `<tr><td colspan="8" class="empty">数据载入失败：${esc(error.message)}</td></tr>`;
    $("checkedAt").textContent = "数据暂时不可用";
  }
}

["search", "category", "status", "sort"].forEach((id) => $(id).addEventListener(id === "search" ? "input" : "change", () => applyFilters()));
$("prev").addEventListener("click", () => { state.page -= 1; renderRows(); scrollTo({top: document.querySelector(".catalog").offsetTop - 80, behavior:"smooth"}); });
$("next").addEventListener("click", () => { state.page += 1; renderRows(); scrollTo({top: document.querySelector(".catalog").offsetTop - 80, behavior:"smooth"}); });
init();
