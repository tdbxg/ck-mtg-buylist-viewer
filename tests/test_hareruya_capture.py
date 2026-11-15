import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hareruya_capture import annotate, detail_prices, detail_stocks, listing_rows, merge_listing
from refresh_hareruya import capture_detail
import probe_hareruya_priority as probe
import refresh_hareruya as refresh_module


class CaptureTests(unittest.TestCase):
    def test_scheduled_rotation_respects_existing_retail_access_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "prices.json"
            previous = {"meta":{"generatedAt":"2026-11-15T00:00:00Z", "versionValidation":{"retailBlockedUntil":"2099-01-01T00:00:00Z"}},
                        "items":[{"productId":"1", "language":"EN", "buy":{"EN":100}, "buyCapturedAt":"2026-11-15T00:00:00Z"}]}
            with patch.object(refresh_module.legacy, "load_previous", return_value=previous), patch.object(refresh_module.legacy,"OUTPUT",output), \
                 patch.object(refresh_module,"record_refresh"), patch.object(refresh_module,"capture_detail",return_value=previous["items"][0]) as request:
                refresh_module.refresh(1, 1, 1, False)
            self.assertFalse(request.call_args.args[2])

    def test_legacy_probe_keeps_official_identity_and_existing_sale_evidence(self):
        page = '''<li class="itemList"><a class="itemName" href="/ja/purchase/detail/123?lang=EN">【Foil】(011)《甲/Example Card》[SLD]</a>
        <p class="itemDetail__price">¥ 1,200</p></li>'''
        with tempfile.TemporaryDirectory() as tmp:
            output, state, targets = (Path(tmp) / name for name in ("prices.json", "state.json", "targets.json"))
            old = {"productId":"123", "language":"EN", "sale":{"EN":{"NM":1500}},
                   "saleStock":{"EN":{"NM":2}}, "saleCapturedAt":"2026-11-14T00:00:00Z", "saleCaptureError":"retained"}
            output.write_text(json.dumps({"items":[old]}))
            with patch.multiple(probe, OUTPUT=output, STATE=state, TARGETS=targets), \
                 patch.object(probe, "high_value_names", return_value=[{"key":"examplecard", "name":"Example Card", "cashUsd":10}]), \
                 patch.object(probe, "search", return_value=listing_rows(page)), patch.object(sys, "argv", ["probe", "--limit", "1"]):
                probe.main()
            row = json.loads(output.read_text())["items"][0]
            self.assertEqual(row.get("variation"), "【EN】【Foil】(011)《甲/Example Card》[SLD]")
            self.assertTrue(row.get("foil"))
            self.assertEqual(row.get("identityEvidence", {}).get("kind"), "officialListing")
            self.assertEqual(row.get("saleStock"), old["saleStock"])
            self.assertEqual(row.get("saleCapturedAt"), old["saleCapturedAt"])
            self.assertEqual(row.get("saleCaptureError"), "retained")

    def test_parenthesized_card_name_is_not_a_collector_number(self):
        page = '''<li class="itemList"><a class="itemName" href="/ja/purchase/detail/123?lang=EN">《甲/Example (2020)》[SLD]</a>
        <p class="itemDetail__price">¥ 100</p></li>'''
        self.assertEqual(listing_rows(page)[0]["collectorNumber"], "")

    def test_changed_product_identity_invalidates_old_retail_evidence(self):
        old = {"variation":"【EN】(001)《甲/Example》[SLD]", "retailVerified":True,
               "sale":{"EN":{"NM":1000}}, "saleStock":{"EN":{"NM":3}}, "saleCapturedAt":"2026-11-15T00:00:00Z"}
        incoming = {"productId":"1", "language":"EN", "variation":"【EN】【Foil】(001)《甲/Example》[SLD]",
                    "collectorNumber":"001", "identityEvidence":{"kind":"officialListing"}, "buyPrice":500}
        row = merge_listing(old, incoming, "2026-11-15T10:00:00Z")
        self.assertFalse(row["retailVerified"])
        self.assertEqual(row["sale"], old["sale"])
        self.assertEqual(row["saleCapturedAt"], old["saleCapturedAt"])

    def test_legacy_listing_refresh_also_preserves_print_and_stock_evidence(self):
        page = '''<li class="itemList"><a class="itemName" href="/ja/purchase/detail/123?lang=EN">【Foil】(011)《甲/Example Card》[SLD]</a>
        <p class="itemDetail__price">¥ 1,200</p></li>'''
        legacy = refresh_module.legacy
        with tempfile.TemporaryDirectory() as tmp:
            output, targets = Path(tmp) / "prices.json", Path(tmp) / "targets.json"
            old = {"productId":"123", "language":"EN", "saleStock":{"EN":{"NM":2}}}
            with patch.object(legacy, "load_previous", return_value={"items":[old]}), patch.object(legacy,"OUTPUT",output), \
                 patch.object(legacy,"TARGETS",targets), patch.object(legacy,"purchase_listing_targets_all",return_value=(listing_rows(page),1)), \
                 patch.object(legacy,"fetch",return_value='{"rates":{"CNY":0.04}}'):
                legacy.refresh_listing_only()
            row = json.loads(output.read_text())["items"][0]
            self.assertTrue(row.get("foil"))
            self.assertIn("【EN】【Foil】", row.get("variation", ""))
            self.assertEqual(row.get("saleStock"), old["saleStock"])

    def test_detail_refresh_updates_exact_title_and_finish_not_only_price(self):
        page = '''<h2 class="goods_name_">【Foil】《甲/Example Card》[10ED] 白R</h2>
        <div id="priceTable-EN"><div class="row"><strong>NM</strong><div>￥700</div></div></div>'''
        with patch("refresh_hareruya.legacy.fetch", return_value=page):
            row = capture_detail({"productId":"1", "language":"EN", "name":"Example Card"}, "2026-11-15T12:00:00Z")
        self.assertIn("【EN】【Foil】", row["variation"])
        self.assertEqual(row["set"], "10ED")
        self.assertEqual(row["collectorNumber"], "")
        self.assertTrue(row["foil"])
        self.assertEqual(row["identityEvidence"]["title"], "【Foil】《甲/Example Card》[10ED] 白R")

    def test_retail_stock_is_condition_and_language_specific(self):
        page = '''<div id="priceTable-JP"><div class="row"><div>NM</div><div>￥100</div><div class="col-xs-2">9</div></div></div>
        <div id="priceTable-EN"><div class="row"><div>NM</div><div>￥200</div><div class="col-xs-2">0</div></div>
        <div class="row"><div>SP</div><div>￥150</div><div class="col-xs-2">3</div></div></div>
        <div class="recommendation">NM 在庫 100</div>'''
        self.assertEqual(detail_stocks(page, "EN"), {"NM":0,"SP":3})
        self.assertEqual(detail_stocks(page, "JP"), {"NM":9})

    def test_price_alone_does_not_imply_stock_and_purchase_select_is_not_stock(self):
        self.assertEqual(detail_stocks('<div id="priceTable-EN"><div class="row"><strong>NM</strong><div>￥700</div></div></div>', "EN"), {})
        page = '<div id="priceTable-EN"><div class="row"><div>NM</div><div>￥700</div><div><select><option value="20">20</option></select></div></div></div>'
        self.assertEqual(detail_stocks(page, "EN"), {})

    def test_language_and_recommendations_are_isolated(self):
        page = '''<div id="priceTable-JP"><div class="row"><strong>NM</strong><div>￥600</div></div></div>
        <div id="priceTable-EN"><div class="row"><strong>NM</strong><div>￥700</div></div></div>
        <div class="itemDetail__stock">【買取価格】</div><div class="itemDetail__price">¥600</div>'''
        self.assertEqual(detail_prices(page, "EN"), {"NM": 700})
        self.assertEqual(detail_prices(page, "JP"), {"NM": 600})

    def test_missing_language_does_not_match_other_products(self):
        self.assertEqual(detail_prices('<div class="itemDetail__price">¥9000</div>', "JP"), {})

    def test_attribute_order_double_faces_and_foil(self):
        page = '''<li class="itemList"><a class="itemName" href="/ja/purchase/detail/123?lang=EN&amp;x=1">【Foil】(011)《甲/Front》//《乙/Back》[SLD]</a>
        <img data-original="https://files.hareruyamtg.com/123.jpg?d=100"><p class="itemDetail__price">¥ 1,200</p></li>'''
        row = listing_rows(page)[0]
        self.assertEqual((row["productId"], row["language"], row["buyPrice"]), ("123", "EN", 1200))
        self.assertEqual(row["name"], "Front // Back")
        self.assertTrue(row["foil"])

    def test_old_records_stay_stale_after_another_row_refreshes(self):
        old = {"productId": "1", "language": "JP", "capturedAt": "2026-08-01T00:00:00Z", "buy": {"JP": 500}}
        fresh = merge_listing({}, {"productId": "2", "language": "EN", "buyPrice": 700}, "2026-11-14T00:00:00Z")
        payload = annotate({"items": [old, fresh]}, "2026-11-14T00:00:00Z")
        self.assertTrue(old["stale"])
        self.assertEqual(payload["meta"]["freshItems"], 1)

    def test_detail_failure_cannot_return_a_new_price(self):
        with patch("refresh_hareruya.legacy.fetch", return_value='<div class="itemDetail__price">¥9000</div>'):
            with self.assertRaises(ValueError):
                capture_detail({"productId": "1", "language": "EN", "buy": {"EN": 700}}, "2026-11-14T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
