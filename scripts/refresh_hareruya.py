#!/usr/bin/env python3
"""Refresh promoted listings plus an oldest-first rotation of exact products."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import update_hareruya_prices as legacy
from hareruya_capture import annotate, detail_prices, merge_listing, timestamp
from hareruya_movements import record_refresh


def key(row):
    return str(row["productId"]), row.get("language", "JP")


def capture_detail(old, at, retail=False):
    row = dict(old)
    lang = row.get("language", "JP")
    url = f"{legacy.BASE}/purchase/detail/{row['productId']}?lang={lang}"
    page = legacy.fetch(url)
    prices = detail_prices(page, lang, purchase=True)
    if "NM" not in prices:
        raise ValueError("target language/condition buy price missing; previous price retained")
    row.update({
        "buy": {lang: prices["NM"]}, "buyConditions": {lang: prices},
        "capturedAt": at, "buyCapturedAt": at, "buyUrl": url,
        "lastAttemptAt": at, "captureError": "", "source": "verifiedDetail",
        "buyStatus": "available" if prices["NM"] > 0 else "unavailable",
    })
    sale_error = ""
    if retail:
        try:
            sale_url = f"{legacy.BASE}/products/detail/{row['productId']}?lang={lang}"
            sales = detail_prices(legacy.fetch(sale_url), lang)
            if not sales:
                raise ValueError("target retail table missing")
            row.update({"sale": {lang: sales}, "saleCapturedAt": at, "retailVerified": True, "saleUrl": sale_url})
        except Exception as error:
            sale_error = f"{type(error).__name__}: {error}"
        row["saleCaptureError"] = sale_error
    return row


def refresh(detail_limit=240, workers=3, retail_limit=12, listings=True):
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = legacy.load_previous()
    items = {key(r): r for r in previous.get("items", []) if r.get("productId") != "70578"}
    failures = []
    listed, pages = legacy.purchase_listing_targets_all(failures) if listings else ([], 0)
    listed_keys = set()
    for row in listed:
        k = key(row)
        listed_keys.add(k)
        items[k] = merge_listing(items.get(k, {}), row, at)
    # Rotate every known product instead of only discovering new card names.
    pending = sorted((r for k, r in items.items() if k not in listed_keys), key=lambda r: (
        timestamp(r.get("lastAttemptAt") or r.get("buyCapturedAt") or r.get("capturedAt")), key(r)))[:detail_limit]
    refreshed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(capture_detail, r, at, i < retail_limit): r for i, r in enumerate(pending)}
        for future in as_completed(futures):
            old = futures[future]
            try:
                row = future.result()
                items[key(row)] = row
                refreshed += 1
            except Exception as error:
                items[key(old)] = {**old, "lastAttemptAt": at, "captureError": f"{type(error).__name__}: {error}"}
                failures.append(f"{old['productId']}|{old['language']}: {type(error).__name__}: {error}")
    successful = len(listed) + refreshed
    payload = annotate({
        "meta": {**previous.get("meta", {}), "lastAttemptAt": at,
                 "generatedAt": at if successful else previous.get("meta", {}).get("generatedAt"),
                 "lastSuccessfulAt": at if successful else previous.get("meta", {}).get("lastSuccessfulAt"),
                 "listingPages": pages, "listingItems": len(listed), "detailAttempted": len(pending),
                 "detailRefreshed": refreshed, "retainedItems": len(items) - len(listed) - refreshed,
                 "failures": failures, "status": "partial" if failures else "ok",
                 "refreshIntervalMinutes": 30, "source": "Hareruya exact purchase listings and language-specific product tables"},
        "items": sorted(items.values(), key=lambda r: (int(r["productId"]), r["language"])),
    }, at)
    if listings:
        try:
            payload["meta"]["jpyCny"] = json.loads(legacy.fetch(legacy.FX_URL))["rates"]["CNY"]
        except Exception as error:
            payload["meta"]["fxError"] = str(error)
    record_refresh(previous, payload, at)
    temp = legacy.OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(legacy.OUTPUT)
    print(json.dumps({k: v for k, v in payload["meta"].items() if k != "priorityProbe"}, ensure_ascii=False))
    return 0 if successful else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-limit", type=int, default=240)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retail-limit", type=int, default=12)
    parser.add_argument("--no-listings", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.detail_limit <= 1000 or not 1 <= args.workers <= 4 or args.retail_limit < 0:
        parser.error("invalid batch size")
    raise SystemExit(refresh(args.detail_limit, args.workers, args.retail_limit, not args.no_listings))
