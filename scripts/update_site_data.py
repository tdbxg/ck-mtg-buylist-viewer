#!/usr/bin/env python3
"""Refresh the public static Card Kingdom buylist viewer data.

This script is intentionally self-contained for GitHub Actions. It does not
depend on the local Codex workspace; instead it fetches public Card Kingdom,
Scryfall, mtgch, and FX data, then rewrites the compressed static files that
GitHub Pages serves.
"""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import html
import json
import os
import re
import shutil
import subprocess
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
SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data/default-cards"
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
    "marketUsd",
    "marketEur",
    "tcgplayerUrl",
    "cardmarketUrl",
    "formatBucket",
    "cnSource",
    "reserved",
    "conditions",
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


def price_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 2)
    except Exception:
        return None


def qty(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def boolish(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def full_url(base: str, path: str) -> str:
    return (base.rstrip("/") + "/" + str(path).lstrip("/")).replace(" ", "%20")


def market_key(name: str, set_code: str, collector_number: str) -> str:
    return "|".join([normalize_name(name), normalize_name(set_code), normalize_name(collector_number)])


def sealed_key(row: dict) -> str:
    return "|".join(
        [
            str(row.get("id") or ""),
            normalize_name(row.get("name") or ""),
            normalize_name(row.get("edition") or ""),
        ]
    )


def load_previous_payload() -> dict:
    gz_path = ROOT / "data.json.gz"
    if not gz_path.exists():
        return {"cards": [], "sealed": [], "meta": {}}
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load_git_payload(rev: str) -> dict | None:
    try:
        raw = subprocess.check_output(["git", "show", f"{rev}:data.json.gz"], cwd=ROOT)
    except Exception as exc:
        print(f"WARN: previous git payload unavailable at {rev}: {exc}")
        return None
    try:
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception as exc:
        print(f"WARN: previous git payload unreadable at {rev}: {exc}")
        return None


def scryfall_image(card: dict) -> str:
    images = card.get("image_uris") or {}
    if not images and card.get("card_faces"):
        images = card["card_faces"][0].get("image_uris") or {}
    return images.get("normal") or images.get("large") or images.get("small") or ""


def compact_scryfall_card(card: dict) -> dict:
    prices = card.get("prices") or {}
    purchases = card.get("purchase_uris") or {}
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
        "reserved": bool(card.get("reserved")),
        "legalities": card.get("legalities") or {},
        "scryfallUri": card.get("scryfall_uri") or "",
        "image": scryfall_image(card),
        "usd": price_float(prices.get("usd")),
        "usdFoil": price_float(prices.get("usd_foil")),
        "usdEtched": price_float(prices.get("usd_etched")),
        "eur": price_float(prices.get("eur")),
        "eurFoil": price_float(prices.get("eur_foil")),
        "eurEtched": price_float(prices.get("eur_etched")),
        "tcgplayerUrl": purchases.get("tcgplayer") or "",
        "cardmarketUrl": purchases.get("cardmarket") or "",
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
            "reserved": bool(row.get("reserved")),
            "legalities": row.get("legalities") or {},
            "formatBucket": row.get("formatBucket") or "",
            "usd": row.get("marketUsd"),
            "usdFoil": row.get("marketUsd"),
            "eur": row.get("marketEur"),
            "eurFoil": row.get("marketEur"),
            "tcgplayerUrl": row.get("tcgplayerUrl") or "",
            "cardmarketUrl": row.get("cardmarketUrl") or "",
            "scryfallUri": row.get("scryfallUrl") or "",
            "image": row.get("image") if "cards.scryfall.io" in str(row.get("image") or "") else "",
        }
        if sid:
            by_sid[sid] = exact
        if row.get("cn"):
            cn_by_name.setdefault(normalize_name(row.get("name") or row.get("ckName") or ""), row["cn"])
        if row.get("flavorName") and row.get("flavorCn"):
            skin_cn_by_name.setdefault(normalize_name(row.get("flavorName") or ""), row["flavorCn"])
    return by_sid, cn_by_name, skin_cn_by_name


def previous_sealed_images(payload: dict) -> dict:
    images: dict[str, str] = {}
    for row in payload.get("sealed", []):
        image = row.get("image") or ""
        if not image:
            continue
        if row.get("id"):
            images[f"id:{row.get('id')}"] = image
        if row.get("ckUrl"):
            images[f"url:{row.get('ckUrl')}"] = image
        images[f"key:{sealed_key(row)}"] = image
    return images


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


def market_price(exact: dict, foil: bool, currency: str) -> float | None:
    if currency == "usd":
        if foil:
            return exact.get("usdFoil") if exact.get("usdFoil") is not None else exact.get("usd")
        return exact.get("usd") if exact.get("usd") is not None else exact.get("usdFoil")
    if foil:
        return exact.get("eurFoil") if exact.get("eurFoil") is not None else exact.get("eur")
    return exact.get("eur") if exact.get("eur") is not None else exact.get("eurFoil")


def fetch_missing_scryfall(needed: list[str], existing: dict) -> dict:
    missing = [
        sid
        for sid in needed
        if (
            sid not in existing
            or not existing[sid].get("image")
            or not existing[sid].get("set")
        )
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


def extract_ck_product_image(page_html: str) -> str:
    patterns = [
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
        r'data-maxsrc=["\']([^"\']+)["\']',
        r"background-image:url\(['\"]?([^'\"\)]+)['\"]?\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE)
        if match:
            image = html.unescape(match.group(1)).strip()
            if image.startswith("//"):
                return "https:" + image
            if image.startswith("/"):
                return "https://www.cardkingdom.com" + image
            if image.startswith("http"):
                return image
    return ""


def fetch_ck_product_image(url: str) -> str:
    if not url:
        return ""
    try:
        page = subprocess.check_output(
            ["curl", "-fsSL", "--max-time", "20", "-A", USER_AGENT, url],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            timeout=25,
        )
        image = extract_ck_product_image(page.decode("utf-8", errors="ignore"))
        if image:
            return image
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return extract_ck_product_image(resp.read().decode("utf-8", errors="ignore"))


def enrich_sealed_images(payload: dict, previous: dict) -> dict:
    if os.environ.get("CK_SKIP_SEALED_IMAGES") == "1":
        payload.setdefault("meta", {})["sealedImageSkipped"] = "local_skip"
        return payload

    cached = previous_sealed_images(previous)
    sealed_rows = payload.get("sealed", [])
    cached_filled = 0
    fetched_filled = 0
    missing = []
    for row in sealed_rows:
        if row.get("image"):
            continue
        image = (
            cached.get(f"id:{row.get('id')}")
            or cached.get(f"url:{row.get('ckUrl')}")
            or cached.get(f"key:{sealed_key(row)}")
            or ""
        )
        if image:
            row["image"] = image
            cached_filled += 1
        else:
            missing.append(row)

    if missing:
        print(f"Fetching {len(missing)} Card Kingdom sealed product images...")
    workers = max(1, int(os.environ.get("CK_SEALED_IMAGE_WORKERS") or 8))

    def fetch_one(row: dict) -> tuple[dict, str, str]:
        try:
            image = fetch_ck_product_image(row.get("ckUrl") or "")
        except Exception as exc:
            return row, "", str(exc)
        return row, image, ""

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_one, row) for row in missing]
        for future in as_completed(futures):
            row, image, error = future.result()
            completed += 1
            if image:
                row["image"] = image
                fetched_filled += 1
            elif error:
                print(f"WARN: sealed image unavailable for {row.get('name')}: {error}")
            if completed % 50 == 0 or completed == len(missing):
                print(f"  sealed images {completed}/{len(missing)}")

    still_missing = sum(1 for row in sealed_rows if not row.get("image"))
    payload.setdefault("meta", {})["sealedImagesCached"] = cached_filled
    payload.setdefault("meta", {})["sealedImagesFetched"] = fetched_filled
    payload.setdefault("meta", {})["sealedImagesMissing"] = still_missing
    return payload


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
        flavor_cn = prev_skin_cn_by_name.get(normalize_name(skin_name), "") if exact.get("flavorName") else ""
        image = exact.get("image") or ""
        if not cn:
            missing_cn += 1
        if not image:
            missing_image += 1

        edition = row.get("edition") or ""
        cash_usd = money(row.get("price_buy"))
        retail_usd = money(row.get("price_retail"))
        foil = boolish(row.get("is_foil"))
        market_usd = market_price(exact, foil, "usd")
        market_eur = market_price(exact, foil, "eur")
        legalities = exact.get("legalities") or {}
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
                "foil": foil,
                "ckUrl": full_url(base, row.get("url", "")),
                "scryfallUrl": exact.get("scryfallUri") or "",
                "scryfallSet": exact.get("set") or "",
                "scryfallSetName": exact.get("setName") or "",
                "collectorNumber": exact.get("collectorNumber") or "",
                "rarity": exact.get("rarity") or "",
                "releasedAt": exact.get("releasedAt") or "",
                "finishes": exact.get("finishes") or [],
                "promoTypes": exact.get("promoTypes") or [],
                "reserved": bool(exact.get("reserved")),
                "legalities": legalities,
                "formatBucket": format_bucket({"legalities": legalities}),
                "image": image,
                "cashUsd": cash_usd,
                "cashCny": round(cash_usd * usd_cny, 2),
                "creditUsd": round(cash_usd * 1.3, 2),
                "creditCny": round(cash_usd * 1.3 * usd_cny, 2),
                "qtyBuying": qty(row.get("qty_buying")),
                "retailUsd": retail_usd,
                "retailCny": round(retail_usd * usd_cny, 2),
                "qtyRetail": qty(row.get("qty_retail")),
                "marketUsd": market_usd,
                "marketEur": market_eur,
                "tcgplayerUrl": exact.get("tcgplayerUrl") or "",
                "cardmarketUrl": exact.get("cardmarketUrl") or "",
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


def build_sets(cards: list[dict]) -> list[dict]:
    by_set: dict[str, dict] = {}
    for row in cards:
        code = row.get("scryfallSet") or ""
        name = row.get("scryfallSetName") or ""
        if not code or not name:
            continue
        current = by_set.setdefault(
            code,
            {
                "code": code,
                "name": name,
                "releasedAt": row.get("releasedAt") or "",
                "count": 0,
                "maxCashUsd": 0,
            },
        )
        current["count"] += 1
        current["maxCashUsd"] = max(current["maxCashUsd"], float(row.get("cashUsd") or 0))
        if (row.get("releasedAt") or "") > current["releasedAt"]:
            current["releasedAt"] = row.get("releasedAt") or ""
    return sorted(
        by_set.values(),
        key=lambda item: (
            item.get("releasedAt") or "",
            item.get("maxCashUsd") or 0,
            item.get("count") or 0,
        ),
        reverse=True,
    )


def write_payload_files(payload: dict) -> None:
    payload["sets"] = build_sets(payload.get("cards", []))
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
        "sets": payload.get("sets") or build_sets(payload.get("cards", [])),
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


def scryfall_bulk_cards() -> list[dict]:
    meta = fetch_json(SCRYFALL_BULK_URL, timeout=120)
    download_uri = meta.get("download_uri")
    if not download_uri:
        raise RuntimeError("Scryfall default-cards bulk download URI missing")
    req = urllib.request.Request(download_uri, headers=JSON_HEADERS)
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.loads(resp.read().decode("utf-8"))


def enrich_market_reference(payload: dict) -> dict:
    if os.environ.get("CK_SKIP_MARKET_BULK") == "1":
        payload.setdefault("meta", {})["scryfallMarketSource"] = "Scryfall public USD/EUR price fields"
        payload.setdefault("meta", {})["scryfallMarketSkipped"] = "local_skip"
        return payload

    cards = payload.get("cards", [])
    wanted_ids = {row.get("scryfallId") for row in cards if row.get("scryfallId")}
    wanted_keys = {
        market_key(row.get("name") or "", row.get("scryfallSet") or "", row.get("collectorNumber") or "")
        for row in cards
        if row.get("scryfallSet") and row.get("collectorNumber")
    }
    if not wanted_ids and not wanted_keys:
        return payload

    print("Fetching Scryfall bulk market reference prices...")
    refs: dict[str, dict] = {}
    for card in scryfall_bulk_cards():
        sid = card.get("id") or ""
        key = market_key(card.get("name") or "", card.get("set") or "", card.get("collector_number") or "")
        if sid not in wanted_ids and key not in wanted_keys:
            continue
        prices = card.get("prices") or {}
        purchases = card.get("purchase_uris") or {}
        rec = {
            "usd": price_float(prices.get("usd")),
            "usdFoil": price_float(prices.get("usd_foil")),
            "usdEtched": price_float(prices.get("usd_etched")),
            "eur": price_float(prices.get("eur")),
            "eurFoil": price_float(prices.get("eur_foil")),
            "eurEtched": price_float(prices.get("eur_etched")),
            "tcgplayerUrl": purchases.get("tcgplayer") or "",
            "cardmarketUrl": purchases.get("cardmarket") or "",
            "legalities": card.get("legalities") or {},
        }
        if sid:
            refs[f"id:{sid}"] = rec
        refs[f"key:{key}"] = rec

    matched_usd = 0
    matched_eur = 0
    for row in cards:
        rec = refs.get(f"id:{row.get('scryfallId') or ''}") or refs.get(
            f"key:{market_key(row.get('name') or '', row.get('scryfallSet') or '', row.get('collectorNumber') or '')}"
        )
        if not rec:
            continue
        foil = bool(row.get("foil"))
        row["marketUsd"] = market_price(rec, foil, "usd")
        row["marketEur"] = market_price(rec, foil, "eur")
        row["tcgplayerUrl"] = rec.get("tcgplayerUrl") or ""
        row["cardmarketUrl"] = rec.get("cardmarketUrl") or ""
        row["legalities"] = rec.get("legalities") or row.get("legalities") or {}
        row["formatBucket"] = format_bucket(row)
        if row["marketUsd"] is not None:
            matched_usd += 1
        if row["marketEur"] is not None:
            matched_eur += 1
    payload.setdefault("meta", {})["scryfallMarketMatchedUsd"] = matched_usd
    payload.setdefault("meta", {})["scryfallMarketMatchedEur"] = matched_eur
    payload.setdefault("meta", {})["scryfallMarketSource"] = "Scryfall public USD/EUR price fields"
    return payload


def mover_row_key(row: dict) -> str:
    return row.get("sku") or "|".join(
        [
            row.get("name") or "",
            row.get("edition") or "",
            row.get("collectorNumber") or "",
            "foil" if row.get("foil") else "normal",
        ]
    )


def format_bucket(row: dict) -> str:
    legalities = row.get("legalities") or {}
    if legalities.get("standard") == "legal":
        return "standard"
    if legalities.get("pioneer") == "legal":
        return "pioneer"
    if legalities.get("modern") == "legal":
        return "modern"
    if legalities.get("legacy") == "legal":
        return "legacy"
    return "special"


def compact_mover(
    row: dict,
    previous: dict,
    days: int,
    value_field: str = "cashUsd",
    currency: str = "USD",
    source: str = "ck_buylist",
) -> dict:
    now = float(row.get(value_field) or 0)
    before = float(previous.get(value_field) or 0)
    change = round(now - before, 2)
    pct = round(change / before * 100, 2) if before else None
    retail = float(row.get("retailUsd") or 0)
    return {
        "key": mover_row_key(row),
        "name": row.get("name") or "",
        "cn": row.get("cn") or "",
        "edition": row.get("edition") or "",
        "setName": row.get("scryfallSetName") or "",
        "setCode": str(row.get("scryfallSet") or "").upper(),
        "collectorNumber": row.get("collectorNumber") or "",
        "sku": row.get("sku") or "",
        "foil": bool(row.get("foil")),
        "rarity": row.get("rarity") or "",
        "releasedAt": row.get("releasedAt") or "",
        "formatBucket": row.get("formatBucket") or format_bucket(row),
        "image": row.get("image") or "",
        "cashUsd": now,
        "previousCashUsd": before,
        "changeUsd": change,
        "currentPrice": now,
        "previousPrice": before,
        "changePrice": change,
        "changePct": pct,
        "currency": currency,
        "source": source,
        "creditUsd": round(now * 1.3, 2),
        "retailUsd": retail,
        "buyRatio": round(now / retail * 100, 2) if retail else None,
        "qtyBuying": int(row.get("qtyBuying") or 0),
        "qtyRetail": int(row.get("qtyRetail") or 0),
        "ckUrl": row.get("ckUrl") or "",
        "scryfallUrl": row.get("scryfallUrl") or "",
        "tcgplayerUrl": row.get("tcgplayerUrl") or "",
        "cardmarketUrl": row.get("cardmarketUrl") or "",
        "windowDays": days,
    }


def rank_mover_rows(rows: list[dict]) -> dict:
    return {
        "winners": sorted(rows, key=lambda row: (row["changePct"] or 0, row["changeUsd"]), reverse=True)[:100],
        "losers": sorted(rows, key=lambda row: (row["changePct"] or 0, row["changeUsd"]))[:100],
        "dollarsUp": sorted(
            [row for row in rows if row["changeUsd"] > 0],
            key=lambda row: row["changeUsd"],
            reverse=True,
        )[:100],
        "dollarsDown": sorted(
            [row for row in rows if row["changeUsd"] < 0],
            key=lambda row: row["changeUsd"],
        )[:100],
        "changedRows": len(rows),
    }


def mover_groups(
    current: dict,
    previous: dict,
    days: int,
    value_field: str = "cashUsd",
    currency: str = "USD",
    source: str = "ck_buylist",
    require_active: bool = True,
    require_retail_stock: bool = False,
    exclude_non_cards: bool = False,
) -> dict:
    previous_by_key = {mover_row_key(row): row for row in previous.get("cards", [])}
    rows = []
    for row in current.get("cards", []):
        if require_active and row.get("activeBuying") is False:
            continue
        if require_retail_stock and int(row.get("qtyRetail") or 0) <= 0:
            continue
        if exclude_non_cards:
            text = " ".join(
                [
                    str(row.get("edition") or ""),
                    str(row.get("scryfallSetName") or ""),
                    str(row.get("scryfallSet") or ""),
                    str(row.get("variation") or ""),
                    str(row.get("ckUrl") or ""),
                ]
            ).lower()
            if any(term in text for term in ["token", "helper", "oversized", "substitute card"]):
                continue
        old = previous_by_key.get(mover_row_key(row))
        if not old:
            continue
        now = float(row.get(value_field) or 0)
        before = float(old.get(value_field) or 0)
        if before < 0.25 or now <= 0:
            continue
        change = round(now - before, 2)
        pct_abs = abs(change / before * 100) if before else 0
        if abs(change) < 0.05 and pct_abs < 3:
            continue
        rows.append(compact_mover(row, old, days, value_field=value_field, currency=currency, source=source))

    ranked = rank_mover_rows(rows)
    ranked["formats"] = {
        key: rank_mover_rows([row for row in rows if (row.get("formatBucket") or format_bucket(row)) == key])
        for key in ["standard", "pioneer", "modern", "legacy", "special"]
    }
    return ranked


def write_movers(payload: dict, daily_previous: dict, weekly_previous: dict) -> None:
    movers_payload = {
        "meta": {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "currentDataAt": payload.get("meta", {}).get("cardKingdomCreatedAt", ""),
            "dailyPreviousDataAt": daily_previous.get("meta", {}).get("cardKingdomCreatedAt", ""),
            "weeklyPreviousDataAt": weekly_previous.get("meta", {}).get("cardKingdomCreatedAt", ""),
            "source": "Card Kingdom buylist",
            "currency": "USD",
            "marketSource": payload.get("meta", {}).get("scryfallMarketSource", ""),
        },
        "daily": mover_groups(payload, daily_previous, 1),
        "weekly": mover_groups(payload, weekly_previous, 7),
        "marketSources": {
            "ckretail": {
                "label": "CK正常售价",
                "currency": "USD",
                "source": "Card Kingdom price_retail / NM retail price",
                "daily": mover_groups(
                    payload,
                    daily_previous,
                    1,
                    value_field="retailUsd",
                    currency="USD",
                    source="ck_retail_nm",
                    require_active=False,
                    require_retail_stock=True,
                    exclude_non_cards=True,
                ),
                "weekly": mover_groups(
                    payload,
                    weekly_previous,
                    7,
                    value_field="retailUsd",
                    currency="USD",
                    source="ck_retail_nm",
                    require_active=False,
                    require_retail_stock=True,
                    exclude_non_cards=True,
                ),
            },
            "tcgplayer": {
                "label": "TCGplayer参考价",
                "currency": "USD",
                "source": "Scryfall public usd/usd_foil fields",
                "daily": mover_groups(
                    payload,
                    daily_previous,
                    1,
                    value_field="marketUsd",
                    currency="USD",
                    source="scryfall_usd_reference",
                    require_active=False,
                ),
                "weekly": mover_groups(
                    payload,
                    weekly_previous,
                    7,
                    value_field="marketUsd",
                    currency="USD",
                    source="scryfall_usd_reference",
                    require_active=False,
                ),
            },
            "cardmarket": {
                "label": "Cardmarket参考价",
                "currency": "EUR",
                "source": "Scryfall public eur/eur_foil fields",
                "daily": mover_groups(
                    payload,
                    daily_previous,
                    1,
                    value_field="marketEur",
                    currency="EUR",
                    source="scryfall_eur_reference",
                    require_active=False,
                ),
                "weekly": mover_groups(
                    payload,
                    weekly_previous,
                    7,
                    value_field="marketEur",
                    currency="EUR",
                    source="scryfall_eur_reference",
                    require_active=False,
                ),
            },
        },
    }
    with open(ROOT / "movers.json", "w", encoding="utf-8") as f:
        json.dump(movers_payload, f, ensure_ascii=False, separators=(",", ":"))


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
    payload = enrich_market_reference(payload)
    payload = enrich_sealed_images(payload, previous)
    write_payload_files(payload)
    write_fast_payload(payload)
    write_exports(payload)
    weekly_previous = load_git_payload("HEAD~7") or previous
    write_movers(payload, previous, weekly_previous)

    # The uncompressed file is useful locally but too large for GitHub Pages repo.
    (ROOT / "data.json").unlink(missing_ok=True)
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
