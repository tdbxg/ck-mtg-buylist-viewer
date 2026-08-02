#!/usr/bin/env python3
"""Refresh configured Hareruya MTG product and buylist snapshots.

Only IDs in hareruya_targets.json are requested. A target must represent an
already-confirmed Hareruya print, so name-only matches are never invented.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "hareruya_targets.json"
OUTPUT = ROOT / "hareruya_prices.json"
FX_URL = "https://open.er-api.com/v6/latest/JPY"
BASE = "https://www.hareruyamtg.com/ja"
SITEMAP_URL = "https://www.hareruyamtg.com/sitemap.xml"
PURCHASE_LIST_URL = f"{BASE}/purchase/"
BUYLIST_TAGS = (633, 634, 635, 636, 637)
CONDITIONS = ("NM", "SP", "MP", "HP")
REQUEST_PAUSE_SECONDS = 0.7


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ck-mtg-price-radar/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def find_title(html: str) -> tuple[str, str]:
    match = re.search(r"<title>\s*(?:買取：)?\s*(.*?)\s*\|", html, re.S)
    raw = text(match.group(1)) if match else ""
    paired = re.search(r"《([^/》]+?)\s*/\s*([^》]+?)》", raw)
    if paired:
        return paired.group(1).strip(), paired.group(2).strip()
    if "/" in raw:
        ja, en = raw.split("/", 1)
        return ja.split("《")[-1].strip("《》 "), en.split("》", 1)[0].strip("《》 ")
    cleaned = raw.split("《")[-1].split("》", 1)[0].strip("《》 ")
    return cleaned, cleaned


def find_image(html: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if not re.search(r"(?:property|name)=[\"']og:image[\"']", tag, re.I):
            continue
        match = re.search(r"content=[\"']([^\"']+)[\"']", tag, re.I)
        if match:
            return unescape(match.group(1))
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        if not re.search(r"class=[\"'][^\"']*\bChangePhoto\b", tag, re.I):
            continue
        match = re.search(r"src=[\"']([^\"']+)[\"']", tag, re.I)
        if match:
            image = unescape(match.group(1))
            if not re.search(r"/(?:jyunbityuu|noimg)\.(?:jpg|png|webp)(?:\?|$)", image, re.I):
                return image
    return ""


def find_set(html: str) -> str:
    title = re.search(r"<title>\s*(?:買取：)?\s*(.*?)\s*\|", html, re.S)
    match = re.search(r"\[([^\]]+)\]", text(title.group(1))) if title else None
    return match.group(1) if match else ""


def find_listing_names(value: str) -> tuple[str, str]:
    """Keep the public listing text intact unless it contains a JP/EN pair."""
    raw = text(value)
    paired = re.search(r"《([^/》]+?)\s*/\s*([^》]+?)》", raw)
    if paired:
        return paired.group(1).strip(), paired.group(2).strip()
    return raw, raw


def purchase_listing_targets() -> list[dict]:
    """Extract exact buylist product IDs, images, and prices from one public page.

    The public sitemap intentionally contains only a small subset of current
    buylist products. The purchase list exposes many more exact product IDs,
    so it is the appropriate source for buy-only entries. Retail conditions are
    left blank until the product page has been separately verified.
    """
    listing = fetch(PURCHASE_LIST_URL)
    targets = []
    for block in re.findall(r"<li\b[^>]*class=[\"'][^\"']*\bitemList\b[^\"']*[\"'][^>]*>(.*?)</li>", listing, re.S | re.I):
        r"""
        detail = re.search(r'href=[\"\'](?:https://www\\.hareruyamtg\\.com)?/ja/purchase/detail/(\d+)\?lang=(JP|EN)[\"\'][^>]*class=[\"\'][^\"']*\bitemName\b', block, re.I)
        name = re.search(r'class=[\"\'][^\"']*\bitemName\b[^\"']*[\"'][^>]*>(.*?)</a>', block, re.S | re.I)
        image = re.search(r'data-original=[\"\']([^\"\']+)', block, re.I)
        """
        detail = re.search(r"href=[\"'](?:https://www\.hareruyamtg\.com)?/ja/purchase/detail/(\d+)\?lang=(JP|EN)[\"'][^>]*class=[\"'][^\"']*\bitemName\b", block, re.I)
        name = re.search(r"class=[\"'][^\"']*\bitemName\b[^\"']*[\"'][^>]*>(.*?)</a>", block, re.S | re.I)
        image = re.search(r"data-original=[\"']([^\"']+)", block, re.I)
        buy = re.search(r'itemDetail__price[^>]*>\s*[￥¥]\s*([\d,]+)', block, re.S)
        if not (detail and name and buy):
            continue
        name_ja, name_en = find_listing_names(name.group(1))
        image_url = unescape(image.group(1)).split("?", 1)[0] if image else ""
        targets.append({
            "productId": detail.group(1),
            "language": detail.group(2),
            "name": name_en or name_ja,
            "nameJa": name_ja,
            "image": image_url,
            "buyPrice": int(buy.group(1).replace(",", "")),
        })
    return targets


def listing_targets_from_html(listing: str) -> list[dict]:
    targets = []
    pattern = r"<li\b[^>]*class=[\"'][^\"']*\bitemList\b[^\"']*[\"'][^>]*>(.*?)</li>"
    for block in re.findall(pattern, listing, re.S | re.I):
        detail = re.search(r"href=[\"'](?:https://www\.hareruyamtg\.com)?/ja/purchase/detail/(\d+)\?lang=(JP|EN)[\"'][^>]*class=[\"'][^\"']*\bitemName\b", block, re.I)
        name = re.search(r"class=[\"'][^\"']*\bitemName\b[^\"']*[\"'][^>]*>(.*?)</a>", block, re.S | re.I)
        image = re.search(r"data-original=[\"']([^\"']+)", block, re.I)
        buy = re.search(r"itemDetail__price[^>]*>\s*[￥¥]\s*([\d,]+)", block, re.S)
        if not (detail and name and buy):
            continue
        listing_name = text(name.group(1))
        name_ja, name_en = find_listing_names(listing_name)
        set_match = re.search(r"\[([^\]]+)\]", listing_name)
        collector_match = re.search(r"\(([^)]+)\)", listing_name)
        targets.append({
            "productId": detail.group(1),
            "language": detail.group(2),
            "name": name_en or name_ja,
            "nameJa": name_ja,
            "set": set_match.group(1).strip() if set_match else "",
            "collectorNumber": collector_match.group(1).strip() if collector_match else "",
            "image": unescape(image.group(1)).split("?", 1)[0] if image else "",
            "buyPrice": int(buy.group(1).replace(",", "")),
        })
    return targets


def purchase_listing_targets_all() -> tuple[list[dict], int]:
    """Load every page from the public buylist categories and de-duplicate IDs."""
    category_urls = [
        f"{BASE}/purchase/search?tags={tag}&purchaseFlg=1&page=1"
        for tag in BUYLIST_TAGS
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        first_pages = list(pool.map(fetch, category_urls))

    page_urls = [PURCHASE_LIST_URL, *category_urls]
    extra_page_urls = []
    page_html = [fetch(PURCHASE_LIST_URL), *first_pages]
    for url, html in zip(category_urls, first_pages):
        last_page = max([int(value) for value in re.findall(r"page=(\d+)", html)] or [1])
        extra_page_urls.extend(f"{url.rsplit('=', 1)[0]}={page}" for page in range(2, last_page + 1))
    page_urls.extend(extra_page_urls)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, url): url for url in extra_page_urls}
        for future in as_completed(futures):
            page_html.append(future.result())

    unique = {}
    for html in page_html:
        for target in listing_targets_from_html(html):
            unique[(target["productId"], target["language"])] = target
    return sorted(unique.values(), key=lambda row: (int(row["productId"]), row["language"])), len(page_urls)


def table_fragment(html: str, language: str) -> str:
    marker = f'id="priceTable-{language}"'
    start = html.find(marker)
    if start < 0:
        return ""
    other = f'id="priceTable-{("EN" if language == "JP" else "JP")}"'
    end = html.find(other, start + len(marker))
    return html[start:end if end >= 0 else start + 20000]


def sale_prices(html: str, language: str) -> dict[str, int]:
    fragment = table_fragment(html, language)
    prices: dict[str, int] = {}
    for condition in CONDITIONS:
        match = re.search(
            rf">\s*{condition}\s*<(?:(?!>\s*(?:NM|SP|MP|HP)\s*<).)*?data-price=\"(\d+)\"",
            fragment,
            re.S,
        )
        if match:
            prices[condition] = int(match.group(1))
    return prices


def buy_price(html: str) -> int | None:
    match = re.search(r'itemDetail__stock[^>]*>\s*【買取価格】.*?itemDetail__price[^>]*>\s*[￥¥]\s*([\d,]+)', html, re.S)
    return int(match.group(1).replace(",", "")) if match else None


def load_previous() -> dict:
    if not OUTPUT.exists():
        return {"items": []}
    try:
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": []}


def discover_targets(existing: list[dict]) -> list[dict]:
    known = {(str(item.get("productId")), item.get("language", "JP")): item for item in existing}
    urls = re.findall(r"https://www\.hareruyamtg\.com/ja/purchase/detail/(\d+)\?lang=(JP|EN)", fetch(SITEMAP_URL))
    for product_id, language in urls:
        known.setdefault((product_id, language), {"productId": product_id, "language": language})
    targets = sorted(known.values(), key=lambda item: (int(item["productId"]), item.get("language", "JP")))
    TARGETS.write_text(json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return targets


def refresh_images_only() -> int:
    payload = load_previous()
    rows = payload.get("items", [])
    failures = []
    updated = 0
    limit = next((int(value.split("=", 1)[1]) for value in sys.argv if value.startswith("--image-limit=")), 0)
    pending = [row for row in rows if not row.get("image")]
    if limit:
        pending = pending[:limit]
    for row in pending:
        product_id = str(row.get("productId", ""))
        sale_url = row.get("saleUrl") or f"{BASE}/products/detail/{product_id}"
        try:
            image = find_image(fetch(sale_url))
            if not image:
                raise ValueError("missing product image in public page")
            row["image"] = image
            updated += 1
        except Exception as error:
            failures.append(f"{product_id}: {error}")
        time.sleep(REQUEST_PAUSE_SECONDS)
    meta = payload.setdefault("meta", {})
    meta["imageRefreshedAt"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    meta["images"] = sum(bool(row.get("image")) for row in rows)
    meta["imageFailures"] = failures
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(rows), "images": meta["images"], "updated": updated, "remaining": sum(not row.get("image") for row in rows), "failures": len(failures)}, ensure_ascii=False))
    return 0 if rows else 1


def refresh_listing_only() -> int:
    """Refresh all public buylist rows without guessing retail condition prices."""
    previous_payload = load_previous()
    previous = {(str(row.get("productId")), row.get("language", "JP")): row for row in previous_payload.get("items", [])}
    listed, listing_pages = purchase_listing_targets_all()
    items = []
    listed_keys = set()
    for row in listed:
        key = (str(row["productId"]), row["language"])
        listed_keys.add(key)
        old = previous.get(key, {})
        items.append({
            "productId": row["productId"],
            "name": row["name"],
            "nameJa": row["nameJa"],
            "set": row.get("set") or old.get("set", ""),
            "collectorNumber": row.get("collectorNumber") or old.get("collectorNumber", ""),
            "language": row["language"],
            "image": row["image"] or old.get("image", ""),
            "sale": old.get("sale", {}),
            "buy": {row["language"]: row["buyPrice"]},
            "saleUrl": old.get("saleUrl") or f"{BASE}/products/detail/{row['productId']}",
            "buyUrl": f"{BASE}/purchase/detail/{row['productId']}?lang={row['language']}",
            "capturedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "retailVerified": bool(old.get("sale", {}).get(row["language"])),
            "source": "publicListing",
        })
    # Preserve previously confirmed priority matches that are not in the
    # rotating public category pages.
    items.extend(old for key, old in previous.items() if key not in listed_keys)
    try:
        jpy_cny = float(json.loads(fetch(FX_URL))["rates"]["CNY"])
    except Exception:
        jpy_cny = previous_payload.get("meta", {}).get("jpyCny")
    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "items": len(items),
            "images": sum(bool(item.get("image")) for item in items),
            "verifiedRetailItems": sum(bool(item.get("retailVerified")) for item in items),
            "listingPages": listing_pages,
            "listingItems": len(listed),
            "retainedItems": len(items) - len(listed),
            "jpyCny": jpy_cny,
            "source": "Hareruya public purchase listing, with verified retail snapshots retained",
            "scope": "Public purchase listing; NM/SP/MP/HP only shown for separately verified product pages",
            "failures": [],
        },
        "items": items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TARGETS.write_text(json.dumps([{k: row[k] for k in ("productId", "language")} for row in items], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False))
    return 0 if items else 1


def main() -> int:
    if "--images-only" in sys.argv:
        return refresh_images_only()
    if "--listing-only" in sys.argv:
        return refresh_listing_only()
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    if "--discover" in sys.argv:
        targets = discover_targets(targets)
    previous_payload = load_previous()
    previous = {(str(row.get("productId")), row.get("language", "JP")): row for row in previous_payload.get("items", [])}
    if "--existing-only" in sys.argv:
        targets = [
            target for target in targets
            if (str(target.get("productId")), target.get("language", "JP")) in previous
        ]
    items = []
    failures = []
    for target in targets:
        product_id = str(target["productId"])
        sale_url = f"{BASE}/products/detail/{product_id}"
        buy_url = f"{BASE}/purchase/detail/{product_id}"
        try:
            sale_html = fetch(sale_url)
            time.sleep(REQUEST_PAUSE_SECONDS)
            buy_html = fetch(f"{buy_url}?lang={target.get('language', 'JP')}")
            time.sleep(REQUEST_PAUSE_SECONDS)
            name_ja, name_en = find_title(sale_html)
            language = target.get("language", "JP")
            item = {
                "productId": product_id,
                "name": name_en or name_ja,
                "nameJa": name_ja,
                "set": target.get("set") or find_set(sale_html),
                "collectorNumber": str(target.get("collectorNumber", "")),
                "language": language,
                "image": target.get("image") or find_image(sale_html),
                "sale": {language: sale_prices(sale_html, language)},
                "buy": {language: buy_price(buy_html)},
                "saleUrl": sale_url,
                "buyUrl": buy_url,
                "capturedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
            if not item["sale"][language] or item["buy"][language] is None:
                raise ValueError("missing sale or buy price in public page")
            items.append(item)
        except Exception as error:  # Preserve a verified previous snapshot instead of publishing blanks.
            old = previous.get((product_id, target.get("language", "JP")))
            if old:
                items.append(old)
            failures.append(f"{product_id}: {error}")

    try:
        jpy_cny = float(json.loads(fetch(FX_URL))["rates"]["CNY"])
    except Exception as error:
        jpy_cny = load_previous().get("meta", {}).get("jpyCny")
        failures.append(f"FX: {error}")

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "items": len(items),
            "images": sum(bool(item.get("image")) for item in items),
            "jpyCny": jpy_cny,
            "source": "Hareruya public product and purchase pages",
            "scope": "Previously verified public purchase-detail URLs" if "--existing-only" in sys.argv else "Public purchase-detail URLs listed in Hareruya sitemap",
            "failures": failures,
        },
        "items": items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False))
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
