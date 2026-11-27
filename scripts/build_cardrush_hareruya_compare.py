#!/usr/bin/env python3
"""Build a side-by-side Hareruya vs Card Rush buy price comparison.

Both stores publish buy prices in JPY per exact printing and language. Card
Rush rows are already matched to a Scryfall ID; Hareruya rows are resolved to
the same ID through the existing ``hareruya_ck_resolutions.json.gz`` cache
(keyed by ``name_key|set_code|finish``). We join on Scryfall ID + foil +
language so a single card can show both stores' buy prices.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from build_hareruya_opportunities import SET_ALIASES, name_key

ROOT = Path(__file__).resolve().parents[1]
CARDRUSH_PATH = ROOT / "cardrush_buylist_matched.json.gz"
HARERUYA_PATH = ROOT / "hareruya_prices_light.json.gz"
RESOLUTIONS_PATH = ROOT / "hareruya_ck_resolutions.json.gz"
OUTPUT_PATH = ROOT / "cardrush_hareruya_compare.json.gz"


def hareruya_set_code(raw: str) -> str | None:
    match = __import__("re").fullmatch(r"([A-Za-z0-9]{2,6})", (raw or "").strip())
    if not match:
        return None
    code = match.group(1)
    return SET_ALIASES.get(code, code.lower())


def resolve_hareruya(items: list[dict[str, Any]], resolutions: dict[str, Any]) -> dict[tuple[str, bool, str], int]:
    """Map (scryfallId, foil, language) -> hareruya buy price (JPY)."""
    out: dict[tuple[str, bool, str], int] = {}
    for it in items:
        code = hareruya_set_code(it.get("set"))
        if not code:
            continue
        finish = "foil" if it.get("foil") else "nonfoil"
        key = f"{name_key(it.get('name'))}|{code}|{finish}"
        entry = resolutions.get(key)
        if not entry or entry.get("complete") is not True:
            continue
        cards = entry.get("cards") or []
        if len(cards) != 1:
            continue
        scryfall_id = cards[0].get("id")
        if not scryfall_id:
            continue
        buy = it.get("buy") or {}
        for lang in ("EN", "JP"):
            price = buy.get(lang)
            if price is None:
                continue
            out[(scryfall_id, bool(it.get("foil")), lang)] = int(price)
    return out


def main() -> int:
    cr = json.loads(gzip.open(CARDRUSH_PATH, "rt", encoding="utf-8").read())
    hr = json.loads(gzip.open(HARERUYA_PATH, "rt", encoding="utf-8").read())
    resolutions = json.loads(gzip.open(RESOLUTIONS_PATH, "rt", encoding="utf-8").read())

    hareruya_prices = resolve_hareruya(hr.get("items", []), resolutions)

    joined: dict[tuple[str, bool, str], dict[str, Any]] = {}
    for row in cr.get("items", []):
        sid = row.get("scryfallId")
        foil = bool(row.get("foil"))
        raw_lang = row.get("language") or ""
        lang = "JP" if raw_lang == "日本語" else ("EN" if raw_lang == "英語" else raw_lang)
        if not sid or lang not in ("EN", "JP"):
            continue
        key = (sid, foil, lang)
        slot = joined.setdefault(key, {
            "scryfallId": sid,
            "name": row.get("name") or "",
            "nameJa": row.get("nameJa") or "",
            "set": row.get("set") or "",
            "collectorNumber": row.get("collectorNumber") or "",
            "foil": foil,
            "language": lang,
            "cardrushBuyJpy": row.get("buyPriceJpy"),
            "hareruyaBuyJpy": None,
            "image": row.get("image") or "",
            "rarity": row.get("rarity") or "",
            "releasedAt": row.get("releasedAt") or "",
            "isHot": bool(row.get("isHot")),
            "displayCategory": row.get("displayCategory") or "",
        })
        slot["cardrushBuyJpy"] = row.get("buyPriceJpy")

    # Attach Hareruya prices for matching keys (also for keys Card Rush lacks).
    for (sid, foil, lang), price in hareruya_prices.items():
        key = (sid, foil, lang)
        if key in joined:
            joined[key]["hareruyaBuyJpy"] = price

    items = list(joined.values())
    items.sort(key=lambda r: (r["name"], r["set"], r["collectorNumber"], r["foil"], r["language"]))

    payload = {
        "meta": {
            "source": "cardrush_buylist_matched + hareruya_prices_light",
            "items": len(items),
            "withHareruya": sum(1 for r in items if r["hareruyaBuyJpy"] is not None),
        },
        "items": items,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = OUTPUT_PATH.with_suffix(".gz.tmp")
    tmp.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    tmp.replace(OUTPUT_PATH)
    print(json.dumps(payload["meta"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
