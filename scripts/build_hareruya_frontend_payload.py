#!/usr/bin/env python3
"""Build the compact front-end payloads served to the Hareruya query page.

``hareruya_prices.json`` is an 86k-row capture snapshot that is intentionally
verbose: each row keeps identity evidence and capture bookkeeping used by the
pipeline, which inflates it to tens of megabytes. The browser query page only
reads a small display-oriented subset of those fields, so we emit two gzipped
payloads from the same snapshot:

* ``hareruya_prices_fast.json.gz`` — the "fresh" rows (within the 24h capture
  window), loaded first for a fast first paint.
* ``hareruya_prices_light.json.gz`` — every row with display fields only,
  loaded in the background to enable full search and historical browsing.

The full ``hareruya_prices.json`` remains the authoritative capture snapshot
and is not modified.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRICES_PATH = ROOT / "hareruya_prices.json"
FAST_PATH = ROOT / "hareruya_prices_fast.json.gz"
LIGHT_PATH = ROOT / "hareruya_prices_light.json.gz"

# Fields the query page reads. Everything else (identityEvidence, variation,
# capture bookkeeping) stays only in the authoritative snapshot.
LIGHT_FIELDS = (
    "productId",
    "language",
    "name",
    "nameJa",
    "set",
    "collectorNumber",
    "image",
    "buy",
    "sale",
    "buyCapturedAt",
    "capturedAt",
    "saleCapturedAt",
    "captureError",
    "saleUrl",
    "buyUrl",
    "foil",
)


def write_gzip_payload(payload: dict[str, Any], path: Path) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    tmp.replace(path)


def trim_item(item: dict[str, Any]) -> dict[str, Any]:
    return {field: item.get(field) for field in LIGHT_FIELDS}


def build(snapshot_path: Path = PRICES_PATH) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = snapshot.get("items", [])
    meta: dict[str, Any] = dict(snapshot.get("meta", {}))

    fresh_items = [trim_item(row) for row in items if not row.get("stale")]
    light_items = [trim_item(row) for row in items]

    fast_meta = dict(meta)
    fast_meta["subset"] = "fresh"
    fast_meta["fullItems"] = len(items)
    write_gzip_payload({"meta": fast_meta, "items": fresh_items}, FAST_PATH)

    light_meta = dict(meta)
    light_meta["subset"] = "full"
    write_gzip_payload({"meta": light_meta, "items": light_items}, LIGHT_PATH)

    return {
        "fastItems": len(fresh_items),
        "lightItems": len(light_items),
        "fastBytes": FAST_PATH.stat().st_size,
        "lightBytes": LIGHT_PATH.stat().st_size,
    }


def main() -> int:
    result = build()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
