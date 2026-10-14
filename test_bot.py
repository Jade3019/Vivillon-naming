import unittest

from bot import extract_stats, format_guess


class ExtractStatsTests(unittest.TestCase):
    def test_extracts_level_gender_and_iv_percentage(self) -> None:
        self.assertEqual(
            extract_stats("Caught Level 17 Pikachu Gender: Female IV: 81.2%"),
            {"Level": "17", "Gender": "Female", "IV": "81.2%"},
        )

    def test_extracts_gender_symbol_and_ivs_percentage(self) -> None:
        self.assertEqual(
            extract_stats("Level: 5 | Gender: ♂ | IVs: 100%"),
            {"Level": "5", "Gender": "Male", "IV": "100%"},
        )

    def test_calculates_percentage_from_six_stat_ivs(self) -> None:
        self.assertEqual(
            extract_stats(
                "Level 3 HP: 31 Attack: 30 Defense: 29 "
                "Sp. Atk: 28 Sp. Def: 27 Speed: 26"
            ),
            {"Level": "3", "IV": "91.9%"},
        )

    def test_does_not_treat_an_iv_stat_spread_as_a_percentage(self) -> None:
        self.assertEqual(extract_stats("IVs: 31/31/31/31/31/31"), {})


class GuessFormatTests(unittest.TestCase):
    def test_formats_one_guess_without_a_label(self) -> None:
        self.assertEqual(format_guess("Pikachu", 85), "Pikachu: 85%")

if __name__ == "__main__":
    unittest.main()
