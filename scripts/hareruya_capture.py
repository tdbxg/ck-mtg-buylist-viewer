"""Structural parsing and freshness rules for exact Hareruya products."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

BASE = "https://www.hareruyamtg.com/ja"
CONDITIONS = ("NM", "SP", "MP", "HP")


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find_all(self, predicate):
        for child in self.children:
            if isinstance(child, Node):
                if predicate(child):
                    yield child
                yield from child.find_all(predicate)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def amount(value):
    match = re.search(r"[\u00a5\uffe5]\s*([\d,]+)", value)
    return int(match[1].replace(",", "")) if match else None


def listing_rows(html):
    rows = []
    root = Document(html).root
    for block in root.find_all(lambda n: n.tag == "li" and n.has_class("itemList")):
        link = next(block.find_all(lambda n: n.tag == "a" and n.has_class("itemName")), None)
        price = next(block.find_all(lambda n: n.has_class("itemDetail__price")), None)
        if link is None or price is None:
            continue
        url = urlsplit(urljoin(BASE + "/", link.attrs.get("href", "")))
        identity = re.fullmatch(r"/ja/purchase/detail/(\d+)", url.path)
        language = parse_qs(url.query).get("lang", [""])[0]
        title = link.text()
        if url.hostname != "www.hareruyamtg.com" or not identity or language not in {"EN", "JP"}:
            continue
        if "まとめて買取" in title or amount(price.text()) is None:
            continue
        pairs = re.findall(r"\u300a([^/\u300b]+)/([^\u300b]+)\u300b", title)
        name_ja = " // ".join(p[0].strip() for p in pairs) or title
        name_en = " // ".join(p[1].strip() for p in pairs) or title
        set_match = re.search(r"\[([^\]]+)\]", title)
        number = re.search(r"\((\d+[a-zA-Z★*\-]*)\)", title)
        image = next(block.find_all(lambda n: n.tag == "img"), None)
        image_url = (image.attrs.get("data-original") or image.attrs.get("src") or "") if image else ""
        if image_url and not image_url.startswith("https://files.hareruyamtg.com/"):
            image_url = ""
        rows.append({
            "productId": identity[1], "language": language, "name": name_en, "nameJa": name_ja,
            "set": set_match[1] if set_match else "", "collectorNumber": number[1] if number else "",
            "variation": title if f"【{language}】" in title else f"【{language}】{title}",
            "foil": any("foil" in t.lower() for t in re.findall(r"【([^】]+)】", re.sub(r"《[^》]+》", "", title))),
            "image": image_url.split("?", 1)[0], "buyPrice": amount(price.text()),
            "identityEvidence": {"title": title, "language": language, "kind": "officialListing", "url": url.geturl()},
        })
    return rows


def detail_prices(html, language, purchase=False):
    root = Document(html).root
    table = next(root.find_all(lambda n: n.attrs.get("id") == f"priceTable-{language}"), None)
    if table is None:
        return {}
    prices = {}
    for row in table.find_all(lambda n: n.has_class("row") or n.tag == "tr"):
        tokens = row.text().split()
        condition = next((c for c in CONDITIONS if c in tokens), None)
        if not condition:
            continue
        price = amount(row.text())
        if price is None:
            data_price = next(row.find_all(lambda n: str(n.attrs.get("data-price", "")).isdigit()), None)
            price = int(data_price.attrs["data-price"]) if data_price else None
        if price is not None:
            prices[condition] = price
    return prices


def detail_metadata(html, language):
    root = Document(html).root
    title_node = next(root.find_all(lambda n: n.tag == "h2" and n.has_class("goods_name_")), None)
    table = next(root.find_all(lambda n: n.attrs.get("id") == f"priceTable-{language}"), None)
    if title_node is None or table is None:
        raise ValueError("exact product title or language table missing")
    title = title_node.text()
    pairs = re.findall(r"《([^/》]+)/([^》]+)》", title)
    series = re.search(r"\[([^\]]+)\]", title)
    collector = re.search(r"\((\d+[a-zA-Z★*\-]*)\)", re.sub(r"《[^》]+》", "", title))
    if not pairs or not series:
        raise ValueError("product name or edition missing from official title")
    if any(tag in title for tag in ("【EN】", "【JP】")) and f"【{language}】" not in title:
        raise ValueError("product title language conflicts with requested table")
    return {"name": " // ".join(p[1].strip() for p in pairs), "nameJa": " // ".join(p[0].strip() for p in pairs),
            "set": series[1], "collectorNumber": collector[1] if collector else "",
            "variation": title if f"【{language}】" in title else f"【{language}】{title}",
            "foil": any("foil" in tag.lower() for tag in re.findall(r"【([^】]+)】", re.sub(r"《[^》]+》", "", title))),
            "identityEvidence": {"title": title, "language": language, "kind": "officialDetail"}}


def detail_stocks(html, language):
    table = next(Document(html).root.find_all(lambda n: n.attrs.get("id") == f"priceTable-{language}"), None)
    if table is None:
        return {}
    result = {}
    for row in table.find_all(lambda n: n.has_class("row") or n.tag == "tr"):
        cells = [n for n in row.children if isinstance(n, Node)]
        if len(cells) < 3:
            continue
        condition = next((c for c in CONDITIONS if c in cells[0].text().split()), None)
        if not condition or amount(cells[1].text()) is None:
            continue
        stock_cell = cells[2]
        if any(stock_cell.find_all(lambda n: n.tag in {"select", "input"})):
            continue
        if re.fullmatch(r"[\d,]+", stock_cell.text()):
            result[condition] = int(stock_cell.text().replace(",", ""))
    return result


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def merge_listing(old, row, at, source="publicListing"):
    result = dict(old)
    result.update({k: v for k, v in row.items() if k != "buyPrice" and v not in (None, "")})
    lang = row["language"]
    result.update({
        "buy": {lang: row["buyPrice"]}, "sale": old.get("sale", {}),
        "buyUrl": f"{BASE}/purchase/detail/{row['productId']}?lang={lang}",
        "saleUrl": f"{BASE}/products/detail/{row['productId']}?lang={lang}",
        "capturedAt": at, "buyCapturedAt": at, "lastAttemptAt": at,
        "buyStatus": "available" if row["buyPrice"] > 0 else "unavailable",
        "captureError": "", "source": source,
    })
    return result


def annotate(payload, at):
    now = timestamp(at)
    for row in payload.get("items", []):
        captured = row.get("buyCapturedAt") or row.get("capturedAt")
        age = max(0, (now - timestamp(captured)).total_seconds())
        row["stale"] = age > 86400
        row.setdefault("buyCapturedAt", captured)
    meta = payload.setdefault("meta", {})
    rows = payload.get("items", [])
    meta.update({
        "items": len(rows), "images": sum(bool(r.get("image")) for r in rows),
        "freshItems": sum(not r["stale"] for r in rows), "staleItems": sum(r["stale"] for r in rows),
        "errorItems": sum(bool(r.get("captureError")) for r in rows),
        "verifiedRetailItems": sum(bool(r.get("retailVerified")) for r in rows),
        "staleAfterHours": 24,
    })
    return payload
