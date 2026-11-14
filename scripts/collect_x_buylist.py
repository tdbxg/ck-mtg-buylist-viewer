#!/usr/bin/env python3
"""Archive verified public Hareruya X posts without inferring image prices."""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from hareruya_capture import Document
from update_hareruya_prices import fetch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "social_buylist.json"
CONFIG = ROOT / "social_sources.json"


def iso(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = parsedate_to_datetime(value)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_timeline(html):
    node = next(Document(html).root.find_all(lambda n: n.tag == "script" and n.attrs.get("id") == "__NEXT_DATA__"), None)
    if node is None:
        raise ValueError("public embedded timeline unavailable")
    data = json.loads("".join(c for c in node.children if isinstance(c, str)))
    timeline = data.get("props", {}).get("pageProps", {}).get("timeline")
    if not isinstance(timeline, dict) or not isinstance(timeline.get("entries"), list):
        raise ValueError("public timeline entries missing")
    return [e.get("content", {}).get("tweet", {}) for e in timeline["entries"] if e.get("type") == "tweet"]


def is_buylist_text(body):
    return bool(re.search(r"買取情報|買取表|強化.{0,6}買取|買取.{0,6}強化|買取価格|[\d,]+円.{0,12}買取|買取.{0,30}[\d,]+円|buylist|buying", body, re.I))


def normalize_post(tweet, account, keywords, at):
    user = tweet.get("user", {})
    if user.get("screen_name", "").lower() != account["handle"].lower():
        return None
    body = (tweet.get("note_tweet") or {}).get("text") or tweet.get("full_text") or tweet.get("text", "")
    if not any(k.lower() in body.lower() for k in keywords) or body.startswith("RT @") or not is_buylist_text(body):
        return None
    if any(k in body for k in ("ポケカ", "デュエマ", "ポケモンカード")) and "MTG" not in body.upper():
        return None
    post_id = str(tweet.get("id_str", ""))
    if not post_id.isdigit() or not tweet.get("created_at"):
        return None
    photos = tweet.get("photos") or (tweet.get("extended_entities") or tweet.get("entities") or {}).get("media", [])
    images = []
    for photo in photos:
        url = photo.get("media_url_https") or photo.get("url", "")
        if urlsplit(url).hostname == "pbs.twimg.com":
            images.append(url)
    return {
        "id": post_id, "account": account["handle"], "shop": account["label"],
        "url": f"https://x.com/{account['handle']}/status/{post_id}",
        "publishedAt": iso(tweet["created_at"]), "collectedAt": at,
        "text": body, "images": list(dict.fromkeys(images)),
        "priceStatus": "imageReviewNeeded" if images else "originalText",
        "source": "X public post", "quotes": [],
    }


def discover_accounts(config):
    known = {r["handle"].lower(): r for r in config["accounts"]}
    for page in config.get("shopPages", []):
        try:
            root = Document(fetch(page)).root
            title = next(root.find_all(lambda n: n.tag == "title"), None)
            for link in root.find_all(lambda n: n.tag == "a"):
                href = link.attrs.get("href", "")
                match = re.fullmatch(r"https://(?:twitter|x)\.com/(hareruya[A-Za-z0-9_]+)(?:\?.*)?", href)
                if match and match[1].lower() not in known:
                    known[match[1].lower()] = {"handle": match[1], "label": title.text().split("|")[0].strip() if title else match[1], "verifiedFrom": page}
        except Exception as error:
            print(f"Shop directory unavailable: {page}: {type(error).__name__}")
    config["accounts"] = list(known.values())
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def collect(urls=(), discover=False, timeline_file=None, account_handle=None):
    config = json.loads(CONFIG.read_text())
    if discover:
        discover_accounts(config)
    accounts = {a["handle"].lower(): a for a in config["accounts"]}
    previous = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {"items": []}
    items = {p["id"]: p for p in previous.get("items", []) if is_buylist_text(p.get("text", ""))}
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    statuses, failures, new_ids = [], [], set()

    def ingest(tweet, account):
        post = normalize_post(tweet, account, config["keywords"], at)
        if post:
            if post["id"] not in items:
                items[post["id"]] = post
                new_ids.add(post["id"])

    if timeline_file:
        account = accounts[account_handle.lower()]
        for tweet in parse_timeline(Path(timeline_file).read_text()):
            ingest(tweet, account)
        statuses.append({"account": account["handle"], "checkedAt": at, "status": "importedPublicCapture"})
    elif urls:
        for url in urls:
            parsed = urlsplit(url)
            match = re.fullmatch(r"/([A-Za-z0-9_]+)/status/(\d+)(?:/.*)?", parsed.path)
            if parsed.scheme != "https" or parsed.hostname not in {"x.com", "twitter.com", "www.x.com"} or not match or match[1].lower() not in accounts:
                raise ValueError("only configured official account post URLs may be imported")
            data = json.loads(fetch(f"https://cdn.syndication.twimg.com/tweet-result?id={match[2]}&lang=ja&token=1"))
            ingest(data, accounts[match[1].lower()])
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch, f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{a['handle']}"): a for a in accounts.values()}
            for future in as_completed(futures):
                account = futures[future]
                try:
                    tweets = parse_timeline(future.result())
                    for tweet in tweets:
                        ingest(tweet, account)
                    statuses.append({"account": account["handle"], "checkedAt": at, "status": "publicEmbedLimited", "visiblePosts": len(tweets)})
                except Exception as error:
                    failures.append({"account": account["handle"], "error": f"{type(error).__name__}: {error}"})
    values = sorted(items.values(), key=lambda p: p["publishedAt"], reverse=True)[:config["maxItems"]]
    payload = {"meta": {
        "lastCheckedAt": at, "lastNewPostAt": at if new_ids else previous.get("meta", {}).get("lastNewPostAt"),
        "newItems": len(new_ids), "items": len(values), "accounts": len(accounts),
        "latestPublishedAt": values[0]["publishedAt"] if values else None,
        "coverage": "publicEmbedLimited", "coverageNote": "公开嵌入页可能仅展示热门旧帖；不保证完整时间线。发布时间以原帖为准。",
        "sources": statuses, "failures": failures, "checkIntervalMinutes": 60,
    }, "items": values}
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUTPUT)
    print(json.dumps({"items": len(values), "new": len(new_ids), "accounts": len(accounts), "failures": failures}, ensure_ascii=False))
    return 0 if urls or statuses else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--timeline-file")
    parser.add_argument("--account")
    args = parser.parse_args()
    if args.timeline_file and not args.account:
        parser.error("--timeline-file requires --account")
    raise SystemExit(collect(args.url, args.discover, args.timeline_file, args.account))
