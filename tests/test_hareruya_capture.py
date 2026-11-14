import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hareruya_capture import annotate, detail_prices, listing_rows, merge_listing
from refresh_hareruya import capture_detail


class CaptureTests(unittest.TestCase):
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
