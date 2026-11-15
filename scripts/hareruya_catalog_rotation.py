"""Resume public English purchase-list pages across the site's series filters."""

import re
import time
from datetime import timedelta
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit

from hareruya_capture import BASE, Document, listing_rows, timestamp
from update_hareruya_prices import fetch


def discover_partitions(html):
    select = next(Document(html).root.find_all(lambda n: n.tag == "select" and n.attrs.get("name") == "cardset"), None)
    if select is None:
        raise ValueError("official series search form missing")
    values = [{"id":n.attrs["value"], "name":n.text(), "nextPage":1}
              for n in select.find_all(lambda n: n.tag == "option" and str(n.attrs.get("value") or "").isdigit())]
    if len(values) < 100:
        raise ValueError("series search form unexpectedly small")
    # Cover the user's SL inventory first, then follow the official series order.
    values.sort(key=lambda p: ("secret lair" not in p["name"].lower(),))
    return {"version":2, "partitions":values, "cursor":0}


def partition_url(partition, page):
    params = {"cardset":partition["id"], "language[]":"2", "purchaseFlg":"1", "sort":"price", "order":"DESC", "page":str(page)}
    if "foil" in partition:
        params["foilFlg[]"] = str(partition["foil"])
    return f"{BASE}/purchase/search?{urlencode(params)}"


def page_info(html, series, foil=None):
    root = Document(html).root
    if any(root.find_all(lambda n: n.has_class("search_results_exceeded"))):
        raise ValueError("too many results; refine official series/foil filters")
    counter = next(root.find_all(lambda n: n.has_class("count_number")), None)
    total = int(counter.text().replace(",", "")) if counter and re.fullmatch(r"[\d,]+", counter.text()) else None
    pages = [1]
    for link in root.find_all(lambda n: n.tag == "a" and "page=" in n.attrs.get("href", "")):
        url = urlsplit(link.attrs["href"])
        q = parse_qs(url.query)
        if url.hostname not in (None, "www.hareruyamtg.com") or url.path != "/ja/purchase/search":
            continue
        languages = [v for key, values in q.items() if re.fullmatch(r"language\[\d*\]", key) for v in values]
        if q.get("cardset") != [str(series)] or languages != ["2"]:
            continue
        foils = [v for key, values in q.items() if re.fullmatch(r"foilFlg\[\d*\]", key) for v in values]
        if foil is not None and foils != [str(foil)]:
            continue
        if q.get("page", [""])[0].isdigit():
            pages.append(int(q["page"][0]))
    return {"lastPage":max(pages), "total":total}


def capture(state, page_limit, at, checkpoint=None):
    report = {"pagesAttempted":0, "pagesCompleted":0, "rows":0, "failures":[], "at":at}
    if state.get("blockedUntil") and timestamp(state["blockedUntil"]) > timestamp(at):
        report["blockedUntil"] = state["blockedUntil"]
        return [], state, report
    state.pop("blockedUntil", None)
    rows, visited = {}, set()
    while report["pagesAttempted"] < page_limit and state.get("partitions"):
        cursor = state.get("cursor", 0) % len(state["partitions"])
        part = state["partitions"][cursor]
        page = part.get("nextPage", 1)
        token = (part["id"], part.get("foil"), page)
        if token in visited:
            break
        visited.add(token)
        url = partition_url(part, page)
        report["pagesAttempted"] += 1
        time.sleep(0.8)
        try:
            html = fetch(url)
            info = page_info(html, part["id"], part.get("foil"))
            found = listing_rows(html)
            if not found and info["total"] != 0:
                raise ValueError("no verified purchase rows or explicit zero-result count")
            if page == 1 and info["total"] and info["total"] > len(found) and info["lastPage"] == 1:
                raise ValueError("result count requires pagination but verified next-page links are missing")
            if any(r["language"] != "EN" for r in found):
                raise ValueError("English filter returned another language")
            for row in found:
                row["identityEvidence"]["listingUrl"] = url
                rows[(row["productId"], row["language"])] = row
            part.update(lastPage=info["lastPage"], total=info["total"], lastSuccessfulAt=at)
            part["nextPage"] = page + 1
            if page >= info["lastPage"]:
                part.update(nextPage=1, completedAt=at, completedPasses=part.get("completedPasses", 0) + 1)
                state["cursor"] = (cursor + 1) % len(state["partitions"])
            report["pagesCompleted"] += 1
            report["rows"] = len(rows)
            if checkpoint and report["pagesCompleted"] % 10 == 0:
                checkpoint(list(rows.values()), state, report)
            if report["pagesCompleted"] % 10 == 0:
                print(f"English catalog: {report['pagesCompleted']}/{page_limit} pages, {len(rows)} verified rows", flush=True)
        except Exception as error:
            report["failures"].append(f"{url}: {type(error).__name__}: {error}")
            part["lastAttemptAt"] = at
            if isinstance(error, HTTPError) and error.code in (403, 429):
                state["blockedUntil"] = (timestamp(at) + timedelta(hours=6)).isoformat(timespec="seconds")
                report["blockedUntil"] = state["blockedUntil"]
                break
            if isinstance(error, ValueError) and "refine official" in str(error) and "foil" not in part:
                state["partitions"][cursor:cursor + 1] = [
                    {"id":part["id"], "name":part["name"], "foil":f, "nextPage":1} for f in (0, 1)]
            else:
                # Keep the failed page for the next pass; do not starve other series.
                state["cursor"] = (cursor + 1) % len(state["partitions"])
            if checkpoint:
                checkpoint(list(rows.values()), state, report)
    state["lastRun"] = report
    if checkpoint:
        checkpoint(list(rows.values()), state, report)
    return list(rows.values()), state, report
