import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_hareruya_opportunities import build_feed, hareruya_identity

AT = "2026-11-15T10:00:00+00:00"
SID = "11111111-1111-4111-8111-111111111111"


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.h = {"meta": {"generatedAt": AT}, "items": [{
            "productId": "10", "language": "EN", "name": "Example Card", "nameJa": "Example",
            "set": "MH2", "collectorNumber": "001", "variation": "【EN】(001)《Example/Example Card》[MH2]",
            "foil": False, "buy": {"EN": 1000}, "buyCapturedAt": AT, "captureError": "",
        }]}
        self.ck = {"meta": {"capturedAt": AT}, "cards": [{
            "sku": "MH2-1", "scryfallId": SID, "scryfallSet": "mh2", "collectorNumber": "1", "foil": False,
            "name": "Example Card", "ckName": "Example Card", "ckUrl": "https://www.cardkingdom.com/mtg/example",
            "edition": "Modern Horizons 2", "variation": "", "conditions": {"nm_price": "5.00", "nm_qty": 2},
            "cashUsd": 900, "retailUsd": 999, "qtyRetail": 9,
        }]}
        self.fx = {"sourceAt": AT, "base_code": "USD", "rates": {"JPY": 100, "CNY": 7}}
        self.ids = {SID: {"id": SID, "lang": "en", "name": "Example Card", "set": "mh2", "collector_number": "1",
                          "finishes": ["nonfoil", "foil"], "promo_types": None, "card_faces": None,
                          "image_uris": {"normal": "https://cards.scryfall.io/example.jpg"}}}

    def feed(self, previous=None, at=AT):
        return build_feed(self.h, self.ck, self.fx, self.ids, previous or {}, at)

    def test_uses_nm_retail_not_cash_buy_or_total_retail(self):
        row = self.feed()["items"][0]
        self.assertEqual(row["ckRetailUsd"], 5)
        self.assertEqual(row["ckNmQty"], 2)
        self.assertEqual(row["spreadJpy"], 500)
        self.assertEqual(row["condition"], "NM")

    def test_equal_or_higher_cost_is_removed(self):
        for price in ("10.00", "10.01", "11.00"):
            with self.subTest(price=price):
                self.ck["cards"][0]["conditions"]["nm_price"] = price
                feed = self.feed()
                self.assertEqual(feed["items"], [])
                self.assertEqual(feed["meta"]["excluded"]["threshold"], 1)

    def test_comparison_is_not_rounded_before_threshold(self):
        self.fx["rates"]["JPY"] = "199.999999"
        self.assertGreater(self.feed()["items"][0]["spreadJpy"], 0)
        self.fx["rates"]["JPY"] = "200"
        self.assertEqual(self.feed()["items"], [])

    def test_other_condition_stock_is_not_nm_stock(self):
        self.ck["cards"][0]["conditions"]["nm_qty"] = 0
        self.assertEqual(self.feed()["meta"]["excluded"]["nmUnavailable"], 1)

    def test_missing_nm_quote_is_not_replaced_with_generic_price(self):
        self.ck["cards"][0]["conditions"] = {}
        self.assertEqual(self.feed()["items"], [])

    def test_japanese_rows_and_foreign_ck_prints_are_excluded(self):
        self.h["items"][0]["language"] = "JP"
        self.assertEqual(self.feed()["items"], [])
        self.h["items"][0]["language"] = "EN"
        self.ids[SID]["lang"] = "ja"
        self.assertEqual(self.feed()["meta"]["excluded"]["identityMismatch"], 1)

    def test_exact_set_number_and_finish_are_required(self):
        for field, value in (("scryfallSet", "mh1"), ("collectorNumber", "2"), ("foil", True)):
            with self.subTest(field=field):
                old = self.ck["cards"][0][field]
                self.ck["cards"][0][field] = value
                self.assertEqual(self.feed()["items"], [])
                self.ck["cards"][0][field] = old

    def test_serialized_foil_is_not_regular_foil(self):
        self.h["items"][0]["variation"] = "【EN】【ダブルレインボウ・Foil】(001)《Example/Example Card》(シリアル入り)[MH2]"
        self.assertEqual(self.feed()["meta"]["excluded"]["specialFinish"], 1)

    def test_card_named_foil_is_not_automatically_a_foil(self):
        row = self.h["items"][0]
        row["variation"] = "【EN】(001)《Example/Foil》[MH2]"
        row["name"] = "Foil"
        self.assertEqual(hareruya_identity(row)[0], ("mh2", "1", "nonfoil"))

    def test_explicit_collector_does_not_override_a_conflicting_title(self):
        self.h["items"][0]["variation"] = "【EN】(001)《甲/Unrelated Card》[MH2]"
        self.assertEqual(self.feed()["items"], [])
        self.h["items"][0]["variation"] = "【EN】【JP】(001)《甲/Example Card》[MH2]"
        self.assertEqual(self.feed()["items"], [])

    def test_prerelease_stamp_with_same_base_number_is_not_a_regular_print(self):
        self.h["items"][0]["variation"] = "【EN】(001)■プレリリース■《Example/Example Card》[MH2]"
        self.assertEqual(self.feed()["meta"]["excluded"]["specialFinish"], 1)

    def test_missing_or_leftover_collector_number_is_not_guessed(self):
        row = self.h["items"][0]
        row["variation"] = "【EN】《Example/Example Card》[MH2]"
        self.assertEqual(self.feed()["items"], [])
        row["collectorNumber"] = ""
        self.assertEqual(self.feed()["meta"]["excluded"]["numberMissing"], 1)

    def test_reskin_dual_names_require_both_names_on_the_exact_print(self):
        row = self.h["items"][0]
        row.update(name="Reskinned Name // Example Card", variation="【EN】(001)《甲/Reskinned Name》//《乙/Example Card》[MH2]")
        self.ids[SID]["flavor_name"] = "Reskinned Name"
        self.assertEqual(len(self.feed()["items"]), 1)
        row.update(name="Unrelated Name // Example Card", variation="【EN】(001)《甲/Unrelated Name》//《乙/Example Card》[MH2]")
        self.assertEqual(self.feed()["items"], [])

    def test_ambiguous_ck_print_is_not_resolved_by_cheapest_price(self):
        other = copy.deepcopy(self.ck["cards"][0])
        other["sku"] = "MH2-1-special"
        other["conditions"]["nm_qty"] = 0
        self.ck["cards"].append(other)
        self.assertEqual(self.feed()["meta"]["excluded"]["ambiguousCK"], 1)

    def test_ambiguous_hareruya_products_are_not_merged(self):
        other = copy.deepcopy(self.h["items"][0])
        other["productId"] = "11"
        self.h["items"].append(other)
        self.assertEqual(self.feed()["items"], [])
        self.assertEqual(self.feed()["meta"]["excluded"]["ambiguousHareruya"], 2)

    def test_an_old_ambiguous_product_does_not_bypass_identity_checks(self):
        other = copy.deepcopy(self.h["items"][0])
        other.update(productId="11", buyCapturedAt="2026-08-01T00:00:00Z")
        self.h["items"].append(other)
        self.assertEqual(self.feed()["items"], [])

    def test_identity_service_result_must_match_exact_id_name_and_version(self):
        for field, value in (("id", "other"), ("name", "Other Card"), ("set", "mh1"), ("collector_number", "2")):
            with self.subTest(field=field):
                old = self.ids[SID][field]
                self.ids[SID][field] = value
                self.assertEqual(self.feed()["items"], [])
                self.ids[SID][field] = old
        self.ids.clear()
        self.assertEqual(self.feed()["meta"]["excluded"]["identityMissing"], 1)

    def test_stale_quote_fx_and_capture_errors_are_excluded(self):
        old = "2026-11-10T10:00:00+00:00"
        self.ck["meta"]["capturedAt"] = old
        self.assertEqual(self.feed()["meta"]["excluded"]["ckStale"], 1)
        self.ck["meta"]["capturedAt"] = AT
        self.fx["sourceAt"] = old
        self.assertEqual(self.feed()["meta"]["excluded"]["fxStale"], 1)
        self.fx["sourceAt"] = AT
        self.h["items"][0]["captureError"] = "timeout"
        self.assertEqual(self.feed()["meta"]["excluded"]["hareruyaStale"], 1)

    def test_stop_buying_is_removed_without_negative_or_zero_quote(self):
        self.h["items"][0]["buy"]["EN"] = 0
        self.assertEqual(self.feed()["meta"]["excluded"]["hareruyaUnavailable"], 1)

    def test_membership_is_automatically_removed_and_readded_without_duplicate_events(self):
        first = self.feed()
        self.assertEqual(first["events"], [])
        self.ck["cards"][0]["conditions"]["nm_price"] = "10.00"
        second = self.feed(first)
        self.assertEqual(second["items"], [])
        self.assertEqual(second["events"][0]["type"], "removed")
        self.assertIn("达到或超过", second["events"][0]["reason"])
        third = self.feed(second)
        self.assertEqual(len(third["events"]), 1)
        self.ck["cards"][0]["conditions"]["nm_price"] = "5.00"
        fourth = self.feed(third)
        self.assertEqual(len(fourth["items"]), 1)
        self.assertEqual(len(fourth["events"]), 2)
        self.assertEqual(fourth["meta"]["lastRunAdded"], 1)


if __name__ == "__main__":
    unittest.main()
