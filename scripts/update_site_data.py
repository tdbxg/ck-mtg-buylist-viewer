#!/usr/bin/env python3
"""Refresh the public static Card Kingdom buylist viewer data.

This script is intentionally self-contained for GitHub Actions. It does not
depend on the local Codex workspace; instead it fetches public Card Kingdom,
Scryfall, mtgch, and FX data, then rewrites the compressed static files that
GitHub Pages serves.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import shutil
import time
import urllib.request
from urllib.error import HTTPError
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SINGLES_URL = "https://api.cardkingdom.com/api/v2/pricelist"
SEALED_URL = "https://api.cardkingdom.com/api/sealed_pricelist"
FX_URL = "https://open.er-api.com/v6/latest/USD"
SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
MTGCH_NAMES_URL = "https://mtgch.com/static/card_names.json"
USER_AGENT = "ck-mtg-buylist-viewer-github-actions/1.0"
JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

FAST_CASH_USD = 2
RECENT_SET_LIMIT = 30

CARD_FIELDS = [
    "sku",
    "scryfallId",
    "name",
    "ckName",
    "flavorName",
    "cn",
    "edition",
    "variation",
    "activeBuying",
    "foil",
    "ckUrl",
    "scryfallUrl",
    "scryfallSet",
    "scryfallSetName",
    "collectorNumber",
    "rarity",
    "releasedAt",
    "image",
    "cashUsd",
    "cashCny",
    "creditUsd",
    "creditCny",
    "retailUsd",
    "retailCny",
    "qtyBuying",
    "qtyRetail",
    "cnSource",
]

SEALED_FIELDS = [
    "sku",
    "name",
    "edition",
    "shipsInternationally",
    "ckUrl",
    "image",
    "cashUsd",
    "cashCny",
    "creditUsd",
    "creditCny",
    "retailUsd",
    "retailCny",
    "qtyBuying",
    "qtyRetail",
]

CSV_HEADERS = [
    "英文名",
    "中文名",
    "CK版本",
    "Scryfall系列",
    "系列代码",
    "编号",
    "变体/皮肤",
    "闪卡",
    "现金回收USD",
    "现金回收CNY",
    "店铺积分USD",
    "店铺积分CNY",
    "CK正常售价USD",
    "CK正常售价CNY",
    "现金/售价比例",
    "积分/售价比例",
    "收购数量",
    "零售库存",
    "发售日",
    "稀有度",
    "Card Kingdom链接",
    "Scryfall链接",
    "SKU",
]


def fetch_json(url: str, timeout: int = 120) -> Any:
    req = urllib.request.Request(url, headers=JSON_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout: int = 120) -> Any:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **JSON_HEADERS},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {body[:1000]}") from exc


def normalize_name(name: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(name or "").strip().lower())


def money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0


def qty(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def boolish(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def full_url(base: str, path: str) -> str:
    return (base.rstrip("/") + "/" + str(path).lstrip("/")).replace(" ", "%20")


def load_previous_payload() -> dict:
    gz_path = ROOT / "data.json.gz"
    if not gz_path.exists():
        return {"cards": [], "sealed": [], "meta": {}}
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def scryfall_image(card: dict) -> str:
    images = card.get("image_uris") or {}
    if not images and card.get("card_faces"):
        images = card["card_faces"][0].get("image_uris") or {}
    return images.get("normal") or images.get("large") or images.get("small") or ""


def compact_scryfall_card(card: dict) -> dict:
    return {
        "id": card.get("id") or "",
        "name": card.get("name") or "",
        "flavorName": card.get("flavor_name") or "",
        "printedName": card.get("printed_name") or "",
        "lang": card.get("lang") or "",
        "set": card.get("set") or "",
        "setName": card.get("set_name") or "",
        "collectorNumber": card.get("collector_number") or "",
        "rarity": card.get("rarity") or "",
        "releasedAt": card.get("released_at") or "",
        "finishes": card.get("finishes") or [],
        "promoTypes": card.get("promo_types") or [],
        "scryfallUri": card.get("scryfall_uri") or "",
        "image": scryfall_image(card),
    }


def previous_indexes(payload: dict) -> tuple[dict, dict, dict]:
    by_sid: dict[str, dict] = {}
    cn_by_name: dict[str, str] = {}
    skin_cn_by_name: dict[str, str] = {}
    for row in payload.get("cards", []):
        sid = row.get("scryfallId") or ""
        exact = {
            "id": sid,
            "name": row.get("name") or row.get("ckName") or "",
            "flavorName": row.get("flavorName") or "",
            "set": row.get("scryfallSet") or "",
            "setName": row.get("scryfallSetName") or "",
            "collectorNumber": row.get("collectorNumber") or "",
            "rarity": row.get("rarity") or "",
            "releasedAt": row.get("releasedAt") or "",
            "finishes": row.get("finishes") or [],
            "promoTypes": row.get("promoTypes") or [],
            "scryfallUri": row.get("scryfallUrl") or "",
            "image": row.get("image") or "",
        }
        if sid:
            by_sid[sid] = exact
        if row.get("cn"):
            cn_by_name.setdefault(normalize_name(row.get("name") or row.get("ckName") or ""), row["cn"])
        if row.get("flavorCn"):
            skin_cn_by_name.setdefault(normalize_name(row.get("flavorName") or ""), row["flavorCn"])
    return by_sid, cn_by_name, skin_cn_by_name


def mtgch_indexes() -> tuple[dict, dict]:
    by_sid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    try:
        rows = fetch_json(MTGCH_NAMES_URL, timeout=180)
    except Exception as exc:
        print(f"WARN: mtgch name index unavailable: {exc}")
        return by_sid, by_name

    for item in rows:
        if isinstance(item, list):
            en = str(item[0] if len(item) > 0 else "")
            cn = str(item[1] if len(item) > 1 else "")
            image = str(item[2] if len(item) > 2 else "")
            sid = str(item[3] if len(item) > 3 else "")
        elif isinstance(item, dict):
            en = str(item.get("en") or item.get("name") or "")
            cn = str(item.get("cn") or item.get("printed_name") or "")
            image = str(item.get("image") or "")
            sid = str(item.get("scryfall_id") or "")
        else:
            continue
        if not en or not cn:
            continue
        rec = {"en": en, "cn": cn, "image": image, "scryfallId": sid}
        by_name.setdefault(normalize_name(en), rec)
        if sid:
            by_sid.setdefault(sid, rec)
    return by_sid, by_name


def fetch_missing_scryfall(needed: list[str], existing: dict) -> dict:
    missing = [
        sid
        for sid in needed
        if sid not in existing or not existing[sid].get("image") or not existing[sid].get("set")
    ]
    if not missing:
        return existing

    print(f"Fetching {len(missing)} Scryfall exact-print records...")
    chunk_size = 50
    for start in range(0, len(missing), chunk_size):
        chunk = missing[start : start + chunk_size]
        payload = {"identifiers": [{"id": sid} for sid in chunk]}
        try:
            response = post_json(SCRYFALL_COLLECTION_URL, payload)
        except Exception as exc:
            print(f"WARN: Scryfall collection chunk failed ({chunk[0]}..{chunk[-1]}): {exc}")
            for sid in chunk:
                try:
                    response = post_json(SCRYFALL_COLLECTION_URL, {"identifiers": [{"id": sid}]})
                except Exception as one_exc:
                    print(f"WARN: Scryfall exact print unavailable for {sid}: {one_exc}")
                    continue
                for card in response.get("data", []):
                    if card.get("id"):
                        existing[card["id"]] = compact_scryfall_card(card)
            continue
        for card in response.get("data", []):
            if card.get("id"):
                existing[card["id"]] = compact_scryfall_card(card)
        print(f"  {min(start + len(chunk), len(missing))}/{len(missing)}")
        time.sleep(0.08)
    return existing


def lookup_cn(
    sid: str,
    name: str,
    mtgch_by_sid: dict,
    mtgch_by_name: dict,
    prev_cn_by_name: dict,
) -> tuple[str, str]:
    if sid and sid in mtgch_by_sid:
        return mtgch_by_sid[sid].get("cn") or "", "mtgch_scryfall_id"
    key = normalize_name(name)
    if key in mtgch_by_name:
        return mtgch_by_name[key].get("cn") or "", "mtgch_name"
    if key in prev_cn_by_name:
        return prev_cn_by_name[key], "previous_name"
    return "", "not_found"


def build_payload(
    singles: dict,
    sealed: dict,
    fx: dict,
    exact_prints: dict,
    mtgch_by_sid: dict,
    mtgch_by_name: dict,
    prev_cn_by_name: dict,
    prev_skin_cn_by_name: dict,
) -> dict:
    usd_cny = float(fx.get("rates", {}).get("CNY") or 0)
    if not usd_cny:
        raise RuntimeError("USD/CNY exchange rate missing")

    cards = []
    editions: dict[str, dict] = {}
    missing_cn = 0
    missing_image = 0
    base = singles["meta"]["base_url"]

    for row in singles.get("data", []):
        if money(row.get("price_buy")) <= 0:
            continue
        sid = row.get("scryfall_id") or ""
        exact = exact_prints.get(sid) or {}
        real_name = exact.get("name") or row.get("name") or ""
        cn, cn_source = lookup_cn(sid, real_name, mtgch_by_sid, mtgch_by_name, prev_cn_by_name)
        skin_name = exact.get("flavorName") or row.get("variation") or ""
        flavor_cn = prev_skin_cn_by_name.get(normalize_name(skin_name), "")
        mtgch_name_record = mtgch_by_name.get(normalize_name(real_name), {})
        image = (
            exact.get("image")
            or (mtgch_by_sid.get(sid) or {}).get("image")
            or mtgch_name_record.get("image")
            or ""
        )
        if not cn:
            missing_cn += 1
        if not image:
            missing_image += 1

        edition = row.get("edition") or ""
        cash_usd = money(row.get("price_buy"))
        retail_usd = money(row.get("price_retail"))
        edition_slot = editions.setdefault(
            edition,
            {"name": edition, "count": 0, "latestReleasedAt": "", "maxCashUsd": 0},
        )
        edition_slot["count"] += 1
        edition_slot["maxCashUsd"] = max(edition_slot["maxCashUsd"], cash_usd)
        if (exact.get("releasedAt") or "") > edition_slot["latestReleasedAt"]:
            edition_slot["latestReleasedAt"] = exact.get("releasedAt") or ""

        cards.append(
            {
                "id": row.get("id"),
                "sku": row.get("sku"),
                "scryfallId": sid,
                "name": real_name,
                "ckName": row.get("name") or "",
                "flavorName": exact.get("flavorName") or "",
                "flavorCn": flavor_cn,
                "cn": cn,
                "match": cn_source,
                "edition": edition,
                "variation": row.get("variation") or "",
                "activeBuying": qty(row.get("qty_buying")) > 0,
                "foil": boolish(row.get("is_foil")),
                "ckUrl": full_url(base, row.get("url", "")),
                "scryfallUrl": exact.get("scryfallUri") or "",
                "scryfallSet": exact.get("set") or "",
                "scryfallSetName": exact.get("setName") or "",
                "collectorNumber": exact.get("collectorNumber") or "",
                "rarity": exact.get("rarity") or "",
                "releasedAt": exact.get("releasedAt") or "",
                "finishes": exact.get("finishes") or [],
                "promoTypes": exact.get("promoTypes") or [],
                "image": image,
                "cashUsd": cash_usd,
                "cashCny": round(cash_usd * usd_cny, 2),
                "creditUsd": round(cash_usd * 1.3, 2),
                "creditCny": round(cash_usd * 1.3 * usd_cny, 2),
                "qtyBuying": qty(row.get("qty_buying")),
                "retailUsd": retail_usd,
                "retailCny": round(retail_usd * usd_cny, 2),
                "qtyRetail": qty(row.get("qty_retail")),
                "conditions": row.get("condition_values") or {},
                "search": normalize_name(
                    " ".join(
                        [
                            row.get("name") or "",
                            real_name,
                            exact.get("flavorName") or "",
                            flavor_cn,
                            cn,
                            edition,
                            exact.get("setName") or "",
                            exact.get("set") or "",
                            exact.get("collectorNumber") or "",
                            row.get("sku") or "",
                            row.get("variation") or "",
                        ]
                    )
                ),
                "cnSource": cn_source,
            }
        )

    cards.sort(key=lambda item: item["cashUsd"], reverse=True)

    sealed_rows = []
    sealed_base = sealed["meta"]["base_url"]
    for row in sealed.get("data", []):
        if qty(row.get("qty_buying")) <= 0:
            continue
        cash_usd = money(row.get("price_buy"))
        retail_usd = money(row.get("price_retail"))
        sealed_rows.append(
            {
                "id": row.get("id"),
                "sku": row.get("sku"),
                "name": row.get("name") or "",
                "edition": row.get("edition") or "",
                "shipsInternationally": bool(row.get("ships_internationally")),
                "ckUrl": full_url(sealed_base, row.get("url", "")),
                "image": row.get("image") or "",
                "cashUsd": cash_usd,
                "cashCny": round(cash_usd * usd_cny, 2),
                "creditUsd": round(cash_usd * 1.3, 2),
                "creditCny": round(cash_usd * 1.3 * usd_cny, 2),
                "qtyBuying": qty(row.get("qty_buying")),
                "retailUsd": retail_usd,
                "retailCny": round(retail_usd * usd_cny, 2),
                "qtyRetail": qty(row.get("qty_retail")),
                "search": normalize_name(" ".join([row.get("name") or "", row.get("edition") or ""])),
            }
        )
    sealed_rows.sort(key=lambda item: item["cashUsd"], reverse=True)

    return {
        "meta": {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "cardKingdomCreatedAt": singles["meta"].get("created_at", ""),
            "sealedCreatedAt": sealed["meta"].get("created_at", ""),
            "usdCny": usd_cny,
            "fxUpdatedAt": fx.get("time_last_update_utc", ""),
            "cards": len(cards),
            "sealed": len(sealed_rows),
            "missingCn": missing_cn,
            "missingImage": missing_image,
            "updateMode": "github-actions-static",
        },
        "editions": sorted(
            editions.values(),
            key=lambda item: (
                item.get("latestReleasedAt") or "",
                item.get("maxCashUsd") or 0,
                item.get("count") or 0,
            ),
            reverse=True,
        ),
        "cards": cards,
        "sealed": sealed_rows,
    }


def pack_row(row: dict, fields: list[str]) -> list:
    return [row.get(field) for field in fields]


def recent_codes(cards: list[dict]) -> set[str]:
    recent_sets = sorted(
        {
            (row.get("scryfallSet") or "", row.get("releasedAt") or "")
            for row in cards
            if row.get("scryfallSet") and row.get("releasedAt")
        },
        key=lambda item: item[1],
        reverse=True,
    )[:RECENT_SET_LIMIT]
    return {code for code, _ in recent_sets}


def write_payload_files(payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(ROOT / "data.json.gz.tmp", "wb", compresslevel=9) as f:
        f.write(raw)
    (ROOT / "data.json.gz.tmp").replace(ROOT / "data.json.gz")
    with open(ROOT / "last_update.json", "w", encoding="utf-8") as f:
        json.dump(payload["meta"], f, ensure_ascii=False, indent=2)


def write_fast_payload(payload: dict) -> None:
    codes = recent_codes(payload.get("cards", []))
    cards = [
        row
        for row in payload.get("cards", [])
        if float(row.get("cashUsd") or 0) >= FAST_CASH_USD or row.get("scryfallSet") in codes
    ]
    meta = dict(payload.get("meta", {}))
    meta.update(
        {
            "mode": "fast",
            "cards": len(cards),
            "fullCards": payload.get("meta", {}).get("cards", len(payload.get("cards", []))),
            "fastCashUsd": FAST_CASH_USD,
            "recentSetLimit": RECENT_SET_LIMIT,
        }
    )
    fast_payload = {
        "meta": meta,
        "fields": CARD_FIELDS,
        "sealedFields": SEALED_FIELDS,
        "editions": payload.get("editions", [])[:800],
        "cards": [pack_row(row, CARD_FIELDS) for row in cards],
        "sealed": [pack_row(row, SEALED_FIELDS) for row in payload.get("sealed", [])],
    }
    raw = json.dumps(fast_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(ROOT / "data_fast.json.gz.tmp", "wb", compresslevel=9) as f:
        f.write(raw)
    (ROOT / "data_fast.json.gz.tmp").replace(ROOT / "data_fast.json.gz")


def ratio(value: float, retail: float) -> float | str:
    if not retail:
        return ""
    return round(value / retail, 4)


def csv_row(row: dict) -> list:
    cash = float(row.get("cashUsd") or 0)
    credit = float(row.get("creditUsd") or 0)
    retail = float(row.get("retailUsd") or 0)
    return [
        row.get("name") or "",
        row.get("cn") or "",
        row.get("edition") or "",
        row.get("scryfallSetName") or "",
        str(row.get("scryfallSet") or "").upper(),
        row.get("collectorNumber") or "",
        row.get("flavorName") or row.get("variation") or "",
        "是" if row.get("foil") else "否",
        cash,
        row.get("cashCny") or 0,
        credit,
        row.get("creditCny") or 0,
        retail,
        row.get("retailCny") or 0,
        ratio(cash, retail),
        ratio(credit, retail),
        row.get("qtyBuying") or 0,
        row.get("qtyRetail") or 0,
        row.get("releasedAt") or "",
        row.get("rarity") or "",
        row.get("ckUrl") or "",
        row.get("scryfallUrl") or "",
        row.get("sku") or "",
    ]


def write_csv(path: Path, rows: list[dict], compress: bool = False) -> None:
    opener = gzip.open if compress else open
    mode = "wt" if compress else "w"
    with opener(path, mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for row in rows:
            writer.writerow(csv_row(row))


def write_exports(payload: dict) -> None:
    export_dir = ROOT / "exports"
    export_dir.mkdir(exist_ok=True)
    cards = payload.get("cards", [])
    codes = recent_codes(cards)
    fast_rows = [
        row
        for row in cards
        if float(row.get("cashUsd") or 0) >= FAST_CASH_USD or row.get("scryfallSet") in codes
    ]
    top_rows = sorted(cards, key=lambda row: float(row.get("cashUsd") or 0), reverse=True)[:5000]

    fast_path = export_dir / "ck_buylist_fast_high_recent.csv"
    top_path = export_dir / "ck_buylist_top5000.csv"
    full_path = export_dir / "ck_buylist_full.csv.gz"
    write_csv(fast_path, fast_rows)
    write_csv(top_path, top_rows)
    write_csv(full_path, cards, compress=True)

    manifest = {
        "generatedAt": payload.get("meta", {}).get("generatedAt"),
        "cardKingdomCreatedAt": payload.get("meta", {}).get("cardKingdomCreatedAt"),
        "fastRows": len(fast_rows),
        "topRows": len(top_rows),
        "fullRows": len(cards),
        "files": {
            fast_path.name: fast_path.stat().st_size,
            top_path.name: top_path.stat().st_size,
            full_path.name: full_path.stat().st_size,
        },
    }
    with open(export_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def main() -> int:
    previous = load_previous_payload()
    exact_prints, prev_cn_by_name, prev_skin_cn_by_name = previous_indexes(previous)
    mtgch_by_sid, mtgch_by_name = mtgch_indexes()

    singles = fetch_json(SINGLES_URL)
    sealed = fetch_json(SEALED_URL)
    fx = fetch_json(FX_URL)

    needed = sorted(
        {
            row.get("scryfall_id")
            for row in singles.get("data", [])
            if money(row.get("price_buy")) > 0 and UUID_RE.match(str(row.get("scryfall_id") or ""))
        }
    )
    exact_prints = fetch_missing_scryfall(needed, exact_prints)
    payload = build_payload(
        singles,
        sealed,
        fx,
        exact_prints,
        mtgch_by_sid,
        mtgch_by_name,
        prev_cn_by_name,
        prev_skin_cn_by_name,
    )
    write_payload_files(payload)
    write_fast_payload(payload)
    write_exports(payload)

    # The uncompressed file is useful locally but too large for GitHub Pages repo.
    (ROOT / "data.json").unlink(missing_ok=True)
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
