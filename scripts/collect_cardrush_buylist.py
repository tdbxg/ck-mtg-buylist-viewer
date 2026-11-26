#!/usr/bin/env python3
"""Collect Card Rush (カードラッシュ) MTG buy prices.

Fetches the public ``cardrush.media/mtg/buying_prices`` listing (a Next.js SSR
page) and extracts the embedded ``__NEXT_DATA__`` JSON, paginating through the
full list. The output is a raw, compact JSON snapshot that a separate matching
step aligns to Scryfall printings.

Polite scraping: serial requests, a small delay between pages, and retries.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://cardrush.media/mtg/buying_prices"
OUTPUT_RAW = ROOT / "cardrush_buylist_raw.json.gz"
CHECKPOINT = ROOT / "cardrush_buylist_raw.checkpoint.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
LIMIT = 300          # confirmed accepted by the endpoint
DELAY_SECONDS = 0.25 # politeness between pages
MAX_RETRIES = 3
CHECKPOINT_EVERY = 10

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_page(page: int) -> tuple[list[dict], int, str]:
    url = (
        f"{BASE_URL}?limit={LIMIT}&page={page}"
        f"&sort%5Bkey%5D=name&sort%5Border%5D=asc"
    )
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            html = fetch_html(url)
            match = NEXT_DATA_RE.search(html)
            if not match:
                raise RuntimeError("no __NEXT_DATA__ in response")
            data = json.loads(match.group(1))
            props = data["props"]["pageProps"]
            return props.get("buyingPrices", []), int(props.get("lastPage", 0)), str(props.get("updatedAt", ""))
        except Exception as exc:  # noqa: BLE001 - retry transient failures
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"page {page} failed after retries: {last_error}")


def main() -> int:
    rows, last_page, updated_at = fetch_page(1)
    print(f"lastPage={last_page} updatedAt={updated_at} firstRows={len(rows)}", flush=True)

    seen: dict[int, dict] = {}
    start_page = 1
    if CHECKPOINT.exists():
        ck = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        seen = {int(k): v for k, v in ck.get("seen", {}).items()}
        start_page = int(ck.get("next_page", 1))
        last_page = int(ck.get("last_page", last_page))
        updated_at = ck.get("updated_at", updated_at)
        print(f"resumed from checkpoint at page {start_page} ({len(seen)} rows so far)", flush=True)

    for page in range(start_page, last_page + 1):
        page_rows, _, page_updated = fetch_page(page)
        if page_updated:
            updated_at = page_updated
        for row in page_rows:
            rid = row.get("id")
            if rid is not None:
                seen[int(rid)] = row
        if page % CHECKPOINT_EVERY == 0 or page == last_page:
            CHECKPOINT.write_text(json.dumps(
                {"next_page": page + 1, "last_page": last_page, "updated_at": updated_at,
                 "seen": {str(k): v for k, v in seen.items()}},
                ensure_ascii=False,
            ), encoding="utf-8")
            print(f"  page {page}/{last_page}  unique={len(seen)}  (checkpointed)", flush=True)
        time.sleep(DELAY_SECONDS)

    payload = {
        "meta": {
            "source": BASE_URL,
            "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": updated_at,
            "items": len(seen),
            "limit": LIMIT,
        },
        "items": list(seen.values()),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = OUTPUT_RAW.with_suffix(".gz.tmp")
    tmp.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    tmp.replace(OUTPUT_RAW)
    CHECKPOINT.unlink(missing_ok=True)
    print(json.dumps({"output": str(OUTPUT_RAW.relative_to(ROOT)), "items": len(seen), "bytes": OUTPUT_RAW.stat().st_size}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
