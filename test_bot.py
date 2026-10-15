import unittest

from bot import format_catch_command, format_guess, format_spawn_reply, is_valid_pokemon_name


class GuessFormatTests(unittest.TestCase):
    def test_formats_one_guess_without_a_label(self) -> None:
        self.assertEqual(format_guess("Pikachu", 85), "Pikachu: 85%")

    def test_formats_plain_poketwo_catch_command(self) -> None:
        self.assertEqual(
            format_catch_command(716390085896962058, "Pikachu"),
            "<@716390085896962058> c pikachu",
        )

    def test_formats_guess_and_command_on_separate_lines(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 85, 716390085896962058),
            "Pikachu: 85%\n`<@716390085896962058> c pikachu`",
        )


class PokemonNameValidationTests(unittest.TestCase):
    def test_accepts_unicode_pokemon_names(self) -> None:
        for name in ("Flabébé", "Nidoran♀", "Type: Null"):
            with self.subTest(name=name):
                self.assertTrue(is_valid_pokemon_name(name))

    def test_rejects_multiple_candidates_and_unexpected_symbols(self) -> None:
        self.assertFalse(is_valid_pokemon_name("Gothorita / Gothita"))
        self.assertFalse(is_valid_pokemon_name("Gothorita!"))


if __name__ == "__main__":
    unittest.main()
