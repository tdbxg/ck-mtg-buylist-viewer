import copy
from datetime import datetime, timedelta
import unittest

import test_hareruya_opportunities as fixtures

AT, SID = fixtures.AT, fixtures.SID


class CatalogTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.OpportunityTests()
        fixture.setUp()
        self.h, self.ck, self.fx, self.ids = fixture.h, fixture.ck, fixture.fx, fixture.ids

    def feed(self, history=None):
        from build_hareruya_opportunities import build_feed
        return build_feed(self.h, self.ck, self.fx, self.ids, {}, AT, history=history)

    def test_old_quotes_are_searchable_but_never_current_opportunities(self):
        self.h["items"][0]["buyCapturedAt"] = "2026-08-01T10:00:00+00:00"
        feed = self.feed()
        self.assertEqual(feed["items"], [])
        row = feed["catalog"]["items"][0]
        self.assertEqual(row["quoteStatus"], "historical")
        self.assertEqual(row["hareruyaBuyJpy"], 1000)
        self.assertEqual(row["hareruyaCapturedAt"], "2026-08-01T10:00:00+00:00")
        self.assertEqual(row["spreadJpy"], 500)
        self.assertFalse(row["currentComparison"])
        self.assertEqual(row["observation"]["observedDays"], 0)
        self.assertFalse(row["observation"]["coverageComplete"])

    def test_every_english_record_is_retained_including_missing_identity_and_zero(self):
        original = self.h["items"][0]
        other = {**copy.deepcopy(original), "productId": "11", "variation": "", "collectorNumber": "", "buy": {"EN": 0}}
        jp = {**copy.deepcopy(original), "productId": "12", "language": "JP"}
        self.h["items"].extend([other, jp])
        rows = self.feed()["catalog"]["items"]
        self.assertEqual({r["key"] for r in rows}, {"10|EN", "11|EN"})
        unmatched = next(r for r in rows if r["productId"] == "11")
        self.assertIsNone(unmatched["ckRetailUsd"])
        self.assertIsNone(unmatched["spreadJpy"])
        self.assertEqual(unmatched["hareruyaBuyJpy"], 0)
        self.assertEqual(unmatched["matchStatus"], "identityMissing")

    def test_failed_capture_is_distinct_from_an_old_observation(self):
        self.h["items"][0]["captureError"] = "timeout"
        feed = self.feed()
        self.assertEqual(feed["catalog"]["items"][0]["quoteStatus"], "failed")
        self.assertEqual(feed["meta"]["catalog"]["failed"], 1)
        self.assertEqual(feed["catalog"]["items"][0]["hareruyaBuyJpy"], 1000)
        self.assertFalse(feed["catalog"]["items"][0]["currentComparison"])

    def test_identity_coverage_does_not_disappear_behind_quote_age(self):
        self.h["items"][0].update(variation="", buyCapturedAt="2026-08-01T00:00:00Z")
        meta = self.feed()["catalog"]["meta"]
        self.assertEqual(meta.get("identityReasons"), {"identityMissing":1})
        self.assertEqual(meta["historical"], 1)

    def test_negative_spreads_and_out_of_stock_remain_searchable(self):
        self.ck["cards"][0]["conditions"] = {"nm_price": "12.00", "nm_qty": 0}
        feed = self.feed()
        self.assertEqual(feed["items"], [])
        row = feed["catalog"]["items"][0]
        self.assertEqual(row["spreadJpy"], -200)
        self.assertEqual(row["ckNmQty"], 0)
        self.assertFalse(row["currentComparison"])

    def test_unverified_matching_never_exposes_an_assumed_ck_price(self):
        self.ids[SID]["collector_number"] = "2"
        row = self.feed()["catalog"]["items"][0]
        self.assertEqual(row["matchStatus"], "identityMismatch")
        self.assertIsNone(row["ckRetailUsd"])
        self.assertIsNone(row["spreadJpy"])
        self.assertEqual(row["scryfallId"], "")

    def test_verified_rows_export_the_concrete_print_id(self):
        row = self.feed()["catalog"]["items"][0]
        self.assertEqual(row["scryfallId"], SID)
        self.assertEqual(row["ckSku"], "MH2-1")

    def test_expired_ck_and_fx_stay_reference_only(self):
        for source in (self.ck["meta"], self.fx):
            field = "capturedAt" if source is self.ck["meta"] else "sourceAt"
            source[field] = "2026-11-01T10:00:00+00:00"
        row = self.feed()["catalog"]["items"][0]
        self.assertEqual(row["ckRetailUsd"], 5)
        self.assertFalse(row["currentComparison"])

    def test_repeated_same_price_with_a_large_gap_is_not_thirty_day_coverage(self):
        end = datetime.fromisoformat(AT)
        points = [[int((end - timedelta(days=29)).timestamp()), 1000], [int(end.timestamp()), 1000]]
        observation = self.feed({"records": {"10|EN": {"buy": points}}})["catalog"]["items"][0]["observation"]
        self.assertEqual(observation["observedDays"], 2)
        self.assertFalse(observation["coverageComplete"])
        self.assertEqual(observation["minimumJpy"], 1000)

    def test_thirty_days_need_actual_daily_observations_and_include_stop_buying(self):
        end = datetime.fromisoformat(AT)
        points = [[int((end - timedelta(days=i)).timestamp()), 1000] for i in range(29, -1, -1)]
        history = {"records": {"10|EN": {"buy": points}}}
        observation = self.feed(history)["catalog"]["items"][0]["observation"]
        self.assertTrue(observation["coverageComplete"])
        self.assertEqual(observation["observedDays"], 30)
        self.assertEqual(observation["floorSpreadJpy"], 500)
        points[10][1] = 0
        observation = self.feed(history)["catalog"]["items"][0]["observation"]
        self.assertTrue(observation["stopObserved"])
        self.assertEqual(observation["minimumJpy"], 0)
        self.assertEqual(observation["floorSpreadJpy"], -500)

    def test_day_coverage_does_not_count_thirty_one_calendar_boundaries(self):
        end = datetime.fromisoformat(AT)
        points = [[int((end - timedelta(days=i)).timestamp()), 1000] for i in range(30, -1, -1)]
        observation = self.feed({"records": {"10|EN": {"buy": points}}})["catalog"]["items"][0]["observation"]
        self.assertEqual(observation["observedDays"], 30)


if __name__ == "__main__":
    unittest.main()
