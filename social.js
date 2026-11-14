const $ = (s) => document.querySelector(s);
const escapeText = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
function stored(key) { try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); } catch { return new Set(); } }
const state = { items: [], accounts: [], saved: stored("hareruya-x-saved-v1"), hidden: stored("hareruya-x-hidden-v1"), page: 1 };
function filtered() {
  const q = $("#postSearch").value.toLowerCase().trim();
  const days = Number($("#periodFilter").value);
  return state.items.filter((p) => !state.hidden.has(p.id)
    && (!q || `${p.text} ${p.shop} ${p.account}`.toLowerCase().includes(q))
    && (!$("#accountFilter").value || p.account === $("#accountFilter").value)
    && (!days || Date.now() - Date.parse(p.publishedAt) <= days * 86400000)
    && (!$("#savedOnly").checked || state.saved.has(p.id)));
}
function render() {
  const rows = filtered();
  const pages = Math.max(1, Math.ceil(rows.length / 24));
  state.page = Math.min(state.page, pages);
  $("#resultCount").textContent = `${rows.length} 条`;
  $("#socialPage").textContent = `${state.page} / ${pages}`;
  $("#previousPosts").disabled = state.page === 1;
  $("#nextPosts").disabled = state.page >= pages;
  $("#emptyPosts").hidden = rows.length > 0;
  $("#postList").innerHTML = rows.slice((state.page - 1) * 24, state.page * 24).map((p) => {
    const archived = Date.now() - Date.parse(p.publishedAt) > 7 * 86400000;
    const media = (p.images || []).filter((u) => { try { return new URL(u).hostname === "pbs.twimg.com"; } catch { return false; } });
    const handle = /^[A-Za-z0-9_]+$/.test(p.account) ? p.account : "";
    const href = `https://x.com/${handle}/status/${/^\d+$/.test(p.id) ? p.id : ""}`;
    return `<article class="post"><h2>${escapeText(p.shop)}</h2><time datetime="${escapeText(p.publishedAt)}">${escapeText(new Date(p.publishedAt).toLocaleString("zh-CN", {hour12:false}))}</time><p class="post-status">${archived ? "历史公告 · 当前价格须复核" : "近期回收公告"}${media.length ? " · 图片报价待核对" : ""}</p><p class="post-text">${escapeText(p.text)}</p><div class="post-media">${media.map((u) => `<a href="${escapeText(u)}" target="_blank" rel="noreferrer"><img src="${escapeText(u)}" loading="lazy" alt="${escapeText(p.shop)}回收表原图"></a>`).join("")}</div><div class="post-actions"><a href="${href}" target="_blank" rel="noreferrer">查看 X 原帖 ↗</a><button data-save="${p.id}" title="${state.saved.has(p.id) ? "取消收藏" : "收藏"}" aria-label="${state.saved.has(p.id) ? "取消收藏" : "收藏"}">${state.saved.has(p.id) ? "★" : "☆"}</button><button data-hide="${p.id}" title="移除此公告" aria-label="移除此公告">×</button></div></article>`;
  }).join("");
}
async function load() {
  $("#reloadPosts").disabled = true;
  try {
    const responses = await Promise.all([fetch(`./social_buylist.json?v=${Date.now()}`, {cache:"no-store"}), fetch(`./social_sources.json?v=${Date.now()}`, {cache:"no-store"})]);
    if (responses.some((r) => !r.ok)) throw new Error("公告数据暂不可用");
    const [payload, config] = await Promise.all(responses.map((r) => r.json()));
    state.items = payload.items || []; state.accounts = config.accounts || [];
    $("#sourceTime").textContent = `最近检查 ${new Date(payload.meta.lastCheckedAt).toLocaleString("zh-CN", {hour12:false})} · 每小时收集${payload.meta.latestPublishedAt ? ` · 最新原帖 ${new Date(payload.meta.latestPublishedAt).toLocaleString("zh-CN", {hour12:false})}` : ""}`;
    $("#postCount").textContent = state.items.length;
    $("#accountCount").textContent = state.accounts.length;
    const failedAccounts = new Set((payload.meta.failures || []).map((f) => f.account)).size;
    $("#coverage").textContent = `${payload.meta.coverageNote}${failedAccounts ? ` 本次 ${failedAccounts} 个账号部分读取失败，保留上次存档。` : ""}`;
    const selected = $("#accountFilter").value;
    $("#accountFilter").replaceChildren(new Option("晴屋官方主账号", ""), ...state.accounts.map((a) => new Option(a.label, a.handle)));
    $("#accountFilter").value = selected;
    $("#accountList").innerHTML = state.accounts.map((a) => `<a href="https://x.com/${encodeURIComponent(a.handle)}" target="_blank" rel="noreferrer">${escapeText(a.label)} @${escapeText(a.handle)}</a>`).join("");
    render();
  } catch (error) { $("#sourceTime").textContent = error.message; }
  finally { $("#reloadPosts").disabled = false; }
}
["postSearch", "accountFilter", "periodFilter", "savedOnly"].forEach((id) => $("#" + id).addEventListener("input", () => { state.page = 1; render(); }));
$("#reloadPosts").addEventListener("click", load);
$("#previousPosts").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); render(); });
$("#nextPosts").addEventListener("click", () => { state.page++; render(); });
$("#postList").addEventListener("click", (e) => {
  const saved = e.target.closest("[data-save]"); const hidden = e.target.closest("[data-hide]");
  if (saved) { const id = saved.dataset.save; state.saved.has(id) ? state.saved.delete(id) : state.saved.add(id); localStorage.setItem("hareruya-x-saved-v1", JSON.stringify([...state.saved])); }
  if (hidden) { state.hidden.add(hidden.dataset.hide); localStorage.setItem("hareruya-x-hidden-v1", JSON.stringify([...state.hidden])); }
  if (saved || hidden) render();
});
$("#exportPosts").addEventListener("click", () => {
  const cell = (s) => '"' + String(/^[=+@-]/.test(String(s)) ? "'" + s : s).replaceAll('"', '""') + '"';
  const csv = [["店铺", "账号", "原帖时间", "回收公告", "原帖链接", "图片"], ...filtered().map((p) => [p.shop, p.account, p.publishedAt, p.text, p.url, (p.images || []).join(" ")])].map((r) => r.map(cell).join(",")).join("\r\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + csv], {type:"text/csv;charset=utf-8"})); a.download = "晴屋-X回收公告.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 500);
});
load();
