#!/usr/bin/env python3
"""Refresh promoted listings plus an oldest-first rotation of exact products."""

import argparse
import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from threading import Event
from urllib.error import HTTPError

import update_hareruya_prices as legacy
from hareruya_capture import annotate, detail_metadata, detail_prices, detail_stocks, merge_listing, timestamp
from hareruya_movements import record_refresh
from hareruya_catalog_rotation import capture as capture_catalog, discover_partitions


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
    identity = detail_metadata(page, lang)
    identity["identityEvidence"].update({"url": url, "capturedAt": at})
    row.update(identity)
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
            sale_page = legacy.fetch(sale_url)
            sales = detail_prices(sale_page, lang)
            if not sales:
                raise ValueError("target retail table missing")
            sale_identity = detail_metadata(sale_page, lang)
            if sale_identity["variation"] != identity["variation"]:
                raise ValueError("retail print differs from the purchase page")
            row.update({"sale": {lang: sales}, "saleStock": {lang: detail_stocks(sale_page, lang)},
                        "saleCapturedAt": at, "retailVerified": True, "saleUrl": sale_url})
        except Exception as error:
            sale_error = f"{type(error).__name__}: {error}"
        row["saleCaptureError"] = sale_error
    return row


def refresh(detail_limit=240, workers=3, retail_limit=12, listings=True, catalog_pages=90):
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = legacy.load_previous()
    access = dict(previous.get("meta", {}).get("versionValidation", {}))
    source_blocked, retail_blocked = Event(), Event()
    if timestamp(access.get("sourceBlockedUntil")) > timestamp(at):
        source_blocked.set()
        listings = False
    previous_retail = access.get("retailBlockedUntil")
    if not previous_retail and any("403" in error or "429" in error for error in access.get("failures", [])):
        previous_retail = (timestamp(access.get("at")) + timedelta(hours=6)).isoformat(timespec="seconds")
    if timestamp(previous_retail) > timestamp(at):
        retail_blocked.set()
    items = {key(r): r for r in previous.get("items", []) if r.get("productId") != "70578"}
    failures = []
    listed, pages = [], 0
    if listings:
        try:
            if catalog_pages:
                listed = legacy.listing_targets_from_html(legacy.fetch(legacy.PURCHASE_LIST_URL))
                pages = 1
            else:
                listed, pages = legacy.purchase_listing_targets_all(failures)
        except Exception as error:
            failures.append(f"purchase listings: {type(error).__name__}: {error}")
    listed_keys = set()
    for row in listed:
        k = key(row)
        listed_keys.add(k)
        items[k] = merge_listing(items.get(k, {}), row, at)
    rotation = copy.deepcopy(previous.get("meta", {}).get("catalogRotation", {}))
    catalog_report = {}
    if listings and catalog_pages:
        try:
            if rotation.get("version") != 2 or not rotation.get("partitions"):
                rotation = discover_partitions(legacy.fetch(f"{legacy.BASE}/purchase/search?tags=633"))
            def checkpoint(rows, state, report):
                for row in rows:
                    listed_keys.add(key(row))
                    items[key(row)] = merge_listing(items.get(key(row), {}), row, at, source="englishCatalog")
                draft = annotate({"meta":{**previous.get("meta", {}), "catalogRotation":state,
                                          "catalogCapture":report, "lastAttemptAt":at}, "items":list(items.values())}, at)
                temp = legacy.OUTPUT.with_suffix(".tmp")
                temp.write_text(json.dumps(draft, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                temp.replace(legacy.OUTPUT)
            _, rotation, catalog_report = capture_catalog(rotation, catalog_pages, at, checkpoint)
            pages += catalog_report["pagesAttempted"]
            failures.extend(catalog_report["failures"])
            if catalog_report.get("blockedUntil"):
                source_blocked.set()
        except Exception as error:
            failures.append(f"English catalog: {type(error).__name__}: {error}")
    # Rotate every known product instead of only discovering new card names.
    pending = sorted((r for k, r in items.items() if k not in listed_keys and not source_blocked.is_set()), key=lambda r: (
        timestamp(r.get("lastAttemptAt") or r.get("buyCapturedAt") or r.get("capturedAt")), key(r)))[:detail_limit]
    refreshed = 0
    def guarded_detail(i, row):
        if source_blocked.is_set():
            return None
        try:
            result = capture_detail(row, at, i < retail_limit and not retail_blocked.is_set())
        except HTTPError as error:
            if error.code in (403, 429):
                source_blocked.set()
            raise
        if any(code in result.get("saleCaptureError", "") for code in ("403", "429")):
            retail_blocked.set()
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(guarded_detail, i, r): r for i, r in enumerate(pending)}
        for future in as_completed(futures):
            old = futures[future]
            try:
                row = future.result()
                if row is None:
                    continue
                items[key(row)] = row
                refreshed += 1
            except Exception as error:
                items[key(old)] = {**old, "lastAttemptAt": at, "captureError": f"{type(error).__name__}: {error}"}
                failures.append(f"{old['productId']}|{old['language']}: {type(error).__name__}: {error}")
    until = (timestamp(at) + timedelta(hours=6)).isoformat(timespec="seconds")
    if source_blocked.is_set():
        access["sourceBlockedUntil"] = access.get("sourceBlockedUntil") if timestamp(access.get("sourceBlockedUntil")) > timestamp(at) else until
    if retail_blocked.is_set():
        access["retailBlockedUntil"] = previous_retail if timestamp(previous_retail) > timestamp(at) else until
    successful = len(listed_keys) + refreshed
    payload = annotate({
        "meta": {**previous.get("meta", {}), "lastAttemptAt": at,
                 "generatedAt": at if successful else previous.get("meta", {}).get("generatedAt"),
                 "lastSuccessfulAt": at if successful else previous.get("meta", {}).get("lastSuccessfulAt"),
                 "listingPages": pages, "listingItems": len(listed_keys), "detailAttempted": len(pending),
                 "detailRefreshed": refreshed, "retainedItems": len(items) - len(listed_keys) - refreshed,
                 "catalogRotation":rotation, "catalogCapture":catalog_report,
                 "versionValidation":access,
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
    print(json.dumps({k:payload["meta"].get(k) for k in ("generatedAt", "items", "freshItems", "staleItems", "status", "listingPages", "listingItems", "catalogCapture", "failures")}, ensure_ascii=False))
    return 0 if successful or source_blocked.is_set() else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-limit", type=int, default=240)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retail-limit", type=int, default=12)
    parser.add_argument("--no-listings", action="store_true")
    parser.add_argument("--catalog-pages", type=int, default=90)
    args = parser.parse_args()
    if not 0 <= args.detail_limit <= 1000 or not 1 <= args.workers <= 4 or args.retail_limit < 0 or not 0 <= args.catalog_pages <= 600:
        parser.error("invalid batch size")
    raise SystemExit(refresh(args.detail_limit, args.workers, args.retail_limit, not args.no_listings, args.catalog_pages))
