"""Maintain exact-print EN/NM CK retail-to-Hareruya buy-price opportunities."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener

from hareruya_capture import timestamp

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "hareruya_opportunities.json"
RETAIL = ROOT / "hareruya_ck_retail.json.gz"
IDENTITIES = ROOT / "hareruya_ck_identities.json.gz"
FX = ROOT / "hareruya_ck_fx.json"
CK_URL = "https://api.cardkingdom.com/api/v2/pricelist"
FX_URL = "https://open.er-api.com/v6/latest/USD"
COLLECTION_URL = "https://api.scryfall.com/cards/collection"
AGES = {"ck": 6, "hareruya": 24, "fx": 72}
SET_ALIASES = {"10ED": "10e", "MPS2": "mp2"}
SPECIAL = re.compile(
    r"serial|signed|signature|etched|surge|textured|galaxy|gilded|confetti|fracture|"
    r"double.?rainbow|step.and.compleat|neon|halo.?foil|mana foil|fractured foil|"
    r"シリアル|サイン|エッチング|サージ|テクスチャ|ギャラクシー|ダブルレインボウ|"
    r"金箔|箔押し|マナ・Foil|ドラフト・セットブースター|コレクター.*ブースター|"
    r"prerelease|promopack|stamp|プレリ|プロモ|記念|FNM|アリーナ|ジャッジ|ボックス|\bBOX\b|大判|エラーカード",
    re.IGNORECASE,
)
NON_ENGLISH = re.compile(r"japanese|\bJPN\b|chinese|korean|phyrexian|german|french|italian|spanish|portuguese|russian|foreign", re.I)
REASONS = {
    "threshold": "CK 售价已达到或超过晴屋收价",
    "nmUnavailable": "CK NM 缺货或未提供 NM 专属报价",
    "hareruyaUnavailable": "晴屋当前没有有效回收报价",
    "hareruyaStale": "晴屋核价过期或采集失败",
    "ckStale": "CK 核价过期或不可用",
    "fxStale": "汇率过期或不可用",
    "identityMissing": "具体印刷版本尚未核实",
    "identityMismatch": "版本、语言或闪别无法对应",
    "ambiguousCK": "CK 存在多个无法区分的版本",
    "ambiguousHareruya": "晴屋存在多个无法区分的版本",
    "notObserved": "未取得当前对应商品报价",
    "specialFinish": "特殊工艺、签名或序列号未能准确对应",
    "numberMissing": "缺少可核对的收藏编号",
    "setUnknown": "系列代码或特殊版本尚未核实",
}


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else Decimal(0)
    except (ValueError, TypeError, InvalidOperation):
        return Decimal(0)


def fresh(value, at, hours):
    age = timestamp(at) - timestamp(value)
    return timedelta(0) <= age <= timedelta(hours=hours)


def normalized(value):
    value = str(value or "").casefold().replace("æ", "ae").replace("œ", "oe")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if c.isalnum())


def number(value):
    value = str(value or "").strip().lower()
    return (value.lstrip("0") or "0") if re.fullmatch(r"\d+[a-z*-]*", value) else ""


def without_names(title):
    return re.sub(r"《[^》]*》", "", title)


def hareruya_identity(row):
    title = row.get("variation") or ""
    if not title or "【EN】" not in title:
        return None, "identityMissing"
    markers = without_names(title)
    if SPECIAL.search(markers):
        return None, "specialFinish"
    tags = re.findall(r"【([^】]+)】", markers)
    if any("foil" in t.lower() and t.lower() != "foil" for t in tags):
        return None, "specialFinish"
    finish = "foil" if any(t.lower() == "foil" for t in tags) else "nonfoil"
    raw_set = row.get("set", "")
    match = re.fullmatch(r"([A-Z0-9]{2,5})(?:-(BF|BS|EX))?", raw_set)
    if not match:
        return None, "setUnknown"
    code = SET_ALIASES.get(match[1], match[1].lower())
    collector = number(row.get("collectorNumber"))
    if not collector:
        return None, "numberMissing"
    # The title must independently contain the identity; old parser leftovers are not proof.
    title_number = re.search(r"\((\d+[A-Za-z*-]*)\)", markers)
    if not title_number or number(title_number[1]) != collector or f"[{raw_set}]" not in title:
        return None, "identityMismatch"
    return (code, collector, finish), ""


def ck_key(row):
    return (str(row.get("scryfallSet", "")).lower(), number(row.get("collectorNumber")), "foil" if row.get("foil") else "nonfoil")


def compact_retail(raw, metadata, requested, at):
    by_sku = {r["sku"]: r for r in metadata["cards"]}
    cards = []
    unmapped = 0
    for item in raw["data"]:
        known = by_sku.get(item.get("sku"))
        if not known or known.get("scryfallId") != item.get("scryfall_id"):
            unmapped += 1
            continue
        foil = item.get("is_foil") is True or str(item.get("is_foil")).lower() == "true"
        card = {k: known.get(k) for k in ("sku", "scryfallId", "scryfallSet", "collectorNumber", "name", "cn", "flavorName")}
        card.update({"foil": foil, "conditions": item.get("condition_values") or {},
                     "edition": item.get("edition", ""), "variation": item.get("variation", ""),
                     "ckName": item.get("name", ""), "ckUrl": urljoin(raw["meta"]["base_url"], item["url"])})
        if ck_key(card) in requested:
            cards.append(card)
    return {"meta": {"capturedAt": at, "sourceCreatedAtRaw": raw["meta"].get("created_at"),
                     "source": CK_URL, "rawProducts": len(raw["data"]), "unmappedProducts": unmapped}, "cards": cards}


def preliminaries(hareruya, retail, fx, at):
    index = defaultdict(list)
    for card in retail.get("cards", []):
        index[ck_key(card)].append(card)
    candidates, reasons, counts = [], {}, Counter()
    rate = decimal(fx.get("rates", {}).get("JPY"))
    ck_fresh = fresh(retail.get("meta", {}).get("capturedAt"), at, AGES["ck"])
    fx_fresh = rate > 0 and fx.get("base_code") == "USD" and fresh(fx.get("sourceAt"), at, AGES["fx"])
    for row in hareruya.get("items", []):
        if row.get("language") != "EN":
            continue
        counts["englishRows"] += 1
        key = f"{row['productId']}|EN"
        identity, reason = hareruya_identity(row)
        if row.get("captureError") or not fresh(row.get("buyCapturedAt"), at, AGES["hareruya"]):
            reason = "hareruyaStale"
        elif decimal(row.get("buy", {}).get("EN")) <= 0 or row.get("buyStatus") == "unavailable":
            reason = "hareruyaUnavailable"
        if not reason and not ck_fresh:
            reason = "ckStale"
        if not reason and not fx_fresh:
            reason = "fxStale"
        matches = index.get(identity, [])
        if not reason and len(matches) != 1:
            reason = "ambiguousCK" if matches else "notObserved"
        if not reason:
            card = matches[0]
            cond = card.get("conditions", {})
            price = decimal(cond.get("nm_price"))
            stock = decimal(cond.get("nm_qty"))
            if price <= 0 or stock <= 0:
                reason = "nmUnavailable"
            elif SPECIAL.search(card.get("variation", "")) or NON_ENGLISH.search(card.get("edition", "") + " " + card.get("variation", "")):
                reason = "identityMismatch"
            elif price * rate >= decimal(row["buy"]["EN"]):
                reason = "threshold"
        if reason:
            reasons[key] = reason
            counts[reason] += 1
        else:
            candidates.append((row, matches[0], identity))
    return candidates, reasons, counts


def valid_print(row, card, identity, exact):
    if not exact or exact.get("id") != card["scryfallId"]:
        return False
    if exact.get("lang") != "en" or exact.get("oversized"):
        return False
    if (exact.get("set"), number(exact.get("collector_number"))) != identity[:2]:
        return False
    if identity[2] not in exact.get("finishes", []):
        return False
    if any(SPECIAL.search(str(t)) for t in (exact.get("promo_types") or [])):
        return False
    names = [exact.get("name"), exact.get("flavor_name")]
    names.extend(face.get("name") for face in (exact.get("card_faces") or []))
    return any(normalized(n) == normalized(row.get("name")) for n in names if n)


def build_feed(hareruya, retail, fx, identities, previous, at, failures=()):
    candidates, reasons, counts = preliminaries(hareruya, retail, fx, at)
    valid = []
    for row, card, identity in candidates:
        exact = identities.get(card["scryfallId"])
        reason = "identityMissing" if not exact else "identityMismatch"
        if not valid_print(row, card, identity, exact):
            reasons[f"{row['productId']}|EN"] = reason
            counts[reason] += 1
            continue
        valid.append((row, card, identity, exact))
    by_print = Counter((card["scryfallId"], identity[2]) for row, card, identity, exact in valid)
    items = []
    rate = decimal(fx.get("rates", {}).get("JPY"))
    for row, card, identity, exact in valid:
        if by_print[(card["scryfallId"], identity[2])] > 1:
            reasons[f"{row['productId']}|EN"] = "ambiguousHareruya"
            counts["ambiguousHareruya"] += 1
            continue
        usd = decimal(card["conditions"]["nm_price"])
        cost = usd * rate
        buy = decimal(row["buy"]["EN"])
        spread = buy - cost
        images = exact.get("image_uris") or (exact.get("card_faces") or [{}])[0].get("image_uris") or {}
        items.append({"key": f"{row['productId']}|EN|{card['sku']}", "productId": row["productId"],
                      "name": exact.get("name", row["name"]), "cn": card.get("cn", ""), "nameJa": row.get("nameJa", ""),
                      "set": exact["set"].upper(), "collectorNumber": exact["collector_number"],
                      "hareruyaSet": row["set"], "hareruyaVariation": row["variation"], "finish": identity[2],
                      "language": "EN", "condition": "NM", "ckSku": card["sku"], "scryfallId": card["scryfallId"],
                      "ckRetailUsd": float(usd), "ckRetailJpy": float(cost), "ckNmQty": int(card["conditions"]["nm_qty"]),
                      "hareruyaBuyJpy": int(buy), "spreadJpy": float(spread), "spreadPct": round(float(spread / cost * 100), 2),
                      "ckCapturedAt": retail["meta"]["capturedAt"], "hareruyaCapturedAt": row["buyCapturedAt"],
                      "image": images.get("normal", ""), "ckUrl": card["ckUrl"],
                      "hareruyaUrl": f"https://www.hareruyamtg.com/ja/purchase/detail/{row['productId']}?lang=EN",
                      "scryfallUrl": exact.get("scryfall_uri", "")})
    items.sort(key=lambda r: (-r["spreadJpy"], r["key"]))
    now_by_key = {r["key"]: r for r in items}
    old_by_key = {r["key"]: r for r in previous.get("items", [])}
    events = list(previous.get("events", []))
    added, removed = 0, 0
    if previous:
        for key in now_by_key.keys() - old_by_key.keys():
            card = now_by_key[key]
            events.append({"at": at, "type": "added", "key": key, "name": card["name"],
                           "version": f"{card['set']} #{card['collectorNumber']} {card['finish']}", "reason": "CK 售价低于晴屋收价"})
            added += 1
        for key in old_by_key.keys() - now_by_key.keys():
            card = old_by_key[key]
            reason = reasons.get(f"{card['productId']}|EN", "notObserved")
            events.append({"at": at, "type": "removed", "key": key, "name": card["name"],
                           "version": f"{card['set']} #{card['collectorNumber']} {card['finish']}", "reason": REASONS[reason]})
            removed += 1
    cutoff = timestamp(at) - timedelta(days=7)
    events = sorted((e for e in events if timestamp(e["at"]) >= cutoff), key=lambda e: (e["at"], e["key"]), reverse=True)[:500]
    return {"meta": {"generatedAt": at, "hareruyaDataAt": hareruya.get("meta", {}).get("generatedAt"),
                     "ckCapturedAt": retail.get("meta", {}).get("capturedAt"), "ckSourceCreatedAtRaw": retail.get("meta", {}).get("sourceCreatedAtRaw"),
                     "fxAt": fx.get("sourceAt"), "usdJpy": float(rate), "usdCny": float(decimal(fx.get("rates", {}).get("CNY"))),
                     "fxSource": FX_URL, "ckSource": CK_URL, "hareruyaSource": "https://www.hareruyamtg.com/ja/purchase/",
                     "status": "partial" if failures else "ok", "failures": list(failures), "maxAgeHours": AGES,
                     "rule": "CK EN NM in-stock retail USD * USDJPY < Hareruya EN NM buy JPY",
                     "automatic": True, "items": len(items), "screenedEnglish": counts.pop("englishRows", 0),
                     "excluded": dict(counts), "refreshIntervalMinutes": 30,
                     "initialBaseline": not bool(previous), "lastRunAdded": added, "lastRunRemoved": removed},
            "items": items, "events": events}


def read_json(path, zipped=False, default=None):
    if not path.exists():
        return default if default is not None else {}
    with (gzip.open(path, "rt", encoding="utf-8") if zipped else path.open(encoding="utf-8")) as handle:
        return json.load(handle)


def write_json(path, payload, zipped=False):
    temp = path.with_suffix(".tmp")
    with (gzip.open(temp, "wt", encoding="utf-8") if zipped else temp.open("w", encoding="utf-8")) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def fetch_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "ck-mtg-buylist-viewer/1.0", "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=120) as response:
        return json.load(response)


def refresh(ck_path=None, fx_path=None, no_network=False):
    at = iso_now()
    hareruya = read_json(ROOT / "hareruya_prices.json")
    metadata = read_json(ROOT / "data.json.gz", zipped=True)
    requested = {identity for row in hareruya.get("items", []) if row.get("language") == "EN" for identity, _ in [hareruya_identity(row)] if identity}
    failures = []
    if hareruya.get("meta", {}).get("status") == "partial":
        failures.append("Hareruya: partial capture; invalid rows excluded")
    retail = read_json(RETAIL, zipped=True)
    fx = read_json(FX)
    identities = read_json(IDENTITIES, zipped=True)
    if not no_network:
        try:
            raw = read_json(ck_path) if ck_path else fetch_json(CK_URL)
            if len(raw.get("data", [])) < 1000:
                raise ValueError("CK snapshot unexpectedly small")
            captured = datetime.fromtimestamp(ck_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds") if ck_path else iso_now()
            retail = compact_retail(raw, metadata, requested, captured)
            write_json(RETAIL, retail, zipped=True)
        except Exception as error:
            failures.append(f"CK: {type(error).__name__}; previous capture retained")
        try:
            current = read_json(fx_path) if fx_path else fetch_json(FX_URL)
            if current.get("result") != "success" or current.get("base_code") != "USD" or decimal(current.get("rates", {}).get("JPY")) <= 0:
                raise ValueError("USD/JPY quote missing")
            fx = {"base_code": "USD", "rates": {k: current["rates"][k] for k in ("JPY", "CNY")},
                  "sourceAt": datetime.fromtimestamp(current["time_last_update_unix"], timezone.utc).isoformat(timespec="seconds"), "acquiredAt": iso_now()}
            write_json(FX, fx)
        except Exception as error:
            failures.append(f"FX: {type(error).__name__}; previous rate retained")
    # Acquisition may take minutes; evaluate freshness at the completed capture time.
    at = iso_now()
    candidates, _, _ = preliminaries(hareruya, retail, fx, at)
    missing = sorted({c["scryfallId"] for row, c, key in candidates if c.get("scryfallId") and c["scryfallId"] not in identities})
    if not no_network:
        for offset in range(0, len(missing), 75):
            batch = missing[offset:offset + 75]
            try:
                response = fetch_json(COLLECTION_URL, {"identifiers": [{"id": sid} for sid in batch]})
                for card in response.get("data", []):
                    if card.get("id") in batch:
                        identities[card["id"]] = {k: card.get(k) for k in ("id", "name", "flavor_name", "lang", "set", "collector_number", "finishes", "promo_types", "oversized", "card_faces", "image_uris", "scryfall_uri")}
                        identities[card["id"]]["promo_types"] = card.get("promo_types") or []
                write_json(IDENTITIES, identities, zipped=True)
                time.sleep(0.12)
            except Exception as error:
                failures.append(f"Scryfall: {type(error).__name__}; unverified identities excluded")
    feed = build_feed(hareruya, retail, fx, identities, read_json(FEED), iso_now(), failures)
    write_json(FEED, feed)
    print(json.dumps(feed["meta"], ensure_ascii=False))
    return feed


def validate_outputs():
    feed = read_json(FEED)
    hareruya = read_json(ROOT / "hareruya_prices.json")
    retail = read_json(RETAIL, zipped=True)
    fx = read_json(FX)
    identities = read_json(IDENTITIES, zipped=True)
    assert feed["meta"]["hareruyaDataAt"] == hareruya["meta"]["generatedAt"]
    rebuilt = build_feed(hareruya, retail, fx, identities, {}, feed["meta"]["generatedAt"])
    assert feed["items"] == rebuilt["items"], "published rows differ from verified same-print quotes"
    assert len({r["key"] for r in feed["items"]}) == len(feed["items"])
    assert all(r["spreadJpy"] > 0 and r["ckNmQty"] > 0 and r["language"] == "EN" and r["condition"] == "NM" for r in feed["items"])
    assert feed["meta"]["items"] == len(feed["items"])
    print(f"Validated {len(feed['items'])} same-print EN/NM price opportunities")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ck-json", type=Path)
    parser.add_argument("--fx-json", type=Path)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_outputs()
    else:
        refresh(args.ck_json, args.fx_json, args.no_network)
