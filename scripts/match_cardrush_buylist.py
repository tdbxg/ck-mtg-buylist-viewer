#!/usr/bin/env python3
"""Match Card Rush buy prices to exact Scryfall printings.

Reads the raw Card Rush snapshot (``cardrush_buylist_raw.json.gz``), parses each
row's name into collector number + English name + finish, maps Card Rush's own
``pack_code`` to a Scryfall set code, then resolves each row against the Scryfall
bulk print catalog. Only rows that resolve to a *single* exact printing are kept
(the caller's policy: drop ambiguous / non-unique rows).

Reuses the name/set normalization and Scryfall bulk reader already used by the
Hareruya pipeline (``build_hareruya_opportunities``, ``hareruya_bulk_prints``).
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from build_hareruya_opportunities import name_key, number
from hareruya_bulk_prints import read_cards

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "cardrush_buylist_raw.json.gz"
OUTPUT_PATH = ROOT / "cardrush_buylist_matched.json.gz"

# Card Rush ``pack_code`` -> Scryfall set code. Codes that are already Scryfall
# codes fall through to the lowercase path; full product names are mapped here.
CARD_RUSH_SETS: dict[str, str] = {
    "10ED": "10e",
    "Reprint Cards(Secret Lair Commander)": "slc",
    "Reprint Cards(The List)": "plist",
    "Reprint Cards(Mystery Booster)": "mb1",
    "Reprint Cards(Mystery Booster2)": "mb2",
    "Mystery Booster Playtest Cards": "cmb1",
    "Commander 2021": "c21",
    "Commander 2020": "c20",
    "Commander 2019": "c19",
    "Commander 2018": "c18",
    "Commander 2017": "c17",
    "Commander 2016": "c16",
    "Commander 2015": "c15",
    "Commander 2014": "c14",
    "Commander 2013": "c13",
    "Commander": "cmd",
    "Commander Anthology": "cma",
    "Commander Anthology Volume II": "cm2",
    "Planechase": "hop",
    "Planechase 2012": "pc2",
    "Duel Decks: Elves vs. Inventors": "ddu",
    "Guru Lands": "pgru",
    "Starter Commander Decks": "scd",
    "Secret Lair Showdown": "slc",
    "SUBESORE": "slc",
    "Judge Promos": "jgp",
    "Magic Player Rewards": "mpr",
    "Archenemy": "arc",
    "Archenemy: Nicol Bolas": "e01",
    "Planechase Anthology": "pca",
    "Duel Decks: Merfolk vs. Goblins": "ddt",
    "Duel Decks: Mind vs. Might": "dds",
    "Duel Decks: Phyrexia vs. the Coalition": "dde",
    "Duel Decks: Izzet vs. Golgari": "ddj",
    "Duel Decks: Jace vs. Chandra": "dd2",
    "Duel Decks: Elspeth vs. Tezzeret": "ddf",
    "Duel Decks: Zendikar vs. Eldrazi": "ddp",
    "From the Vault: Relics": "v10",
    "From the Vault: Twenty": "v13",
    "Signature Spellbook: Jace": "ss1",
}

NUMBER_IN_NAME = re.compile(r"\((\d{3,4})\)")


# Japanese treatment markers -> (Scryfall field, required value). These are
# verified against the actual bulk data (e.g. SOA #19 = inverted archive,
# #149 = silverscroll, #84 = Japanese-exclusive art).
TREATMENT_MARKERS = (
    ("アーカイブ", "frame_effects", "inverted"),
    ("シルバースクロール", "promo_types", "silverscroll"),
    ("日限定イラスト", "lang", "ja"),
)


def parse_name(name: str) -> tuple[str | None, str, str, str, dict[str, str]]:
    """Return (collector_number, finish, jp_name, en_name, treatments).

    finish is one of ``nonfoil`` / ``foil`` / ``etched``. ``treatments`` maps a
    Scryfall field to the value its printing must carry (e.g. frame_effects
    ``inverted`` for archive treatments, promo_types ``silverscroll``).
    """
    prefix = re.match(r"^(?:\([^()]+\))*", name or "").group(0)
    rest = (name or "")[len(prefix):]
    markers = re.findall(r"\(([^()]+)\)", prefix)

    collector: str | None = None
    finish = "nonfoil"
    treatments: dict[str, str] = {}
    for marker in markers:
        lowered = marker.lower()
        if re.fullmatch(r"\d{3,4}", marker):
            collector = number(marker)
        elif "etched" in lowered or "エッチング" in lowered:
            finish = "etched"
        elif "foil" in lowered or "フォイル" in lowered:
            finish = "foil"
        for token, field, value in TREATMENT_MARKERS:
            if token in marker:
                treatments[field] = value

    if "/" in rest:
        jp, en = rest.split("/", 1)
    else:
        jp, en = "", rest
    return collector, finish, jp.strip(), en.strip(), treatments


def set_code(pack_code: str) -> str | None:
    raw = (pack_code or "").strip()
    if not raw:
        return None
    if raw in CARD_RUSH_SETS:
        return CARD_RUSH_SETS[raw]
    match = re.fullmatch(r"([A-Za-z0-9]{2,6})", raw)
    if match:
        return match.group(1).lower()
    return None


def scryfall_image(card: dict[str, Any]) -> str:
    images = card.get("image_uris") or {}
    if not images and card.get("card_faces"):
        faces = card["card_faces"]
        if faces:
            images = faces[0].get("image_uris") or {}
    return images.get("normal") or images.get("large") or images.get("small") or ""


def build_index(bulk_path: Path) -> dict[str, list[dict[str, Any]]]:
    """name_key -> list of printings (set, collector_number, finishes, lang, oversized)."""
    index: dict[str, list[dict[str, Any]]] = {}
    for card in read_cards(bulk_path):
        if not isinstance(card.get("finishes"), list):
            continue
        if not card.get("set") or not card.get("collector_number") or not card.get("lang"):
            continue
        names = {card.get("name")}
        for face in card.get("card_faces") or []:
            if face.get("name"):
                names.add(face["name"])
        for nm in names:
            if not nm:
                continue
            index.setdefault(name_key(nm), []).append({
                "id": card.get("id"),
                "set": card.get("set"),
                "number": number(card.get("collector_number")),
                "finishes": card.get("finishes"),
                "lang": card.get("lang"),
                "oversized": bool(card.get("oversized")),
                "name": card.get("name"),
                "image": scryfall_image(card),
                "rarity": card.get("rarity") or "",
                "released_at": card.get("released_at") or "",
                "frame_effects": list(card.get("frame_effects") or []),
                "promo_types": list(card.get("promo_types") or []),
            })
    return index


def match_rows(rows: list[dict[str, Any]], index: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reasons: dict[str, int] = {}
    matched: list[dict[str, Any]] = []

    def reject(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for row in rows:
        name = row.get("name") or ""
        collector, finish, jp, en, treatments = parse_name(name)
        code = set_code(row.get("pack_code"))
        if not en:
            reject("nameMissing")
            continue
        if not code:
            reject("setUnknown")
            continue

        candidates = index.get(name_key(en), [])
        if not candidates:
            reject("nameUnmatched")
            continue

        finish_key = {"foil": "foil", "nonfoil": "nonfoil", "etched": "etched"}.get(finish, "nonfoil")
        hits = [
            c for c in candidates
            if c["set"] == code
            and finish_key in c["finishes"]
            and not c["oversized"]
        ]
        if collector:
            hits = [c for c in hits if c["number"] == collector]
        else:
            for field, value in treatments.items():
                if field == "lang":
                    hits = [c for c in hits if c["lang"] == value]
                else:
                    hits = [c for c in hits if value in c.get(field) or []]

        if len(hits) == 0:
            reject("printUnmatched")
            continue
        if len(hits) > 1:
            reject("ambiguousPrint")
            continue

        exact = hits[0]
        matched.append({
            "sku": None,
            "scryfallId": exact["id"],
            "name": en,
            "nameJa": jp,
            "set": code,
            "collectorNumber": collector or exact["number"],
            "foil": finish == "foil",
            "language": row.get("language") or "",
            "packCode": row.get("pack_code") or "",
            "cardRushName": name,
            "buyPriceJpy": row.get("amount"),
            "isHot": bool(row.get("is_hot")),
            "displayCategory": row.get("display_category") or "",
            "updatedAt": row.get("updated_at") or "",
            "image": exact.get("image") or "",
            "rarity": exact.get("rarity") or "",
            "releasedAt": exact.get("released_at") or "",
        })

    return matched, reasons


def main() -> int:
    raw = json.loads(gzip.open(RAW_PATH, "rt", encoding="utf-8").read())
    rows: list[dict[str, Any]] = raw.get("items", [])
    bulk = ROOT / ".cache" / "hareruya-scryfall" / "default.jsonl.gz"
    if not bulk.exists():
        from hareruya_bulk_prints import acquire
        from build_hareruya_opportunities import iso_now
        bulk, _ = acquire(ROOT / ".cache" / "hareruya-scryfall", iso_now())

    index = build_index(bulk)
    matched, reasons = match_rows(rows, index)
    payload = {
        "meta": {
            "source": "cardrush.media/mtg/buying_prices",
            "rawItems": len(rows),
            "matchedItems": len(matched),
            "reasons": reasons,
        },
        "items": matched,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = OUTPUT_PATH.with_suffix(".gz.tmp")
    tmp.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    tmp.replace(OUTPUT_PATH)
    print(json.dumps({"raw": len(rows), "matched": len(matched), "reasons": reasons, "bytes": OUTPUT_PATH.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
