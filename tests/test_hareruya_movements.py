import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hareruya_movements import build_feed, epoch, observe

AT = "2026-11-14T12:00:00+00:00"


def row(price, captured, language="EN", product="1"):
    return {"productId": product, "language": language, "source": "verifiedDetail", "name": "Same Name",
            "buy": {language: price}, "buyCapturedAt": captured}


class MovementTests(unittest.TestCase):
    def test_old_change_does_not_reappear_in_one_hour(self):
        history = {"records": {"1|EN": {"buy": [[epoch("2026-11-14T08:00:00Z"), 600], [epoch("2026-11-14T10:00:00Z"), 650], [epoch("2026-11-14T11:30:00Z"), 650], [epoch(AT), 650]]}}}
        feed = build_feed(history, {"items": [row(650, AT)]}, AT)
        self.assertEqual(feed["periods"]["hour"]["buy"]["items"], [])
        self.assertEqual(feed["periods"]["day"]["buy"]["items"][0]["deltaJpy"], 50)

    def test_languages_and_product_variants_are_not_merged(self):
        h = {"records": {}}
        observe(h, {"items": [row(100, "2026-11-14T11:00:00Z"), row(1000, "2026-11-14T11:00:00Z", "JP")]}, AT)
        current = {"items": [row(150, AT), row(1000, AT, "JP"), row(500, AT, product="2")]}
        observe(h, current, AT)
        changes = build_feed(h, current, AT)["periods"]["hour"]["buy"]["items"]
        self.assertEqual([(r["key"], r["deltaJpy"]) for r in changes], [("1|EN", 50)])

    def test_stop_buying_is_not_a_100_percent_price_drop(self):
        h = {"records": {}}
        observe(h, {"items": [row(100, "2026-11-14T11:00:00Z")]}, AT)
        current = {"items": [row(0, AT)]}
        observe(h, current, AT)
        self.assertEqual(build_feed(h, current, AT)["periods"]["hour"]["buy"]["items"], [])

    def test_error_and_retained_quote_do_not_become_new_observations(self):
        h = {"records": {}}
        original = row(100, "2026-11-14T11:00:00Z")
        observe(h, {"items": [original]}, AT)
        observe(h, {"items": [original]}, AT)
        failed = {**row(200, AT), "captureError": "timeout"}
        observe(h, {"items": [failed]}, AT)
        self.assertEqual(len(h["records"]["1|EN"]["buy"]), 1)

    def test_sale_uses_its_own_capture_time(self):
        h = {"records": {}}
        a = {**row(100, "2026-11-14T11:00:00Z"), "sale": {"EN": {"NM": 900}}}
        observe(h, {"items": [a]}, AT)
        self.assertNotIn("sale", h["records"]["1|EN"])
        a["saleCapturedAt"] = "2026-11-14T11:00:00Z"
        observe(h, {"items": [a]}, AT)
        b = {**row(100, AT), "sale": {"EN": {"NM": 800}}, "saleCapturedAt": AT}
        observe(h, {"items": [b]}, AT)
        changes = build_feed(h, {"items": [b]}, AT)["periods"]["hour"]["sale"]["items"]
        self.assertEqual(changes[0]["deltaJpy"], -100)

    def test_week_does_not_include_quotes_before_its_window(self):
        h = {"records": {}}
        observe(h, {"items": [row(1, "2026-11-01T11:00:00Z")]}, AT)
        current = {"items": [row(100, AT)]}
        observe(h, current, AT)
        self.assertEqual(build_feed(h, current, AT)["periods"]["week"]["buy"]["items"], [])

    def test_stale_quotes_are_not_current_rankings(self):
        h = {"records": {}}
        observe(h, {"items": [row(100, "2026-11-12T10:00:00Z")]}, AT)
        old = {"items": [row(200, "2026-11-12T11:00:00Z")]}
        observe(h, old, AT)
        self.assertEqual(build_feed(h, old, AT)["periods"]["week"]["buy"]["items"], [])
