#!/usr/bin/env python3
"""Build the compact catalog used by the CK retail availability watch page.

The watch page monitors "上架 / 补货 / 售罄" by exact Card Kingdom SKU. Its
catalog must therefore describe every SKU in the official CK singles pricelist
with the current retail price and quantity, not just the positive-buylist
subset persisted in ``data.json.gz``.

The canonical caller is ``scripts/update_site_data.py``, which already fetches
the full ``https://api.cardkingdom.com/api/v2/pricelist`` response and passes
every row to :func:`build_catalog_from_api_rows` so no second collection is
made. Identity and imagery are enriched from the site snapshot when a SKU is
already known there; the raw API row provides retail price, quantity and
condition stock directly, so retail-only rows keep their values instead of
falling back to zero.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_PATH = ROOT / "data.json.gz"
OUTPUT_PATH = ROOT / "watch" / "catalog.json.gz"

FIELDS = (
    "sku",
    "scryfallId",
    "name",
    "cn",
    "edition",
    "variation",
    "foil",
    "ckUrl",
    "scryfallSet",
    "scryfallSetName",
    "collectorNumber",
    "releasedAt",
    "image",
    "retailUsd",
    "qtyRetail",
    "conditions",
)


def read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def quantity(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "foil"}


def sku_print_identity(sku: str, foil: bool) -> tuple[str, str]:
    match = re.fullmatch(r"([A-Z0-9]+)-([0-9]+[A-Z]?)", sku.upper())
    if not match:
        return "", ""
    prefix, collector = match.groups()
    if foil and prefix.startswith("F") and len(prefix) > 1:
        prefix = prefix[1:]
    return prefix.lower(), collector.lstrip("0") or "0"


def write_payload(payload: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    temp_path.replace(output_path)


def build_catalog_from_api_rows(
    api_rows: list[dict[str, Any]],
    source_at: str,
    source: str,
    base_url: str = "",
    output_path: Path = OUTPUT_PATH,
    site_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build from every CK API row so retail-only listings are not filtered out."""
    site = site_payload if site_payload is not None else read_gzip_json(SITE_DATA_PATH)
    exact_by_sku = {
        str(card.get("sku")): card
        for card in site.get("cards", [])
        if card.get("sku")
    }

    packed_rows: list[list[Any]] = []
    active_rows = 0
    enriched_rows = 0
    for raw in api_rows:
        sku = str(raw.get("sku") or "")
        if not sku:
            continue
        card = exact_by_sku.get(sku) or {}
        enriched_rows += int(bool(card))
        retail = money(raw.get("price_retail"))
        stock = quantity(raw.get("qty_retail"))
        if retail > 0 and stock > 0:
            active_rows += 1

        foil = bool(card.get("foil")) if card else boolish(raw.get("is_foil"))
        fallback_set, fallback_collector = sku_print_identity(sku, foil)
        raw_url = str(raw.get("url") or "")

        row = {
            "sku": sku,
            "scryfallId": card.get("scryfallId") or raw.get("scryfall_id") or "",
            "name": card.get("name") or card.get("ckName") or raw.get("name") or sku,
            "cn": card.get("cn") or "",
            "edition": card.get("edition") or raw.get("edition") or "",
            "variation": card.get("flavorName") or card.get("variation") or raw.get("variation") or "",
            "foil": foil,
            "ckUrl": card.get("ckUrl") or (urljoin(base_url, raw_url) if raw_url else ""),
            "scryfallSet": card.get("scryfallSet") or fallback_set,
            "scryfallSetName": card.get("scryfallSetName") or "",
            "collectorNumber": card.get("collectorNumber") or fallback_collector,
            "releasedAt": card.get("releasedAt") or "",
            "image": card.get("image") or "",
            "retailUsd": retail,
            "qtyRetail": stock,
            "conditions": raw.get("condition_values") or card.get("conditions") or {},
        }
        packed_rows.append([row[field] for field in FIELDS])

    packed_rows.sort(key=lambda row: (str(row[2]).casefold(), str(row[4]).casefold(), str(row[0])))
    payload = {
        "meta": {
            "generatedAt": site.get("meta", {}).get("generatedAt") or "",
            "fullSnapshotAt": site.get("meta", {}).get("cardKingdomCreatedAt") or "",
            "sourceAt": source_at,
            "source": source,
            "cards": len(packed_rows),
            "activeRetailRows": active_rows,
            "enrichedRows": enriched_rows,
            "identity": "exact Card Kingdom SKU; Scryfall printing metadata where available",
        },
        "fields": list(FIELDS),
        "cards": packed_rows,
    }
    write_payload(payload, output_path)
    return payload


def load_api_payload(path: Path) -> tuple[list[dict[str, Any]], str, str]:
    """Read a raw ``api/v2/pricelist`` response and return rows plus metadata."""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    meta = payload.get("meta") or {}
    return payload.get("data") or [], str(meta.get("created_at") or ""), str(meta.get("base_url") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the CK retail watch catalog from a full pricelist JSON.",
    )
    parser.add_argument(
        "--api-rows",
        required=True,
        help="Path to the raw api.cardkingdom.com/api/v2/pricelist JSON response.",
    )
    parser.add_argument(
        "--site-data",
        default=str(SITE_DATA_PATH),
        help="Path to data.json.gz used for exact-print identity enrichment.",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help="Output path for watch/catalog.json.gz.",
    )
    args = parser.parse_args(argv)

    api_rows, source_at, base_url = load_api_payload(Path(args.api_rows))
    site_path = Path(args.site_data)
    site = read_gzip_json(site_path) if site_path.exists() else {"cards": []}
    payload = build_catalog_from_api_rows(
        api_rows,
        source_at=source_at,
        source="Card Kingdom full pricelist",
        base_url=base_url,
        output_path=Path(args.output),
        site_payload=site,
    )
    output_path = Path(args.output).resolve()
    try:
        output_label = str(output_path.relative_to(ROOT))
    except ValueError:
        output_label = str(output_path)
    print(
        json.dumps(
            {
                "output": output_label,
                "sourceAt": payload["meta"]["sourceAt"],
                "cards": payload["meta"]["cards"],
                "activeRetailRows": payload["meta"]["activeRetailRows"],
                "bytes": output_path.stat().st_size,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
