#!/usr/bin/env python3
"""Archive verified public Hareruya X posts without inferring image prices."""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from hareruya_capture import Document
from update_hareruya_prices import fetch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "social_buylist.json"
CONFIG = ROOT / "social_sources.json"
ARCHIVE = ROOT / "social_archive.json"


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


def search_ids(html, handle):
    node = next(Document(html).root.find_all(lambda n: n.tag == "script" and n.attrs.get("id") == "__NEXT_DATA__"), None)
    if node is None:
        raise ValueError("public search result unavailable")
    data = json.loads("".join(c for c in node.children if isinstance(c, str)))
    page = data.get("props", {}).get("pageProps", {}).get("pageData", {})
    error = page.get("searchError", {}).get("errorType")
    if error not in (None, "", "zeromatch"):
        raise ValueError(f"public search error: {error}")
    if "timeline" not in page and error != "zeromatch":
        raise ValueError("public search timeline missing")
    found = []
    for entry in page.get("timeline", {}).get("entry", []):
        url = urlsplit(entry.get("url", ""))
        match = re.fullmatch(r"/([A-Za-z0-9_]+)/status/(\d+)", url.path)
        if match and url.hostname == "x.com" and match[1].lower() == handle.lower() and entry.get("screenName", "").lower() == handle.lower():
            found.append(match[2])
    return list(dict.fromkeys(found))


def recent_ids(account):
    query = urlencode({"p": f"id:{account['handle']} 買取", "ei": "UTF-8"})
    return search_ids(fetch(f"https://search.yahoo.co.jp/realtime/search?{query}"), account["handle"])


def official_post(post_id):
    tweet = json.loads(fetch(f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&lang=ja&token=1"))
    if str(tweet.get("id_str")) != post_id:
        raise ValueError("official post identity mismatch or unavailable")
    return tweet


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
    if config.get("scope") == "headOffice":
        return
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
    retired = [p for p in previous.get("items", []) if p.get("account", "").lower() not in accounts]
    if retired:
        archive = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {"items": []}
        archived = {p["id"]: p for p in [*archive.get("items", []), *retired]}
        ARCHIVE.write_text(json.dumps({"items": sorted(archived.values(), key=lambda p: p["publishedAt"], reverse=True)}, ensure_ascii=False, indent=2) + "\n")
    items = {p["id"]: p for p in previous.get("items", []) if p.get("account", "").lower() in accounts and is_buylist_text(p.get("text", ""))}
    ignored = set(previous.get("ignoredIds", []))
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    statuses, failures, new_ids = [], [], set()

    def ingest(tweet, account):
        post = normalize_post(tweet, account, config["keywords"], at)
        if post:
            if post["id"] not in items:
                items[post["id"]] = post
                new_ids.add(post["id"])
        elif str(tweet.get("id_str", "")).isdigit():
            ignored.add(str(tweet["id_str"]))

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
            data = official_post(match[2])
            ingest(data, accounts[match[1].lower()])
    else:
        candidates = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(recent_ids, a): a for a in accounts.values()}
            for future in as_completed(futures):
                account = futures[future]
                try:
                    ids = future.result()
                    candidates.extend((post_id, account) for post_id in ids if post_id not in items and post_id not in ignored)
                    statuses.append({"account": account["handle"], "checkedAt": at, "status": "publicSearchIndex", "visiblePosts": len(ids)})
                except Exception as error:
                    failures.append({"account": account["handle"], "error": f"{type(error).__name__}: {error}"})
        # Bound requests per run and stop on an upstream rate limit.
        candidates = sorted({post_id: account for post_id, account in candidates}.items(), key=lambda pair: int(pair[0]), reverse=True)
        for post_id, account in candidates[:40]:
            try:
                ingest(official_post(post_id), account)
            except Exception as error:
                failures.append({"account": account["handle"], "postId": post_id, "error": f"{type(error).__name__}: {error}"})
                if getattr(error, "code", None) == 429:
                    break
    values = sorted(items.values(), key=lambda p: p["publishedAt"], reverse=True)[:config["maxItems"]]
    for post in values:
        account = accounts.get(post["account"].lower())
        if account:
            post["shop"] = account["label"]
    payload = {"meta": {
        "lastCheckedAt": at, "lastNewPostAt": at if new_ids else previous.get("meta", {}).get("lastNewPostAt"),
        "lastSuccessfulAt": at if not failures else previous.get("meta", {}).get("lastSuccessfulAt"),
        "status": "partial" if failures else "ok",
        "newItems": len(new_ids), "items": len(values), "accounts": len(accounts),
        "latestPublishedAt": values[0]["publishedAt"] if values else None,
        "coverage": "publicIndexAndOfficialPosts", "coverageNote": "公开实时索引发现链接，X 原帖核验内容与时间；索引可能延迟，不保证完整时间线。图片报价须按版本复核。",
        "sources": statuses, "failures": failures, "checkIntervalMinutes": 60,
    }, "items": values, "ignoredIds": sorted(ignored, key=int)[-2000:]}
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
