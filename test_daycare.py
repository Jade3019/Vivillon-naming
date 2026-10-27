import tempfile
import unittest
from pathlib import Path

from daycare import (
    BOX_LIMIT,
    BoxStore,
    build_candidates,
    egg_groups_for,
    find_pairs,
    load_settings,
    parse_pokemon_lines,
)

SAMPLE = """`52913`　<:litwick:123> **Litwick** <:male:1> "snack" • Lvl. 14 • 79.57%
`52916`　<:litwick:123> **✨ Litwick** <:female:2> • Lvl. 27 • 79.57%
`30113`　**Marine Vivillon** ♂ • Lvl. 3 • 75.81%
not a pokemon line"""


class DaycareTests(unittest.TestCase):
    def test_parse_lines(self) -> None:
        parsed = dict(parse_pokemon_lines([SAMPLE]))
        self.assertEqual(parsed["52913"], ["Litwick", "M", 79.57, False])
        self.assertEqual(parsed["52916"], ["Litwick", "F", 79.57, True])
        self.assertEqual(parsed["30113"], ["Marine Vivillon", "M", 75.81, False])
        self.assertEqual(len(parsed), 3)

    def test_nickname_does_not_change_gender(self) -> None:
        parsed = dict(
            parse_pokemon_lines(['`1` **Eevee** <:female:2> "male" • Lvl. 1 • 50.00%'])
        )
        self.assertEqual(parsed["1"][1], "F")

    def test_egg_groups(self) -> None:
        self.assertTrue(egg_groups_for("Marine Vivillon"))
        self.assertTrue(egg_groups_for("Alolan Raichu"))
        self.assertTrue(egg_groups_for("Mr. Mime"))
        self.assertEqual(egg_groups_for("Notapokemon"), ())

    def test_pairs_share_group_and_opposite_gender(self) -> None:
        entries = {
            "1": ["Litwick", "M", 90.0, False],
            "2": ["Litwick", "M", 50.0, False],
            "3": ["Litwick", "F", 80.0, False],
            "4": ["Pikachu", "F", 99.0, False],
            "5": ["Mewtwo", "F", 99.0, False],
            "6": ["Litwick", "F", 99.0, True],
        }
        pairs = find_pairs(build_candidates(entries, False), 2)
        self.assertEqual([(m.code, f.code) for m, f in pairs], [("1", "3")])
        shiny = find_pairs(build_candidates(entries, True), 1)
        self.assertEqual([(m.code, f.code) for m, f in shiny], [("1", "6")])

    def test_ditto_is_fallback_partner(self) -> None:
        entries = {
            "1": ["Pikachu", "M", 90.0, False],
            "2": ["Ditto", "N", 10.0, False],
        }
        pairs = find_pairs(build_candidates(entries, False), 1)
        self.assertEqual({c.code for c in pairs[0]}, {"1", "2"})

    def test_store_limit_and_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boxes.json"
            store = BoxStore(path)
            slug = store.create_box(1, "Draco")
            parsed = [(str(i), ["Litwick", "M", 1.0, False]) for i in range(BOX_LIMIT + 5)]
            added, present, skipped = store.add_entries(1, slug, parsed)
            self.assertEqual((added, present, skipped), (BOX_LIMIT, 0, 5))
            with self.assertRaises(ValueError):
                store.create_box(1, "draco")
            reloaded = BoxStore(path)
            self.assertEqual(len(reloaded.boxes(1)["draco"]["entries"]), BOX_LIMIT)
            self.assertEqual(reloaded.find_box(1, "Draco"), "draco")

    def test_settings_defaults(self) -> None:
        self.assertEqual(load_settings({"pairs": 5, "grace": "x"})["pairs"], 1)
        self.assertEqual(load_settings(None)["grace"], 1)


if __name__ == "__main__":
    unittest.main()
