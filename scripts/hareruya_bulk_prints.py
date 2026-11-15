"""Read the official default-card bulk file, preserving exact print evidence."""

import gzip
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from hareruya_capture import timestamp

FIELDS = ("id", "name", "flavor_name", "lang", "set", "collector_number", "finishes", "promo_types", "oversized", "card_faces", "image_uris", "scryfall_uri")


def read_cards(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        if ".jsonl" in str(path):
            for line in handle:
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict) or not value.get("id"):
                        raise ValueError("invalid bulk card record")
                    yield value
        else:
            data = json.load(handle)
            if not isinstance(data, list):
                raise ValueError("invalid bulk card array")
            yield from data


def acquire(cache_dir, at):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "default-meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        path = cache_dir / meta.get("file", "missing")
        age = timestamp(at) - timestamp(meta.get("updated_at"))
        if meta.get("validated") is True and timedelta(0) <= age <= timedelta(hours=30) and path.is_file() and path.stat().st_size == meta.get("bytes"):
            return path, meta
    opener = build_opener(ProxyHandler({}))
    headers = {"User-Agent":"ck-mtg-buylist-viewer/1.0", "Accept":"application/json"}
    with opener.open(Request("https://api.scryfall.com/bulk-data", headers=headers), timeout=120) as response:
        catalog = json.load(response)
    record = next(r for r in catalog["data"] if r.get("type") == "default_cards")
    url = record.get("jsonl_download_uri") or record.get("download_uri")
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.hostname not in {"data.scryfall.io", "data.scryfall.com"}:
        raise ValueError("untrusted default-card download URL")
    age = timestamp(at) - timestamp(record.get("updated_at"))
    if not timedelta(0) <= age <= timedelta(hours=30):
        raise ValueError("default-card bulk metadata is stale")
    path = cache_dir / ("default.jsonl.gz" if record.get("jsonl_download_uri") else "default.json")
    temp = path.with_suffix(".download")
    try:
        with opener.open(Request(url, headers=headers), timeout=120) as response, temp.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    meta = {"file":path.name, "source":url, "updated_at":record["updated_at"], "acquiredAt":at, "bytes":path.stat().st_size, "validated":False}
    meta_path.write_text(json.dumps(meta) + "\n")
    return path, meta


def build_proofs(cards, hareruya, at, source, source_at):
    from build_hareruya_opportunities import SET_ALIASES, name_key, card_name_keys, resolution_key, without_names
    import re
    wanted, targets = set(), []
    for row in hareruya.get("items", []):
        match = re.fullmatch(r"([A-Z0-9]{2,5})(?:-(BF|BS|EX))?", row.get("set", ""))
        if row.get("language") != "EN" or not match:
            continue
        code = SET_ALIASES.get(match[1], match[1].lower())
        wanted.add((name_key(row.get("name")), code))
        if "【EN】" in row.get("variation", ""):
            finish = "foil" if "【foil】" in without_names(row["variation"]).lower() else "nonfoil"
            targets.append((row, code, finish))
    groups, identities = defaultdict(dict), {}
    for card in cards:
        if not isinstance(card.get("finishes"), list) or not card.get("lang") or not card.get("set") or not card.get("collector_number"):
            raise ValueError("incomplete bulk print record; uniqueness cannot be established")
        if card.get("lang") != "en":
            continue
        keys = {(key, card.get("set")) for key in card_name_keys(card)} & wanted
        if not keys:
            continue
        exact = {k:card.get(k) for k in FIELDS}
        exact["promo_types"] = card.get("promo_types") or []
        identities[card["id"]] = exact
        for key in keys:
            groups[key][card["id"]] = exact
    resolutions = {}
    for row, code, finish in targets:
        key = resolution_key(row, code, finish)
        resolutions[key] = {"source":source, "sourceUpdatedAt":source_at, "acquiredAt":at,
                            "checkedAt":source_at, "complete":True, "method":"officialDefaultCardsBulk",
                            "cards":list(groups[(name_key(row.get("name")), code)].values())}
    return resolutions, identities
