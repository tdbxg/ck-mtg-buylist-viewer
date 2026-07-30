#!/usr/bin/env python3
"""Refresh configured Hareruya MTG product and buylist snapshots.

Only IDs in hareruya_targets.json are requested. A target must represent an
already-confirmed Hareruya print, so name-only matches are never invented.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "hareruya_targets.json"
OUTPUT = ROOT / "hareruya_prices.json"
FX_URL = "https://open.er-api.com/v6/latest/JPY"
BASE = "https://www.hareruyamtg.com/ja"
CONDITIONS = ("NM", "SP", "MP", "HP")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ck-mtg-price-radar/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def find_title(html: str) -> tuple[str, str]:
    match = re.search(r"<title>\s*(?:買取：)?\s*(.*?)\s*\|", html, re.S)
    raw = text(match.group(1)) if match else ""
    if "/" in raw:
        ja, en = raw.split("/", 1)
        return ja.strip("《》 "), en.split("》", 1)[0].strip("《》 ")
    return raw.strip("《》 "), raw.strip("《》 ")


def find_image(html: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if not re.search(r"(?:property|name)=[\"']og:image[\"']", tag, re.I):
            continue
        match = re.search(r"content=[\"']([^\"']+)[\"']", tag, re.I)
        if match:
            return unescape(match.group(1))
    return ""


def table_fragment(html: str, language: str) -> str:
    marker = f'id="priceTable-{language}"'
    start = html.find(marker)
    if start < 0:
        return ""
    other = f'id="priceTable-{("EN" if language == "JP" else "JP")}"'
    end = html.find(other, start + len(marker))
    return html[start:end if end >= 0 else start + 20000]


def sale_prices(html: str, language: str) -> dict[str, int]:
    fragment = table_fragment(html, language)
    prices: dict[str, int] = {}
    for condition in CONDITIONS:
        match = re.search(
            rf">\s*{condition}\s*<(?:(?!>\s*(?:NM|SP|MP|HP)\s*<).)*?data-price=\"(\d+)\"",
            fragment,
            re.S,
        )
        if match:
            prices[condition] = int(match.group(1))
    return prices


def buy_price(html: str) -> int | None:
    match = re.search(r'itemDetail__stock[^>]*>\s*【買取価格】.*?itemDetail__price[^>]*>\s*[￥¥]\s*([\d,]+)', html, re.S)
    return int(match.group(1).replace(",", "")) if match else None


def load_previous() -> dict:
    if not OUTPUT.exists():
        return {"items": []}
    try:
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": []}


def main() -> int:
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    previous = {str(row.get("productId")): row for row in load_previous().get("items", [])}
    items = []
    failures = []
    for target in targets:
        product_id = str(target["productId"])
        sale_url = f"{BASE}/products/detail/{product_id}"
        buy_url = f"{BASE}/purchase/detail/{product_id}"
        try:
            sale_html = fetch(sale_url)
            buy_html = fetch(f"{buy_url}?lang={target.get('language', 'JP')}")
            name_ja, name_en = find_title(sale_html)
            language = target.get("language", "JP")
            item = {
                "productId": product_id,
                "name": name_en or name_ja,
                "nameJa": name_ja,
                "set": target.get("set", ""),
                "collectorNumber": str(target.get("collectorNumber", "")),
                "language": language,
                "image": target.get("image") or find_image(sale_html),
                "sale": {language: sale_prices(sale_html, language)},
                "buy": {language: buy_price(buy_html)},
                "saleUrl": sale_url,
                "buyUrl": buy_url,
                "capturedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
            if not item["sale"][language] or item["buy"][language] is None:
                raise ValueError("missing sale or buy price in public page")
            items.append(item)
        except Exception as error:  # Preserve a verified previous snapshot instead of publishing blanks.
            old = previous.get(product_id)
            if old:
                items.append(old)
            failures.append(f"{product_id}: {error}")

    try:
        jpy_cny = float(json.loads(fetch(FX_URL))["rates"]["CNY"])
    except Exception as error:
        jpy_cny = load_previous().get("meta", {}).get("jpyCny")
        failures.append(f"FX: {error}")

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "items": len(items),
            "jpyCny": jpy_cny,
            "source": "Hareruya public product and purchase pages",
            "failures": failures,
        },
        "items": items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False))
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
