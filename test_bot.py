import tempfile
import unittest
from pathlib import Path

from bot import (
    format_catch_command,
    format_guess,
    format_reservation_embeds,
    format_spawn_reply,
    is_valid_pokemon_name,
    load_reservations,
    parse_reserve_add_command,
    remove_reservation,
    reservation_key,
    reserved_pokemon_for_user,
    save_reservations,
)


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
            "Pikachu: 85%\n"
            "`<@716390085896962058> c pikachu`",
        )

    def test_formats_only_the_reserved_members_as_mentions(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 716390085896962058, [123, 456]),
            "Pikachu: 95%\n"
            "Reserved: <@123>, <@456>\n"
            "`<@716390085896962058> c pikachu`",
        )


class ReservationPersistenceTests(unittest.TestCase):
    def test_reservation_keys_are_case_insensitive(self) -> None:
        self.assertEqual(reservation_key(1, "Pikachu"), reservation_key(1, "PIKACHU"))
        self.assertNotEqual(reservation_key(1, "Pikachu"), reservation_key(2, "Pikachu"))

    def test_saves_multiple_members_and_loads_them_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reserves.json"
            data = {reservation_key(1, "Pikachu"): [123, 456]}

            save_reservations(path, data)

            self.assertEqual(load_reservations(path), data)

    def test_parses_multiple_pokemon_names_and_member_mention(self) -> None:
        self.assertEqual(
            parse_reserve_add_command("v!r add pikachu, eevee <@319>"),
            (["pikachu", "eevee"], 319),
        )

    def test_rejects_invalid_or_empty_names_in_multi_add(self) -> None:
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu,,eevee <@319>"))
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu! <@319>"))

    def test_search_lists_only_reservations_for_user_and_guild(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123],
            reservation_key(1, "Eevee"): [456],
            reservation_key(2, "Bulbasaur"): [123],
        }
        self.assertEqual(
            reserved_pokemon_for_user(reservations, 1, 123),
            ["pikachu"],
        )

    def test_removes_pokemon_reservation_for_one_user(self) -> None:
        reservations = {reservation_key(1, "Pikachu"): [123, 456]}

        updated, removed = remove_reservation(reservations, 1, "pikachu", 123)

        self.assertTrue(removed)
        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})
        self.assertEqual(reservations[reservation_key(1, "Pikachu")], [123, 456])

    def test_removes_pokemon_reservation_for_everyone(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(2, "Pikachu"): [789],
        }

        updated, removed = remove_reservation(reservations, 1, "Pikachu")

        self.assertTrue(removed)
        self.assertNotIn(reservation_key(1, "Pikachu"), updated)
        self.assertEqual(updated[reservation_key(2, "Pikachu")], [789])

    def test_does_not_report_removal_when_user_is_not_reserved(self) -> None:
        reservations = {reservation_key(1, "Pikachu"): [123]}

        updated, removed = remove_reservation(reservations, 1, "Pikachu", 456)

        self.assertFalse(removed)
        self.assertEqual(updated, reservations)

    def test_formats_reservation_embed_and_splits_long_lists(self) -> None:
        embeds = format_reservation_embeds("Jade", ["eevee", "pikachu"])
        self.assertEqual(embeds[0].title, "Pokémon reserved by Jade")
        self.assertEqual(embeds[0].description, "Eevee\nPikachu")

        long_embeds = format_reservation_embeds("Jade", ["pikachu"] * 600)
        self.assertGreater(len(long_embeds), 1)
        self.assertTrue(all(len(embed.description or "") <= 4096 for embed in long_embeds))


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
