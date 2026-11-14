import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_x_buylist import normalize_post, parse_timeline


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
