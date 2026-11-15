"""Maintain exact-print EN/NM CK retail-to-Hareruya buy-price opportunities."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
import re
import time
from threading import Event
import unicodedata
from urllib.parse import urlencode, urljoin
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hareruya_capture import timestamp
from hareruya_movements import SOURCES, epoch

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "hareruya_opportunities.json"
RETAIL = ROOT / "hareruya_ck_retail.json.gz"
IDENTITIES = ROOT / "hareruya_ck_identities.json.gz"
FX = ROOT / "hareruya_ck_fx.json"
CATALOG = ROOT / "hareruya_opportunity_catalog.json.gz"
HISTORY = ROOT / "hareruya_history.json.gz"
RESOLUTIONS = ROOT / "hareruya_ck_resolutions.json.gz"
TRANSPORT_DAYS = 30
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
    "ambiguousPrint": "同系列同闪别存在多种印刷，不能仅按牌名对齐",
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
    value = str(value or "").strip().lower().replace("★", "*")
    return (value.lstrip("0") or "0") if re.fullmatch(r"\d+[a-z*-]*", value) else ""


def without_names(title):
    return re.sub(r"《[^》]*》", "", title)


def resolution_key(row, code, finish):
    return f"{normalized(row.get('name'))}|{code}|{finish}"


def hareruya_identity(row, resolutions=None, at=None):
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
    if f"[{raw_set}]" not in title:
        return None, "identityMismatch"
    collector = number(row.get("collectorNumber"))
    # The title must independently contain the identity; old parser leftovers are not proof.
    title_number = re.search(r"\((\d+[A-Za-z★*-]*)\)", markers)
    if not title_number:
        entry = (resolutions or {}).get(resolution_key(row, code, finish), {})
        prints = [c for c in entry.get("cards", []) if finish in c.get("finishes", [])]
        title_names = " // ".join(pair[1].strip() for pair in re.findall(r"《([^/》]+)/([^》]+)》", title))
        if normalized(title_names) != normalized(row.get("name")):
            return None, "identityMismatch"
        if entry.get("complete") is True and len(prints) > 1:
            return None, "ambiguousPrint"
        if entry.get("complete") is True and len(prints) == 1 and fresh(entry.get("checkedAt"), at or iso_now(), 168):
            exact = prints[0]
            if number(exact.get("collector_number")) and exact.get("lang") == "en" and exact.get("set") == code and finish in exact.get("finishes", []) and normalized(exact.get("name")) == normalized(row.get("name")) and not exact.get("oversized") and not any(SPECIAL.search(str(t)) for t in (exact.get("promo_types") or [])):
                return (code, number(exact.get("collector_number")), finish), ""
        return None, "numberMissing"
    if not collector:
        return None, "numberMissing"
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
                     "cashUsd": float(decimal(item.get("price_buy"))), "qtyBuying": int(decimal(item.get("qty_buying"))),
                     "edition": item.get("edition", ""), "variation": item.get("variation", ""),
                     "ckName": item.get("name", ""), "ckUrl": urljoin(raw["meta"]["base_url"], item["url"])})
        if ck_key(card) in requested:
            cards.append(card)
    return {"meta": {"capturedAt": at, "sourceCreatedAtRaw": raw["meta"].get("created_at"),
                     "source": CK_URL, "rawProducts": len(raw["data"]), "unmappedProducts": unmapped}, "cards": cards}


def preliminaries(hareruya, retail, fx, at, resolutions=None):
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
        identity, reason = hareruya_identity(row, resolutions, at)
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


def observation_summary(row, history, at, cost):
    now = epoch(at)
    start = now - TRANSPORT_DAYS * 86400
    key = f"{row['productId']}|EN"
    points = {int(t): int(p) for t, p in history.get("records", {}).get(key, {}).get("buy", [])
              if start <= t <= now and p >= 0}
    captured = epoch(row.get("buyCapturedAt"))
    value = row.get("buy", {}).get("EN")
    if row.get("source") in SOURCES and not row.get("captureError") and value is not None and start <= captured <= now and decimal(value) >= 0:
        points[captured] = int(value)
    ordered = sorted(points.items())
    days = len({(now - t) // 86400 for t in points if t > start})
    boundaries = [start, *(t for t, _ in ordered), now]
    gap = max((b - a for a, b in zip(boundaries, boundaries[1:])), default=now-start)
    minimum = min(points.values(), default=None)
    return {"periodDays": TRANSPORT_DAYS, "samples": len(points), "observedDays": days,
            "coverageComplete": days >= TRANSPORT_DAYS and gap <= 2 * 86400 and bool(ordered) and ordered[-1][0] >= now - 86400,
            "maxGapHours": round(gap / 3600, 1), "minimumJpy": minimum,
            "stopObserved": any(p == 0 for p in points.values()),
            "floorSpreadJpy": float(decimal(minimum) - cost) if minimum is not None and cost is not None else None}


def build_catalog(hareruya, retail, fx, identities, history, at, resolutions=None):
    index = defaultdict(list)
    for card in retail.get("cards", []):
        index[ck_key(card)].append(card)
    english = [row for row in hareruya.get("items", []) if row.get("language") == "EN"]
    parsed = [(row, *hareruya_identity(row, resolutions, at)) for row in english]
    duplicates = Counter(identity for _, identity, _ in parsed if identity)
    rate = decimal(fx.get("rates", {}).get("JPY"))
    ck_at = retail.get("meta", {}).get("capturedAt")
    ck_current = fresh(ck_at, at, AGES["ck"])
    fx_current = rate > 0 and fx.get("base_code") == "USD" and fresh(fx.get("sourceAt"), at, AGES["fx"])
    rows, counts = [], Counter()
    for row, identity, reason in parsed:
        captured = row.get("buyCapturedAt")
        quote_status = "failed" if row.get("captureError") else "current" if fresh(captured, at, AGES["hareruya"]) else "historical" if epoch(captured) else "unknown"
        matches = index.get(identity, [])
        card, exact = None, None
        if not reason and len(matches) != 1:
            reason = "ambiguousCK" if matches else "notObserved"
        if not reason:
            candidate = matches[0]
            exact = identities.get(candidate.get("scryfallId"))
            if not exact:
                reason = "identityMissing"
            elif not valid_print(row, candidate, identity, exact) or SPECIAL.search(candidate.get("variation", "")) or NON_ENGLISH.search(candidate.get("edition", "") + " " + candidate.get("variation", "")):
                reason = "identityMismatch"
            elif duplicates[identity] > 1:
                reason = "ambiguousHareruya"
            else:
                card = candidate
        status = reason or "verified"
        price = decimal(card.get("conditions", {}).get("nm_price")) if card else Decimal(0)
        stock = int(decimal(card.get("conditions", {}).get("nm_qty"))) if card else None
        cost = price * rate if price > 0 and rate > 0 else None
        raw_buy = row.get("buy", {}).get("EN")
        buy = decimal(raw_buy) if raw_buy is not None else None
        spread = buy - cost if buy is not None and buy > 0 and cost is not None else None
        available = buy is not None and buy > 0 and row.get("buyStatus") != "unavailable"
        current = bool(card and price > 0 and stock > 0 and available and quote_status == "current" and ck_current and fx_current)
        markers = without_names(row.get("variation") or "")
        finish = identity[2] if identity else "special" if SPECIAL.search(markers) else "foil" if "【Foil】" in markers else "nonfoil" if "【EN】" in markers else "unknown"
        images = (exact.get("image_uris") or (exact.get("card_faces") or [{}])[0].get("image_uris") or {}) if card else {}
        observation = observation_summary(row, history, at, cost)
        sale = decimal(row.get("sale", {}).get("EN", {}).get("NM"))
        sale_qty = row.get("saleStock", {}).get("EN", {}).get("NM")
        cash = decimal(card.get("cashUsd")) if card else Decimal(0)
        buying_qty = int(decimal(card.get("qtyBuying"))) if card else 0
        cash_jpy = cash * rate if cash > 0 and rate > 0 else None
        reverse_current = bool(card and cash > 0 and buying_qty > 0 and sale > 0 and sale_qty is not None and sale_qty > 0
                               and row.get("retailVerified") is True and not row.get("saleCaptureError")
                               and fresh(row.get("saleCapturedAt"), at, AGES["hareruya"]) and ck_current and fx_current)
        rows.append({"key": f"{row['productId']}|EN", "productId": row["productId"],
                     "name": row.get("name", ""), "nameJa": row.get("nameJa", ""), "cn": card.get("cn", "") if card else "",
                     "set": exact["set"].upper() if card else row.get("set", ""),
                     "collectorNumber": exact["collector_number"] if card else row.get("collectorNumber", ""),
                     "hareruyaVariation": row.get("variation", ""), "finish": finish, "language": "EN", "condition": "NM",
                     "matchStatus": status, "quoteStatus": quote_status, "currentComparison": current, "buyAvailable": bool(available),
                     "ckSku": card["sku"] if card else "", "ckUrl": card["ckUrl"] if card else "",
                     "ckRetailUsd": float(price) if price > 0 else None, "ckRetailJpy": float(cost) if cost is not None else None,
                     "ckNmQty": stock, "ckCapturedAt": ck_at if card else None,
                     "identityMethod": "explicitCollector" if re.search(r"\(\d+[A-Za-z★*-]*\)", markers) else "uniqueScryfallPrint" if card else "unverified",
                     "hareruyaSaleJpy": float(sale) if sale > 0 else None, "hareruyaNmQty": sale_qty,
                     "saleCapturedAt": row.get("saleCapturedAt"), "saleCaptureError": bool(row.get("saleCaptureError")),
                     "ckCashUsd": float(cash) if cash > 0 else None, "ckCashJpy": float(cash_jpy) if cash_jpy is not None else None,
                     "ckBuyingQty": buying_qty, "reverseCurrent": reverse_current,
                     "reverseEligible": bool(reverse_current and sale < cash_jpy * Decimal("0.7")),
                     "reverseSpreadJpy": float(cash_jpy - sale) if cash_jpy is not None and sale > 0 else None,
                     "reverseBufferJpy": float(cash_jpy * Decimal("0.7") - sale) if cash_jpy is not None and sale > 0 else None,
                     "hareruyaSaleUrl": f"https://www.hareruyamtg.com/ja/products/detail/{row['productId']}?lang=EN",
                     "hareruyaBuyJpy": int(buy) if buy is not None else None, "hareruyaCapturedAt": captured,
                     "spreadJpy": float(spread) if spread is not None else None,
                     "spreadPct": round(float(spread / cost * 100), 2) if spread is not None else None,
                     "image": images.get("normal") or row.get("image", ""),
                     "hareruyaUrl": f"https://www.hareruyamtg.com/ja/purchase/detail/{row['productId']}?lang=EN",
                     "observation": observation})
        counts[quote_status] += 1
        counts["matched" if card else "unmatched"] += 1
        counts["observed30Days"] += int(observation["coverageComplete"])
    rows.sort(key=lambda r: (r["spreadJpy"] is None, -(r["spreadJpy"] or 0), r["name"], r["key"]))
    summary = {"path": CATALOG.name, "items": len(rows), "transportDays": TRANSPORT_DAYS, **dict(counts)}
    summary["pending"] = sum(counts[k] for k in ("historical", "failed", "unknown"))
    return {"meta": {"generatedAt": at, **summary}, "items": rows}


def build_feed(hareruya, retail, fx, identities, previous, at, failures=(), history=None, resolutions=None):
    candidates, reasons, counts = preliminaries(hareruya, retail, fx, at, resolutions)
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
    by_identity = Counter(identity for row in hareruya.get("items", []) if row.get("language") == "EN"
                          for identity, _ in [hareruya_identity(row, resolutions, at)] if identity)
    items = []
    rate = decimal(fx.get("rates", {}).get("JPY"))
    for row, card, identity, exact in valid:
        if by_print[(card["scryfallId"], identity[2])] > 1 or by_identity[identity] > 1:
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
    catalog = build_catalog(hareruya, retail, fx, identities, history or {}, at, resolutions)
    reverse = sorted((r for r in catalog["items"] if r["reverseEligible"]), key=lambda r: -r["reverseBufferJpy"])
    return {"meta": {"generatedAt": at, "hareruyaDataAt": hareruya.get("meta", {}).get("generatedAt"),
                     "ckCapturedAt": retail.get("meta", {}).get("capturedAt"), "ckSourceCreatedAtRaw": retail.get("meta", {}).get("sourceCreatedAtRaw"),
                     "fxAt": fx.get("sourceAt"), "usdJpy": float(rate), "usdCny": float(decimal(fx.get("rates", {}).get("CNY"))),
                     "fxSource": FX_URL, "ckSource": CK_URL, "hareruyaSource": "https://www.hareruyamtg.com/ja/purchase/",
                     "status": "partial" if failures else "ok", "failures": list(failures), "maxAgeHours": AGES,
                     "rule": "CK EN NM in-stock retail USD * USDJPY < Hareruya EN NM buy JPY",
                     "automatic": True, "items": len(items), "reverseItems": len(reverse), "catalog": catalog["meta"], "screenedEnglish": counts.pop("englishRows", 0),
                     "excluded": dict(counts), "refreshIntervalMinutes": 30,
                     "initialBaseline": not bool(previous), "lastRunAdded": added, "lastRunRemoved": removed},
            "items": items, "reverseItems": reverse, "events": events, "catalog": catalog}


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


def refresh_resolutions(hareruya, metadata, resolutions, identities, at, limit, failures):
    known = {(normalized(c.get("name")), str(c.get("scryfallSet", "")).lower()) for c in metadata.get("cards", [])}
    pending = {}
    for row in hareruya.get("items", []):
        if row.get("language") != "EN" or hareruya_identity(row)[1] != "numberMissing":
            continue
        title = row.get("variation", "")
        match = re.fullmatch(r"([A-Z0-9]{2,5})(?:-(BF|BS|EX))?", row.get("set", ""))
        if not match:
            continue
        code = SET_ALIASES.get(match[1], match[1].lower())
        if (normalized(row.get("name")), code) not in known:
            continue
        finish = "foil" if any(t.lower() == "foil" for t in re.findall(r"【([^】]+)】", without_names(title))) else "nonfoil"
        key = resolution_key(row, code, finish)
        if key in resolutions and fresh(resolutions[key].get("checkedAt"), at, 168):
            continue
        pending[key] = (row, code)
    ordered = sorted(pending.items(), key=lambda p: -decimal(p[1][0].get("buy", {}).get("EN")))[:limit]
    stopped = Event()
    def lookup(item):
        key, (row, code) = item
        if stopped.is_set():
            return key, None, None
        query = f'!{json.dumps(row["name"],ensure_ascii=False)} set:{code} lang:en'
        url = "https://api.scryfall.com/cards/search?" + urlencode({"q": query, "unique": "prints", "include_extras": "true", "include_variations": "true"})
        try:
            time.sleep(0.35)
            response = fetch_json(url)
            if response.get("object") != "list" or not isinstance(response.get("data"), list):
                raise ValueError("invalid exact-print search response")
            cards = []
            for card in response["data"]:
                exact = {k: card.get(k) for k in ("id", "name", "flavor_name", "lang", "set", "collector_number", "finishes", "promo_types", "oversized", "card_faces", "image_uris", "scryfall_uri")}
                exact["promo_types"] = card.get("promo_types") or []
                cards.append(exact)
            return key, {"query": query, "source": url, "checkedAt": iso_now(), "complete": response.get("has_more") is False, "cards": cards}, None
        except HTTPError as error:
            if error.code == 404:
                return key, {"query": query, "source": url, "checkedAt": iso_now(), "complete": True, "cards": []}, None
            else:
                stopped.set()
                return key, None, f"Scryfall print resolution: HTTP {error.code}; previous proofs retained"
        except Exception as error:
            stopped.set()
            return key, None, f"Scryfall print resolution: {type(error).__name__}; previous proofs retained"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(lookup, item) for item in ordered]
        completed = 0
        for future in as_completed(futures):
            key, entry, error = future.result()
            if error and error not in failures:
                failures.append(error)
            if entry:
                resolutions[key] = entry
                identities.update({c["id"]:c for c in entry["cards"]})
                write_json(RESOLUTIONS, resolutions, zipped=True)
                write_json(IDENTITIES, identities, zipped=True)
                completed += 1
                if completed % 20 == 0:
                    print(json.dumps({"printProofsCompleted":completed,"requested":len(ordered)}), flush=True)


def refresh(ck_path=None, fx_path=None, no_network=False, resolution_limit=120):
    at = iso_now()
    hareruya = read_json(ROOT / "hareruya_prices.json")
    metadata = read_json(ROOT / "data.json.gz", zipped=True) if not no_network else {}
    failures = []
    if hareruya.get("meta", {}).get("status") == "partial":
        failures.append("Hareruya: partial capture; invalid rows excluded")
    retail = read_json(RETAIL, zipped=True)
    fx = read_json(FX)
    identities = read_json(IDENTITIES, zipped=True)
    resolutions = read_json(RESOLUTIONS, zipped=True)
    if not no_network:
        refresh_resolutions(hareruya, metadata, resolutions, identities, iso_now(), resolution_limit, failures)
    write_json(RESOLUTIONS, resolutions, zipped=True)
    requested = {identity for row in hareruya.get("items", []) if row.get("language") == "EN" for identity, _ in [hareruya_identity(row, resolutions, iso_now())] if identity}
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
    # Identity verification covers historical quotes too; freshness only gates the live board.
    missing = sorted({c["scryfallId"] for c in retail.get("cards", [])
                      if c.get("scryfallId") and c["scryfallId"] not in identities})
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
    feed = build_feed(hareruya, retail, fx, identities, read_json(FEED), iso_now(), failures, read_json(HISTORY, zipped=True), resolutions)
    write_json(CATALOG, feed.pop("catalog"), zipped=True)
    write_json(FEED, feed)
    print(json.dumps(feed["meta"], ensure_ascii=False))
    return feed


def validate_outputs():
    feed = read_json(FEED)
    hareruya = read_json(ROOT / "hareruya_prices.json")
    retail = read_json(RETAIL, zipped=True)
    fx = read_json(FX)
    identities = read_json(IDENTITIES, zipped=True)
    history = read_json(HISTORY, zipped=True)
    catalog = read_json(CATALOG, zipped=True)
    resolutions = read_json(RESOLUTIONS, zipped=True)
    assert feed["meta"]["hareruyaDataAt"] == hareruya["meta"]["generatedAt"]
    rebuilt = build_feed(hareruya, retail, fx, identities, {}, feed["meta"]["generatedAt"], history=history, resolutions=resolutions)
    assert feed["items"] == rebuilt["items"], "published rows differ from verified same-print quotes"
    assert len({r["key"] for r in feed["items"]}) == len(feed["items"])
    assert all(r["spreadJpy"] > 0 and r["ckNmQty"] > 0 and r["language"] == "EN" and r["condition"] == "NM" for r in feed["items"])
    assert feed["meta"]["items"] == len(feed["items"])
    assert feed["reverseItems"] == rebuilt["reverseItems"]
    assert all(r["reverseEligible"] and r["hareruyaNmQty"] > 0 and r["ckBuyingQty"] > 0 and decimal(r["hareruyaSaleJpy"]) < decimal(r["ckCashUsd"]) * decimal(feed["meta"]["usdJpy"]) * Decimal("0.7") for r in feed["reverseItems"])
    assert catalog == rebuilt["catalog"], "full English search catalogue differs from retained source quotes"
    assert feed["meta"]["catalog"] == catalog["meta"]
    catalog_by_product = {r["productId"]:r for r in catalog["items"]}
    assert all(catalog_by_product[r["productId"]]["matchStatus"] == "verified" and catalog_by_product[r["productId"]]["ckSku"] == r["ckSku"] for r in feed["items"])
    expected = {f"{r['productId']}|EN" for r in hareruya["items"] if r.get("language") == "EN"}
    assert {r["key"] for r in catalog["items"]} == expected and len(catalog["items"]) == len(expected)
    print(f"Validated {len(feed['items'])} live opportunities and all {len(expected)} English search records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ck-json", type=Path)
    parser.add_argument("--fx-json", type=Path)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--resolution-limit", type=int, default=120)
    args = parser.parse_args()
    if args.validate:
        validate_outputs()
    else:
        if not 0 <= args.resolution_limit <= 500:
            parser.error("resolution limit must be between 0 and 500")
        refresh(args.ck_json, args.fx_json, args.no_network, args.resolution_limit)
