import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hareruya_catalog_rotation as rotation


def listing(product, page=1, last=1):
    return f'''<p class="count_number">{last * 60}</p><li class="itemList">
    <a class="itemName" href="/ja/purchase/detail/{product}?lang=EN">【Foil】(001)《甲/Example Card》[SLD]</a>
    <p class="itemDetail__price">¥ 1,200</p></li>
    <a class="page_last" href="/ja/purchase/search?cardset=223&amp;language%5B%5D=2&amp;purchaseFlg=1&amp;sort=price&amp;order=DESC&amp;page={last}">最後</a>'''


class RotationTests(unittest.TestCase):
    def test_series_form_placeholder_without_value_is_ignored(self):
        html = '<select name="cardset"><option value>none</option>' + ''.join(f'<option value="{i}">Series {i}</option>' for i in range(1, 105)) + '</select>'
        self.assertEqual(len(rotation.discover_partitions(html)["partitions"]), 104)

    def state(self):
        return {"version":1, "partitions":[{"id":"223", "name":"Secret Lair Series", "nextPage":1}], "cursor":0}

    def test_pages_resume_and_retain_all_old_quotes(self):
        state = self.state()
        with patch.object(rotation, "fetch", side_effect=[listing(1, 1, 3), listing(2, 2, 3)]), patch.object(rotation.time, "sleep"):
            rows, state, report = rotation.capture(state, 2, "2026-11-15T10:00:00Z")
        self.assertEqual([r["productId"] for r in rows], ["1", "2"])
        self.assertEqual(state["partitions"][0]["nextPage"], 3)
        self.assertEqual(report["pagesCompleted"], 2)
        with patch.object(rotation, "fetch", return_value=listing(3, 3, 3)), patch.object(rotation.time, "sleep"):
            rows, state, report = rotation.capture(state, 1, "2026-11-15T11:00:00Z")
        self.assertEqual(rows[0]["productId"], "3")
        self.assertEqual(state["partitions"][0]["nextPage"], 1)
        self.assertEqual(state["partitions"][0]["completedPasses"], 1)

    def test_failure_never_advances_cursor_or_stamps_quotes(self):
        from urllib.error import HTTPError
        state = self.state()
        with patch.object(rotation, "fetch", side_effect=HTTPError("https://www.hareruyamtg.com/", 403, "Forbidden", {}, None)), patch.object(rotation.time, "sleep"):
            rows, new, report = rotation.capture(deepcopy(state), 20, "2026-11-15T10:00:00Z")
        self.assertEqual(rows, [])
        self.assertEqual(new["partitions"][0]["nextPage"], 1)
        self.assertTrue(report["blockedUntil"])
        self.assertEqual(report["pagesAttempted"], 1)

    def test_pagination_ignores_recommendations_and_other_filters(self):
        html = listing(1, last=3) + '<a href="/ja/purchase/search?cardset=999&page=500">other</a>'
        self.assertEqual(rotation.page_info(html, "223")["lastPage"], 3)

    def test_real_pagination_uses_php_indexed_language_arrays(self):
        html = '<p class="count_number">4239</p><a class="page_last" href="https://www.hareruyamtg.com/ja/purchase/search?cardset=223&amp;language%5B0%5D=2&amp;purchaseFlg=1&amp;sort=price&amp;order=DESC&amp;page=71">last</a>'
        self.assertEqual(rotation.page_info(html, "223")["lastPage"], 71)

    def test_too_many_results_is_not_a_successful_empty_page(self):
        html = '<p class="search_results_exceeded">too many</p>'
        with patch.object(rotation, "fetch", return_value=html), patch.object(rotation.time, "sleep"):
            rows, state, report = rotation.capture(self.state(), 1, "2026-11-15T10:00:00Z")
        self.assertEqual(rows, [])
        self.assertEqual(report["pagesCompleted"], 0)
        self.assertIn("refine", report["failures"][0])
