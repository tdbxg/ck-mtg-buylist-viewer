import copy
import gzip
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_site_data as refresh


class MarketRefreshTests(unittest.TestCase):
    def test_current_official_jsonl_catalog_is_read_without_legacy_endpoint(self):
        at = datetime.now(timezone.utc).isoformat()
        card = {"id": "exact-id", "prices": {"usd": "10.00"}}
        raw = gzip.compress((json.dumps(card) + "\n").encode())
        record = {"type": "default_cards", "updated_at": at,
                  "jsonl_download_uri": "https://data.scryfall.io/default-cards/current.jsonl.gz",
                  "compressed_size": len(raw)}

        def download(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(raw)

        with tempfile.TemporaryDirectory() as tmp, patch.object(refresh, "ROOT", Path(tmp)), \
                patch.object(refresh, "fetch_json", return_value={"data": [record]}) as fetch, \
                patch.object(refresh.subprocess, "run", side_effect=download):
            self.assertEqual(list(refresh.scryfall_bulk_cards()), [card])
            fetch.assert_called_once_with(refresh.SCRYFALL_BULK_LIST_URL, timeout=120)

    def test_known_print_id_cannot_fall_back_to_same_name_number(self):
        payload = {"cards": [{"scryfallId": "english-id", "name": "Example",
                              "scryfallSet": "tst", "collectorNumber": "1", "foil": False}]}
        other = {"id": "japanese-id", "name": "Example", "lang": "ja", "set": "tst",
                 "collector_number": "1", "prices": {"usd": "99.00"}}
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(refresh, "scryfall_bulk_cards", return_value=iter([other])):
            result = refresh.enrich_market_reference(payload)
        self.assertIsNone(result["cards"][0].get("marketUsd"))

    def test_fallback_preserves_actual_source_date_and_separates_foil(self):
        row = {"scryfallId": "exact-id", "name": "Example", "scryfallSet": "tst",
               "collectorNumber": "1", "foil": False}
        previous = {"meta": {"scryfallMarketUpdatedAt": "2026-11-18T10:00:00Z",
                             "scryfallMarketAcquiredAt": "2026-11-18T11:00:00Z"},
                    "cards": [{**row, "marketUsd": 10}, {**row, "foil": True, "marketUsd": 50}]}
        with patch.dict("os.environ", {"CK_SKIP_MARKET_BULK": "1"}):
            result = refresh.enrich_market_reference({"cards": [copy.deepcopy(row)]}, previous)
        self.assertEqual(result["cards"][0]["marketUsd"], 10)
        self.assertEqual(result["meta"].get("scryfallMarketUpdatedAt"), "2026-11-18T10:00:00Z")
        self.assertEqual(result["meta"].get("scryfallMarketStatus"), "stale")

    def test_stale_or_untrusted_bulk_metadata_is_not_used(self):
        for record in (
            {"updated_at": "2000-01-01T00:00:00Z", "jsonl_download_uri": "https://data.scryfall.io/old.jsonl.gz"},
            {"updated_at": datetime.now(timezone.utc).isoformat(), "jsonl_download_uri": "https://example.invalid/cards.jsonl.gz"},
        ):
            with self.subTest(record=record), patch.object(refresh, "fetch_json", return_value={
                "data": [{"type": "default_cards", **record}]
            }), self.assertRaises(ValueError):
                list(refresh.scryfall_bulk_cards())

    def test_fresh_reference_clears_old_marker_and_uses_exact_foil_price(self):
        row = {"scryfallId": "exact-id", "foil": True, "marketUsd": 999}
        card = {"id": "exact-id", "prices": {"usd": "10", "usd_foil": "50", "eur_foil": "40"}}

        def archive(metadata):
            yield card
            metadata.update(scryfallMarketUpdatedAt="2026-11-19T10:00:00Z")

        with patch.dict("os.environ", {}, clear=True), patch.object(refresh, "scryfall_bulk_cards", archive):
            result = refresh.enrich_market_reference({"meta": {"scryfallMarketSkipped": "bulk_download_unavailable"},
                                                      "cards": [row]})
        self.assertEqual(row["marketUsd"], 50)
        self.assertEqual(row["marketEur"], 40)
        self.assertEqual(result["meta"]["scryfallMarketStatus"], "fresh")
        self.assertNotIn("scryfallMarketSkipped", result["meta"])

    def test_interrupted_bulk_preserves_only_previous_complete_prices(self):
        row = {"scryfallId": "exact-id", "foil": False}

        def interrupted(metadata):
            yield {"id": "exact-id", "prices": {"usd": "90"}}
            raise EOFError("truncated archive")

        with patch.dict("os.environ", {}, clear=True), patch.object(refresh, "scryfall_bulk_cards", interrupted):
            result = refresh.enrich_market_reference_resilient({"cards": [row]}, {
                "meta": {"scryfallMarketUpdatedAt": "2026-11-18T10:00:00Z"},
                "cards": [{**row, "marketUsd": 10}]
            })
        self.assertEqual(row["marketUsd"], 10)
        self.assertEqual(result["meta"]["scryfallMarketStatus"], "stale")


if __name__ == "__main__":
    unittest.main()
