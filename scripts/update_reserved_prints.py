#!/usr/bin/env python3
"""Download Scryfall's exact Reserved List print IDs for the static viewer."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "ck-mtg-buylist-viewer-github-actions/1.0", "Accept": "application/json"}


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except Exception:
        raw = subprocess.check_output(
            ["curl", "-fsSL", "--max-time", "90", "-A", HEADERS["User-Agent"], url],
            stderr=subprocess.DEVNULL,
            timeout=100,
        )
        return json.loads(raw)


def main() -> int:
    url = "https://api.scryfall.com/cards/search?" + urllib.parse.urlencode({"q": "is:reserved", "unique": "prints"})
    print_ids: dict[str, bool] = {}
    while url:
        payload = fetch(url)
        for card in payload.get("data", []):
            if card.get("id") and card.get("reserved"):
                print_ids[card["id"]] = True
        url = payload.get("next_page") if payload.get("has_more") else ""

    output = {
        "meta": {
            "source": "Scryfall is:reserved unique:prints",
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(print_ids),
        },
        "printIds": print_ids,
    }
    (ROOT / "reserved_prints.json").write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(print_ids)} Reserved List print IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
