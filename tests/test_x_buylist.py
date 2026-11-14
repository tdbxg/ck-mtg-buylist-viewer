import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_x_buylist import normalize_post, parse_timeline, search_ids
import collect_x_buylist as collector
import json


class XTests(unittest.TestCase):
    def test_preserves_original_time_images_and_exact_id(self):
        tweet = {"id_str": "123456789", "created_at": "Sat Nov 14 01:00:00 +0000 2026", "full_text": "MTG 買取 1,000円", "user": {"screen_name": "hareruya_mtg"}, "entities": {"media": [{"media_url_https": "https://pbs.twimg.com/media/example.jpg"}]}}
        row = normalize_post(tweet, {"handle": "hareruya_mtg", "label": "Official"}, ["買取"], "2026-11-14T03:00:00Z")
        self.assertEqual(row["publishedAt"], "2026-11-14T01:00:00+00:00")
        self.assertEqual(row["id"], "123456789")
        self.assertEqual(row["quotes"], [])
        self.assertEqual(row["priceStatus"], "imageReviewNeeded")

    def test_rejects_other_accounts_and_other_games(self):
        a = {"handle": "hareruya_mtg", "label": "Official"}
        self.assertIsNone(normalize_post({"text": "買取", "user": {"screen_name": "someone_else"}}, a, ["買取"], "now"))
        self.assertIsNone(normalize_post({"text": "ポケカ 買取", "user": {"screen_name": "hareruya_mtg"}}, a, ["買取"], "now"))

    def test_login_or_rate_limit_page_is_a_failure(self):
        with self.assertRaises(ValueError):
            parse_timeline("<html>Rate limit exceeded</html>")

    def test_search_only_discovers_exact_official_account_links(self):
        entries = [{"url": "https://x.com/hareruya_mtg/status/123", "screenName": "hareruya_mtg"},
                   {"url": "https://x.com/other/status/456", "screenName": "other"}]
        data = {"props": {"pageProps": {"pageData": {"searchError": {"errorType": ""}, "timeline": {"entry": entries}}}}}
        page = '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'
        self.assertEqual(search_ids(page, "hareruya_mtg"), ["123"])

    def test_head_office_scope_cannot_discover_branch_accounts(self):
        config = {"scope": "headOffice", "accounts": [{"handle": "hareruya_mtg"}], "shopPages": ["https://example.test/shop"]}
        with patch.object(collector, "fetch") as fetch:
            collector.discover_accounts(config)
        fetch.assert_not_called()
        self.assertEqual(len(config["accounts"]), 1)

    def test_branch_posts_are_archived_and_not_reintroduced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {"OUTPUT": root / "active.json", "ARCHIVE": root / "archive.json", "CONFIG": root / "sources.json"}
            paths["CONFIG"].write_text(json.dumps({"scope": "headOffice", "accounts": [{"handle": "hareruya_mtg", "label": "Official"}], "keywords": ["買取"], "maxItems": 100}))
            posts = [{"id": "1", "account": "hareruya_mtg", "text": "MTG 買取 1,000円", "publishedAt": "2026-11-14T01:00:00Z"},
                     {"id": "2", "account": "hareruya_TC", "text": "MTG 買取 2,000円", "publishedAt": "2026-11-14T02:00:00Z"}]
            paths["OUTPUT"].write_text(json.dumps({"items": posts}))
            paths["ARCHIVE"].write_text(json.dumps({"items": [posts[1]]}))
            with patch.multiple(collector, **paths), patch.object(collector, "recent_ids", return_value=[]), patch("builtins.print"):
                self.assertEqual(collector.collect(), 0)
                self.assertEqual(collector.collect(), 0)
            self.assertEqual([p["id"] for p in json.loads(paths["OUTPUT"].read_text())["items"]], ["1"])
            self.assertEqual([p["id"] for p in json.loads(paths["ARCHIVE"].read_text())["items"]], ["2"])
