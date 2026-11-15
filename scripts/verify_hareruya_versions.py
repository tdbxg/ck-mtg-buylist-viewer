"""Rotate exact English product-title and purchasable NM-stock verification."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import gzip
import json
from threading import Event
import time
from urllib.error import HTTPError

import update_hareruya_prices as legacy
from hareruya_capture import annotate, timestamp
from hareruya_movements import record_refresh
from refresh_hareruya import capture_detail, key
from build_hareruya_opportunities import decimal, fresh, hareruya_identity, normalized, read_json, SET_ALIASES


def priority_rows(rows, metadata, fx, at, limit):
    quotes = {}
    rate = decimal(fx.get("rates", {}).get("JPY"))
    for c in metadata.get("cards", []):
        k = (normalized(c.get("name")), c.get("scryfallSet", "").lower())
        value = quotes.setdefault(k, {"retail": [], "cash": []})
        price = decimal(c.get("conditions", {}).get("nm_price"))
        if price > 0 and decimal(c.get("conditions", {}).get("nm_qty")) > 0:
            value["retail"].append(price * rate)
        if decimal(c.get("cashUsd")) > 0 and c.get("activeBuying"):
            value["cash"].append(decimal(c["cashUsd"]) * rate)
    pending = []
    for r in rows:
        if r.get("language") != "EN":
            continue
        if r.get("variation") and hareruya_identity(r)[1] in {"specialFinish", "setUnknown"}:
            continue
        raw_set = r.get("set", "").split("-", 1)[0]
        code = SET_ALIASES.get(raw_set, raw_set.lower())
        q = quotes.get((normalized(r.get("name")), code))
        if not q or not (q["retail"] or q["cash"]):
            continue
        buy = decimal(r.get("buy", {}).get("EN"))
        # Approximate name/edition matches prioritize requests only, never published prices.
        forward = bool(q["retail"] and buy > min(q["retail"]))
        reverse = bool(q["cash"] and buy > 0 and buy < max(q["cash"]) * decimal("0.7"))
        priority = 0 if forward or reverse else 1
        recent = fresh(r.get("lastIdentityAttemptAt"), at, 24)
        repair = r.get("source") == "verifiedDetail" and not r.get("variation") and fresh(r.get("buyCapturedAt"), at, 24)
        pending.append(((recent, not repair, priority, timestamp(r.get("lastIdentityAttemptAt")), -buy, key(r)), r))
    return [r for _, r in sorted(pending, key=lambda p: p[0])[:limit]]


def protected_capture(row, at, retail_blocked, source_blocked):
    if source_blocked.is_set():
        return None
    time.sleep(0.7)
    if source_blocked.is_set():
        return None
    try:
        result = capture_detail(row, at, not retail_blocked.is_set())
    except HTTPError as error:
        if error.code in {403,429}:
            source_blocked.set()
            retail_blocked.set()
        raise
    if "403" in result.get("saleCaptureError", "") or "429" in result.get("saleCaptureError", ""):
        retail_blocked.set()
    return result


def verify(limit=80, workers=2):
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = legacy.load_previous()
    prior = previous.get("meta", {}).get("versionValidation", {})
    if timestamp(prior.get("sourceBlockedUntil")) > timestamp(at):
        print(json.dumps({"status":"cooldown","until":prior["sourceBlockedUntil"],"attempted":0}), flush=True)
        return 0
    with gzip.open(legacy.ROOT / "data.json.gz", "rt", encoding="utf-8") as f:
        metadata = json.load(f)
    fx = read_json(legacy.ROOT / "hareruya_ck_fx.json")
    selected = priority_rows(previous.get("items", []), metadata, fx, at, limit)
    del metadata
    items = {key(r): r for r in previous.get("items", [])}
    completed, sales, skipped, failures = 0, 0, 0, []
    blocked = Event()
    source_blocked = Event()
    previous_block = prior.get("retailBlockedUntil")
    if not previous_block and any("403" in e or "429" in e for e in prior.get("failures", [])):
        previous_block = (timestamp(prior.get("at")) + timedelta(hours=6)).isoformat(timespec="seconds")
    if timestamp(previous_block) > timestamp(at):
        blocked.set()
    def capture(row):
        return protected_capture(row, at, blocked, source_blocked)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(capture, row): row for row in selected}
        for i, future in enumerate(as_completed(futures), 1):
            old = futures[future]
            try:
                row = future.result()
                if row is None:
                    skipped += 1
                    continue
                row["lastIdentityAttemptAt"] = at
                items[key(row)] = row
                completed += 1
                sales += int(row.get("saleCapturedAt") == at and row.get("saleStock", {}).get("EN", {}).get("NM") is not None)
                if row.get("saleCaptureError"):
                    failures.append(f"{old['productId']}|EN sale: {row['saleCaptureError']}")
            except Exception as error:
                items[key(old)] = {**old, "lastIdentityAttemptAt": at, "lastAttemptAt": at, "captureError": f"{type(error).__name__}: {error}"}
                failures.append(f"{old['productId']}|EN: {type(error).__name__}: {error}")
            if i % 25 == 0:
                print(json.dumps({"checked":i,"attempted":len(selected),"titlesVerified":completed,"retailStockVerified":sales}), flush=True)
    report = {"at":at,"selected":len(selected),"attempted":len(selected)-skipped,"skippedDueToRestriction":skipped,"titlesVerified":completed,"retailStockVerified":sales,"failures":failures,
              "sourceBlockedUntil": (timestamp(at)+timedelta(hours=6)).isoformat(timespec="seconds") if source_blocked.is_set() else None,
              "retailBlockedUntil": (timestamp(at)+timedelta(hours=6)).isoformat(timespec="seconds") if blocked.is_set() and timestamp(previous_block) <= timestamp(at) else previous_block}
    payload = annotate({"meta": {**previous.get("meta", {}), "generatedAt": at if completed else previous["meta"]["generatedAt"],
                                  "versionValidation": report, "status": "partial" if failures else previous["meta"].get("status", "ok")},
                        "items":sorted(items.values(), key=lambda r:(int(r["productId"]),r["language"]))}, at)
    record_refresh(previous, payload, at)
    temp = legacy.OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(legacy.OUTPUT)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if completed or not selected else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 0 <= args.limit <= 500 or not 1 <= args.workers <= 3:
        parser.error("invalid verification batch size")
    raise SystemExit(verify(args.limit,args.workers))
