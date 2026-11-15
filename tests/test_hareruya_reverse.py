import copy
import unittest

import test_hareruya_opportunities as fixtures
from build_hareruya_opportunities import build_feed, hareruya_identity, resolution_key


class ReverseTests(unittest.TestCase):
    def setUp(self):
        t = fixtures.OpportunityTests()
        t.setUp()
        self.h, self.ck, self.fx, self.ids = t.h, t.ck, t.fx, t.ids
        self.h["items"][0].update(sale={"EN":{"NM":600}}, saleStock={"EN":{"NM":2}}, saleCapturedAt=fixtures.AT, retailVerified=True)
        self.ck["cards"][0].update(cashUsd=10, qtyBuying=3)

    def feed(self, resolutions=None):
        return build_feed(self.h,self.ck,self.fx,self.ids,{},fixtures.AT,resolutions=resolutions)

    def test_reverse_uses_cash_buy_not_credit_or_retail(self):
        r=self.feed()["reverseItems"][0]
        self.assertEqual((r["ckCashUsd"],r["ckBuyingQty"],r["hareruyaNmQty"]),(10,3,2))
        self.assertEqual(r["reverseBufferJpy"],100)
        self.assertEqual(r["reverseSpreadJpy"],400)

    def test_equal_to_seventy_percent_is_excluded_without_rounding(self):
        for sale in (700,701):
            self.h["items"][0]["sale"]["EN"]["NM"]=sale
            self.assertEqual(self.feed()["reverseItems"],[])

    def test_zero_or_unknown_sale_stock_and_zero_ck_buy_capacity_are_excluded(self):
        for qty in (0,None):
            self.h["items"][0]["saleStock"]["EN"]["NM"]=qty
            self.assertEqual(self.feed()["reverseItems"],[])
        self.h["items"][0]["saleStock"]["EN"]["NM"]=2
        self.ck["cards"][0]["qtyBuying"]=0
        self.assertEqual(self.feed()["reverseItems"],[])

    def test_old_sale_and_capture_failure_are_not_buyable_reverse_candidates(self):
        self.h["items"][0]["saleCapturedAt"]="2026-11-01T00:00:00Z"
        self.assertEqual(self.feed()["reverseItems"],[])
        self.h["items"][0]["saleCapturedAt"]=fixtures.AT
        self.h["items"][0]["saleCaptureError"]="timeout"
        self.assertEqual(self.feed()["reverseItems"],[])

    def test_missing_number_can_only_resolve_from_complete_unique_print_enumeration(self):
        r=self.h["items"][0]
        r.update(variation="【EN】《Example/Example Card》[MH2]",collectorNumber="")
        k=resolution_key(r,"mh2","nonfoil")
        proof={k:{"complete":True,"checkedAt":fixtures.AT,"cards":[self.ids[fixtures.SID]]}}
        self.assertEqual(len(self.feed(proof)["reverseItems"]),1)
        self.assertEqual(hareruya_identity(r)[1],"numberMissing")
        proof[k]["cards"].append(copy.deepcopy(self.ids[fixtures.SID]))
        self.assertEqual(self.feed(proof)["reverseItems"],[])
        proof[k]["cards"]=proof[k]["cards"][:1]
        proof[k]["complete"]=False
        self.assertEqual(self.feed(proof)["reverseItems"],[])

    def test_resolution_cannot_override_title_edition_or_name(self):
        r=self.h["items"][0]
        r.update(variation="【EN】《Other/Other Card》[MH2]",collectorNumber="")
        k=resolution_key(r,"mh2","nonfoil")
        proof={k:{"complete":True,"checkedAt":fixtures.AT,"cards":[self.ids[fixtures.SID]]}}
        self.assertEqual(self.feed(proof)["reverseItems"],[])

    def test_old_foil_star_number_and_nonfoil_print_are_resolved_separately(self):
        row=self.h["items"][0]
        row.update(variation="【EN】【Foil】《Example/Example Card》[MH2]",collectorNumber="")
        normal={**copy.deepcopy(self.ids[fixtures.SID]),"collector_number":"1","finishes":["nonfoil"]}
        foil={**copy.deepcopy(self.ids[fixtures.SID]),"collector_number":"1★","finishes":["foil"]}
        proof={resolution_key(row,"mh2","foil"):{"complete":True,"checkedAt":fixtures.AT,"cards":[normal,foil]}}
        self.assertEqual(hareruya_identity(row,proof,fixtures.AT),(("mh2","1*","foil"),""))

    def test_retail_must_be_english_and_ck_quote_must_be_current(self):
        self.h["items"][0]["saleStock"]={"JP":{"NM":5}}
        self.assertEqual(self.feed()["reverseItems"],[])
        self.h["items"][0]["saleStock"]={"EN":{"NM":2}}
        self.ck["meta"]["capturedAt"]="2026-11-01T00:00:00Z"
        self.assertEqual(self.feed()["reverseItems"],[])


if __name__=="__main__":
    unittest.main()
