"""Keep actual quote observations and compare first/last samples inside a window."""

import argparse
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hareruya_capture import timestamp

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "hareruya_history.json.gz"
FEED = ROOT / "hareruya_movers.json"
WINDOWS = {"hour": 1, "day": 24, "threeDay": 72, "week": 168}
SOURCES = {"publicListing", "priorityProbe", "verifiedDetail"}
DAY = 86400


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def epoch(value):
    dt = timestamp(value)
    return int(dt.timestamp()) if dt.year >= 2000 else 0


def row_key(row):
    return f"{row['productId']}|{row['language']}"


def load_history():
    if not HISTORY.exists():
        return {"schemaVersion": 1, "records": {}}
    with gzip.open(HISTORY, "rt", encoding="utf-8") as handle:
        history = json.load(handle)
    if history.get("schemaVersion") != 1 or not isinstance(history.get("records"), dict):
        raise ValueError("invalid Hareruya observation history")
    return history


def observe(history, payload, at):
    limit = epoch(at)
    added = 0
    for row in payload.get("items", []):
        if row.get("source") not in SOURCES or row.get("language") not in {"JP", "EN"} or not str(row.get("productId", "")).isdigit():
            continue
        language = row["language"]
        quotes = [
            ("buy", row.get("buy", {}).get(language), row.get("buyCapturedAt") or row.get("capturedAt"), row.get("captureError")),
            ("sale", row.get("sale", {}).get(language, {}).get("NM"), row.get("saleCapturedAt"), row.get("saleCaptureError")),
        ]
        for metric, value, captured, failed in quotes:
            observed_at = epoch(captured)
            if failed or value is None or not observed_at or observed_at > limit:
                continue
            try:
                price = int(value)
            except (ValueError, TypeError):
                continue
            if price < 0:
                continue
            points = history["records"].setdefault(row_key(row), {}).setdefault(metric, [])
            if points and observed_at <= points[-1][0]:
                continue
            points.append([observed_at, price])
            added += 1
    return added


def prune(history, at):
    cutoff = epoch(at) - 8 * DAY
    for record in history["records"].values():
        for metric, points in record.items():
            recent = [point for point in points if point[0] >= cutoff]
            older = [point for point in points if point[0] < cutoff]
            record[metric] = ([older[-1]] if older else []) + recent


def comparison(points, start, end):
    # Never carry an old change into a short window or treat a stop-buying zero as a price cut.
    valid = [p for p in points if start <= p[0] <= end]
    last_stop = max((i for i, point in enumerate(valid) if point[1] <= 0), default=-1)
    valid = valid[last_stop + 1:]
    if len(valid) < 2:
        return None
    return valid[0], valid[-1]


def build_feed(history, payload, at):
    now = epoch(at)
    cards = {}
    periods = {}
    rows = {row_key(r): r for r in payload.get("items", [])}
    for period, hours in WINDOWS.items():
        start = now - hours * 3600
        section = {"hours": hours, "from": iso(start)}
        for metric in ("buy", "sale"):
            changes = []
            comparable = 0
            for key, record in history["records"].items():
                row = rows.get(key)
                if not row or row.get("captureError" if metric == "buy" else "saleCaptureError"):
                    continue
                points = record.get(metric, [])
                if not points or points[-1][0] < now - DAY:
                    continue
                captured = (row.get("buyCapturedAt") or row.get("capturedAt")) if metric == "buy" else row.get("saleCapturedAt")
                price = row.get("buy", {}).get(row["language"]) if metric == "buy" else row.get("sale", {}).get(row["language"], {}).get("NM")
                if epoch(captured) != points[-1][0] or price != points[-1][1]:
                    continue
                pair = comparison(points, start, now)
                if not pair:
                    continue
                comparable += 1
                first, last = pair
                delta = last[1] - first[1]
                if not delta:
                    continue
                changes.append({"key": key, "previousJpy": first[1], "currentJpy": last[1],
                                "deltaJpy": delta, "deltaPct": round(delta / first[1] * 100, 2),
                                "previousAt": iso(first[0]), "currentAt": iso(last[0])})
                cards[key] = {k: row.get(k) for k in ("productId", "language", "name", "nameJa", "set", "collectorNumber", "variation", "foil", "image", "buyUrl", "saleUrl")}
            section[metric] = {"items": sorted(changes, key=lambda r: -abs(r["deltaJpy"])), "comparable": comparable}
        periods[period] = section
    observations = sum(len(points) for record in history["records"].values() for points in record.values())
    return {"meta": {"generatedAt": at, "dataAt": payload.get("meta", {}).get("generatedAt"),
                     "latestCaptureAt": payload.get("meta", {}).get("lastSuccessfulAt") or payload.get("meta", {}).get("generatedAt"),
                     "source": "晴屋官网统一回收价 / 已核验 NM 售价", "scope": "Hareruya online official prices",
                     "currency": "JPY", "sampleIntervalMinutes": 30, "trackedProducts": len(history["records"]),
                     "observations": observations, "freshQuotes": payload.get("meta", {}).get("freshItems", 0),
                     "comparison": "first_and_last_verified_observation_within_window", "captureStatus": payload.get("meta", {}).get("status", "unknown")},
            "cards": cards, "periods": periods}


def write_outputs(history, payload, at):
    prune(history, at)
    history["updatedAt"] = at
    feed = build_feed(history, payload, at)
    temp = HISTORY.with_suffix(".tmp")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(history, handle, ensure_ascii=False, separators=(",", ":"))
    temp.replace(HISTORY)
    temp = FEED.with_suffix(".tmp")
    temp.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(FEED)
    return feed


def record_refresh(previous, current, at):
    history = load_history()
    observe(history, previous, at)
    observe(history, current, at)
    return write_outputs(history, current, at)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-dir", type=Path)
    args = parser.parse_args()
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = load_history()
    if args.bootstrap_dir:
        for path in sorted(args.bootstrap_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            observe(history, payload, at)
    payload = json.loads((ROOT / "hareruya_prices.json").read_text(encoding="utf-8"))
    observe(history, payload, at)
    feed = write_outputs(history, payload, at)
    print(json.dumps({"meta": feed["meta"], "changes": {k: {m: len(v[m]["items"]) for m in ("buy", "sale")} for k, v in feed["periods"].items()}}, ensure_ascii=False))
