#!/usr/bin/env python3
"""Incrementally discover Hareruya buylist rows for high-value CK names."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from update_hareruya_prices import BASE, OUTPUT, TARGETS, fetch, listing_targets_from_html

ROOT = Path(__file__).resolve().parents[1]
CK_DATA = ROOT / "data.json.gz"
STATE = ROOT / "hareruya_probe_state.json"


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value).lower())


def load_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def high_value_names(min_cash_usd: float) -> list[dict]:
    with gzip.open(CK_DATA, "rt", encoding="utf-8") as handle:
        cards = json.load(handle)["cards"]
    grouped: dict[str, dict] = {}
    for card in cards:
        name = str(card.get("name") or "").strip()
        cash = float(card.get("cashUsd") or 0)
        if not card.get("activeBuying") or cash < min_cash_usd or not name:
            continue
        key = normalize(name)
        if key not in grouped or cash > grouped[key]["cashUsd"]:
            grouped[key] = {"key": key, "name": name, "cashUsd": cash}
    return sorted(grouped.values(), key=lambda row: (-row["cashUsd"], row["name"]))


def search(name: str) -> list[dict]:
    url = f"{BASE}/purchase/search?{urlencode({'product': name, 'suggest_type': 'card'})}"
    return listing_targets_from_html(fetch(url))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--min-cash-usd", type=float, default=5.0)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.limit < 1 or args.workers < 1:
        raise SystemExit("limit and workers must be positive")

    state = load_json(STATE, {"probed": {}, "unmatched": {}})
    all_names = high_value_names(args.min_cash_usd)
    candidates = [row for row in all_names if row["key"] not in state["probed"]][:args.limit]
    snapshot = load_json(OUTPUT, {"meta": {}, "items": []})
    items = {
        (str(row["productId"]), row.get("language", "JP")): row
        for row in snapshot.get("items", [])
    }
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    discovered = 0
    failures = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(search, row["name"]): row for row in candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                rows = future.result()
                result = {
                    "name": candidate["name"],
                    "cashUsd": candidate["cashUsd"],
                    "checkedAt": now,
                    "matches": len(rows),
                }
                state["probed"][candidate["key"]] = result
                if not rows:
                    state["unmatched"][candidate["key"]] = result
                for row in rows:
                    key = (str(row["productId"]), row["language"])
                    old = items.get(key, {})
                    items[key] = {
                        "productId": row["productId"],
                        "name": row["name"],
                        "nameJa": row["nameJa"],
                        "set": row.get("set") or old.get("set", ""),
                        "collectorNumber": row.get("collectorNumber") or old.get("collectorNumber", ""),
                        "language": row["language"],
                        "image": row.get("image") or old.get("image", ""),
                        "sale": old.get("sale", {}),
                        "buy": {row["language"]: row["buyPrice"]},
                        "saleUrl": old.get("saleUrl") or f"{BASE}/products/detail/{row['productId']}",
                        "buyUrl": f"{BASE}/purchase/detail/{row['productId']}?lang={row['language']}",
                        "capturedAt": now,
                        "retailVerified": bool(old.get("sale", {}).get(row["language"])),
                        "source": "priorityProbe",
                    }
                    if not old:
                        discovered += 1
            except Exception as exc:
                failures.append(f"{candidate['name']}: {exc}")

    values = sorted(items.values(), key=lambda row: (int(row["productId"]), row["language"]))
    meta = snapshot.setdefault("meta", {})
    meta.update({
        "generatedAt": now,
        "items": len(values),
        "images": sum(bool(row.get("image")) for row in values),
        "verifiedRetailItems": sum(bool(row.get("retailVerified")) for row in values),
        "priorityProbe": {
            "minCashUsd": args.min_cash_usd,
            "probedThisRun": len(candidates),
            "discoveredThisRun": discovered,
            "remainingNames": len(all_names) - len(state["probed"]),
            "failures": failures,
        },
    })
    snapshot["items"] = values
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TARGETS.write_text(
        json.dumps([{"productId": row["productId"], "language": row["language"]} for row in values], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta["priorityProbe"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
