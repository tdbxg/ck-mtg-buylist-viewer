import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hareruya_bulk_prints import build_proofs, read_cards
from build_hareruya_opportunities import hareruya_identity

AT = "2026-11-15T10:00:00Z"


class BulkPrintTests(unittest.TestCase):
    def card(self, sid, collector, finishes, lang="en"):
        return {"id":sid, "name":"Example", "set":"10e", "lang":lang,
                "collector_number":collector, "finishes":finishes, "promo_types":[]}

    def test_en_and_same_finish_uniqueness_are_independently_verified(self):
        h = {"items":[{"name":"Example", "language":"EN", "set":"10ED", "variation":"【EN】【Foil】《甲/Example》[10ED]"}]}
        cards = [self.card("a", "1", ["nonfoil"]), self.card("b", "1★", ["foil"]), self.card("c", "1", ["foil"], "ja")]
        resolutions, identities = build_proofs(iter(cards), h, AT, "https://data.scryfall.io/example", AT)
        self.assertEqual(hareruya_identity(h["items"][0], resolutions, AT)[0], ("10e", "1*", "foil"))
        self.assertNotIn("c", identities)
        cards.append(self.card("d", "2", ["foil"]))
        resolutions, _ = build_proofs(iter(cards), h, AT, "https://data.scryfall.io/example", AT)
        self.assertEqual(hareruya_identity(h["items"][0], resolutions, AT)[1], "ambiguousPrint")

    def test_bulk_jsonl_is_streamed_and_truncated_gzip_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cards.jsonl.gz"
            with gzip.open(path, "wt") as handle:
                handle.write(json.dumps(self.card("a", "1", ["nonfoil"])) + "\n")
                handle.write(json.dumps(self.card("b", "2", ["foil"])) + "\n")
            self.assertEqual(len(list(read_cards(path))), 2)
            path.write_bytes(path.read_bytes()[:-10])
            with self.assertRaises((EOFError, OSError)):
                list(read_cards(path))

    def test_incomplete_print_records_cannot_prove_uniqueness(self):
        h = {"items":[{"name":"Example", "language":"EN", "set":"10ED", "variation":"【EN】【Foil】《甲/Example》[10ED]"}]}
        damaged = self.card("b", "2", ["foil"])
        damaged.pop("finishes")
        with self.assertRaises(ValueError):
            build_proofs(iter([self.card("a", "1", ["foil"]), damaged]), h, AT, "https://data.scryfall.io/example", AT)

    def test_bulk_reskin_proof_matches_alias_and_rules_name_not_a_guessed_split(self):
        h = {"items":[{"name":"Alias // Example", "language":"EN", "set":"10ED", "variation":"【EN】【Foil】《甲/Alias》//《乙/Example》[10ED]"}]}
        card = {**self.card("a", "1", ["foil"]), "flavor_name":"Alias"}
        proofs, ids = build_proofs(iter([card]), h, AT, "https://data.scryfall.io/example", AT)
        self.assertIn("a", ids)
        self.assertEqual(hareruya_identity(h["items"][0], proofs, AT)[0], ("10e", "1", "foil"))
