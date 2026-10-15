import tempfile
import unittest
from pathlib import Path

import discord

from bot import (
    add_shinyhunter,
    all_forms_reservation_key,
    clear_guild_reservations,
    format_catch_command,
    format_guess,
    format_all_forms_reservation_embeds,
    format_pokemon_reserver_embeds,
    format_remove_confirmation,
    format_reservation_embeds,
    format_server_reservation_embeds,
    format_shinyhunt_confirmation,
    format_spawn_reply,
    format_shinyhunt_status,
    is_valid_pokemon_name,
    load_pokemon_forms,
    load_reservations,
    parse_reserve_add_command,
    parse_reserve_remove_command,
    parse_shinyhunt_command,
    ReservationPagesView,
    remove_reservation,
    remove_reservations,
    reservation_key,
    reservation_key_for_command,
    reserved_pokemon_for_user,
    reserved_user_ids_for_pokemon,
    save_reservations,
    shinyhunt_pokemon_for_user,
    shinyhunter_user_ids_for_pokemon,
    pokemon_matches_all_forms_reservation,
)


class GuessFormatTests(unittest.TestCase):
    def test_formats_one_guess_without_a_label(self) -> None:
        self.assertEqual(format_guess("Pikachu", 85), "Pikachu: 85.00%")
        self.assertEqual(format_guess("Absol", 56.86), "Absol: 56.86%")

    def test_formats_plain_poketwo_catch_command(self) -> None:
        self.assertEqual(
            format_catch_command(716390085896962058, "Pikachu"),
            "<@716390085896962058> c pikachu",
        )

    def test_formats_guess_and_command_on_separate_lines(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 85, 716390085896962058),
            "Pikachu: 85.00%\n"
            "`<@716390085896962058> c pikachu`",
        )

    def test_formats_only_the_reserved_members_as_mentions(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 716390085896962058, [123, 456]),
            "Pikachu: 95.00%\n"
            "Reserved: <@123>, <@456>\n"
            "`<@716390085896962058> c pikachu`",
        )

    def test_formats_shinyhunters_when_no_reservations_exist(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [], [123, 456]),
            "Absol: 95.00%\n"
            "Shinyhunt: <@123>, <@456>\n"
            "`<@789> c absol`",
        )

    def test_reservations_override_shinyhunters_in_spawn_reply(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [999], [123, 456]),
            "Absol: 95.00%\n"
            "Reserved: <@999>\n"
            "`<@789> c absol`",
        )


class ReservationPersistenceTests(unittest.TestCase):
    def test_formats_removal_confirmations(self) -> None:
        self.assertEqual(format_remove_confirmation("pikachu", None), "Pikachu removed")
        self.assertEqual(
            format_remove_confirmation("pikachu", "@Jade0319"),
            "Pikachu removed from @Jade0319 Reserves",
        )
        self.assertEqual(
            format_remove_confirmation("pikachu, eevee", "@Jade0319"),
            "Pikachu, Eevee removed from @Jade0319 Reserves",
        )
        self.assertEqual(
            format_remove_confirmation("all arceus", "@Jade0319"),
            "All forms of arceus removed from @Jade0319 Reserves",
        )

    def test_reservation_keys_are_case_insensitive(self) -> None:
        self.assertEqual(reservation_key(1, "Pikachu"), reservation_key(1, "PIKACHU"))
        self.assertNotEqual(reservation_key(1, "Pikachu"), reservation_key(2, "Pikachu"))

    def test_all_forms_reservations_match_base_and_named_forms(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        for name in ("Arceus", "Arceus (Fire)", "Arceus-Fire", "Arceus Fire"):
            with self.subTest(name=name):
                self.assertEqual(
                    reserved_user_ids_for_pokemon(reservations, 1, name),
                    [123],
                )
        self.assertEqual(
            reserved_user_ids_for_pokemon(reservations, 2, "Arceus-Fire"),
            [],
        )
        self.assertEqual(
            reserved_user_ids_for_pokemon(reservations, 1, "Arceusian"),
            [],
        )
        self.assertFalse(
            pokemon_matches_all_forms_reservation("Raichu-Alola", "Raichu")
        )
        self.assertTrue(
            pokemon_matches_all_forms_reservation(
                "Pikachu-Alola-Cap",
                "Pikachu",
            )
        )

    def test_all_forms_command_uses_a_separate_reservation_key(self) -> None:
        self.assertEqual(
            reservation_key_for_command(1, "all Arceus"),
            all_forms_reservation_key(1, "Arceus"),
        )
        self.assertEqual(
            reservation_key_for_command(1, "Arceus"),
            reservation_key(1, "Arceus"),
        )

    def test_parses_one_valid_shinyhunt_name(self) -> None:
        self.assertEqual(parse_shinyhunt_command("v!sh Absol"), "Absol")

    def test_rejects_multiple_or_invalid_shinyhunt_names(self) -> None:
        self.assertIsNone(parse_shinyhunt_command("v!sh absol, eevee"))
        self.assertIsNone(parse_shinyhunt_command("v!sh absol!"))

    def test_shinyhunt_registration_replaces_only_that_users_previous_choice(
        self,
    ) -> None:
        shinyhunters = add_shinyhunter({}, 1, "Absol", 123)
        shinyhunters = add_shinyhunter(shinyhunters, 1, "Absol", 456)
        shinyhunters = add_shinyhunter(shinyhunters, 1, "Pikachu", 123)
        shinyhunters = add_shinyhunter(shinyhunters, 2, "Absol", 789)

        self.assertEqual(shinyhunters[reservation_key(1, "Absol")], [456])
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123])
        self.assertEqual(shinyhunters[reservation_key(2, "Absol")], [789])

    def test_all_forms_shinyhunt_matches_every_form_of_a_pokemon(self) -> None:
        shinyhunters = add_shinyhunter({}, 1, "all arceus", 123)

        self.assertEqual(
            shinyhunters,
            {all_forms_reservation_key(1, "Arceus"): [123]},
        )
        for form_name in ("Arceus", "Arceus-Fire", "Fairy Arceus"):
            with self.subTest(form_name=form_name):
                self.assertEqual(
                    shinyhunter_user_ids_for_pokemon(
                        shinyhunters,
                        1,
                        form_name,
                    ),
                    [123],
                )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(shinyhunters, 2, "Arceus-Fire"),
            [],
        )

    def test_all_forms_shinyhunt_matches_catalogued_pichu_form(self) -> None:
        shinyhunters = add_shinyhunter({}, 1, "all pichu", 123)

        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                shinyhunters,
                1,
                "Spiky-eared Pichu",
            ),
            [123],
        )

    def test_formats_shinyhunt_status_in_lowercase(self) -> None:
        self.assertEqual(
            format_shinyhunt_status("Absol"),
            "You are currently shinyhunting absol",
        )
        self.assertEqual(
            format_shinyhunt_confirmation("Pikachu"),
            "You are now shinyhunting pikachu",
        )
        self.assertEqual(
            format_shinyhunt_confirmation("all arceus"),
            "You are now shinyhunting all forms of arceus",
        )
        self.assertEqual(
            format_shinyhunt_status("all arceus"),
            "You are currently shinyhunting all forms of arceus",
        )

    def test_lists_the_single_shinyhunt_pokemon_for_one_user_and_guild(self) -> None:
        shinyhunters = {
            reservation_key(1, "Absol"): [123, 456],
            reservation_key(1, "Eevee"): [456],
            reservation_key(1, "Pikachu"): [789],
            reservation_key(2, "Bulbasaur"): [123],
        }

        self.assertEqual(
            shinyhunt_pokemon_for_user(shinyhunters, 1, 123),
            ["absol"],
        )
        self.assertEqual(shinyhunt_pokemon_for_user(shinyhunters, 1, 999), [])
        all_forms = add_shinyhunter({}, 1, "all arceus", 123)
        self.assertEqual(
            shinyhunt_pokemon_for_user(all_forms, 1, 123),
            ["all arceus"],
        )

    def test_persists_shinyhunt_registrations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shinyhunts.json"
            shinyhunters = add_shinyhunter({}, 1, "Absol", 123)

            save_reservations(path, shinyhunters)

            self.assertEqual(load_reservations(path), shinyhunters)

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
        self.assertEqual(
            parse_reserve_add_command("v!r add all arceus <@319>"),
            (["all arceus"], 319),
        )

    def test_rejects_invalid_or_empty_names_in_multi_add(self) -> None:
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu,,eevee <@319>"))
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu! <@319>"))

    def test_parses_multiple_pokemon_names_for_removal(self) -> None:
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee <@319>"),
            (["pikachu", "eevee"], 319),
        )
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee, <@319>"),
            (["pikachu", "eevee"], 319),
        )
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee"),
            (["pikachu", "eevee"], None),
        )

    def test_rejects_invalid_or_empty_names_in_multi_remove(self) -> None:
        self.assertIsNone(parse_reserve_remove_command("v!r remove pikachu,,eevee"))
        self.assertIsNone(parse_reserve_remove_command("v!r remove pikachu!"))

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

    def test_member_reserve_list_labels_all_forms(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        self.assertEqual(
            reserved_pokemon_for_user(reservations, 1, 123),
            ["all forms of arceus"],
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

    def test_removes_all_forms_reservation(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        updated, removed = remove_reservation(reservations, 1, "all arceus", 123)

        self.assertTrue(removed)
        self.assertEqual(updated, {})

    def test_clears_all_reservations_for_one_guild_only(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Bulbasaur"): [123],
        }

        updated = clear_guild_reservations(reservations, 1)

        self.assertEqual(updated, {reservation_key(2, "Bulbasaur"): [123]})
        self.assertEqual(len(reservations), 3)

    def test_does_not_report_removal_when_user_is_not_reserved(self) -> None:
        reservations = {reservation_key(1, "Pikachu"): [123]}

        updated, removed = remove_reservation(reservations, 1, "Pikachu", 456)

        self.assertFalse(removed)
        self.assertEqual(updated, reservations)

    def test_removes_multiple_pokemon_and_reports_missing_names(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123],
            reservation_key(1, "Eevee"): [123, 456],
            reservation_key(2, "Bulbasaur"): [123],
        }

        updated, removed, missing = remove_reservations(
            reservations,
            1,
            ["pikachu", "eevee", "bulbasaur"],
        )

        self.assertEqual(removed, ["pikachu", "eevee"])
        self.assertEqual(missing, ["bulbasaur"])
        self.assertEqual(updated, {reservation_key(2, "Bulbasaur"): [123]})
        self.assertIn(reservation_key(1, "Eevee"), reservations)

    def test_formats_reservation_embed_and_paginates_at_twenty_pokemon(self) -> None:
        embeds = format_reservation_embeds("Jade", ["eevee", "pikachu"])
        self.assertEqual(embeds[0].title, "Pokémon reserved by Jade")
        self.assertEqual(embeds[0].description, "Eevee\nPikachu")

        paged_embeds = format_reservation_embeds(
            "Jade",
            [f"pokemon{i}" for i in range(45)],
        )
        self.assertEqual(
            [len(embed.description.splitlines()) for embed in paged_embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in paged_embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

    def test_formats_all_server_reserves_one_pokemon_user_per_line(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456, 123],
            reservation_key(1, "Scatterbug"): [789],
            reservation_key(2, "Eevee"): [123],
        }

        embeds = format_server_reservation_embeds(reservations, 1)

        self.assertEqual(len(embeds), 1)
        self.assertEqual(
            embeds[0].description,
            "pikachu <@123>\npikachu <@456>\nscatterbug <@789>",
        )

    def test_server_list_labels_all_forms_reservations(self) -> None:
        embeds = format_server_reservation_embeds(
            {all_forms_reservation_key(1, "Arceus"): [123]},
            1,
        )

        self.assertEqual(embeds[0].description, "all forms of arceus <@123>")

    def test_formats_empty_server_reserve_list(self) -> None:
        embeds = format_server_reservation_embeds(
            {reservation_key(2, "Eevee"): [123]},
            1,
        )

        self.assertEqual(
            embeds[0].description,
            "There are no Pokémon reservations in this server.",
        )

    def test_formats_reserve_search_with_all_users_for_pokemon(self) -> None:
        reservations = {
            reservation_key(1, "Scatterbug"): [456, 123, 456],
            reservation_key(2, "Scatterbug"): [789],
        }

        embeds = format_pokemon_reserver_embeds(reservations, 1, "scatterbug")

        self.assertEqual(embeds[0].title, "Reserve search: scatterbug")
        self.assertEqual(
            embeds[0].description,
            "scatterbug <@123>\nscatterbug <@456>",
        )

    def test_search_includes_reservations_for_all_forms(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        embeds = format_pokemon_reserver_embeds(
            reservations,
            1,
            "Arceus (Fire)",
        )

        self.assertEqual(
            embeds[0].description,
            "Arceus (Fire) <@123>",
        )

    def test_all_forms_search_lists_each_reserved_form_and_reservers(self) -> None:
        reservations = {
            reservation_key(1, "Arceus"): [456],
            reservation_key(1, "Arceus (Fire)"): [789],
            reservation_key(1, "Arceus-Water"): [987],
            all_forms_reservation_key(1, "Arceus"): [123],
            reservation_key(1, "Pikachu"): [321],
            reservation_key(2, "Arceus (Grass)"): [654],
        }

        embeds = format_all_forms_reservation_embeds(
            reservations,
            1,
            "Arceus",
        )

        self.assertEqual(
            "\n".join(embed.description for embed in embeds),
            "normal arceus <@123>\nnormal arceus <@456>\n"
            "fire arceus <@123>\nfire arceus <@789>\n"
            "water arceus <@123>\nwater arceus <@987>\n"
            "electric arceus <@123>\ngrass arceus <@123>\n"
            "ice arceus <@123>\nfighting arceus <@123>\n"
            "poison arceus <@123>\nground arceus <@123>\n"
            "flying arceus <@123>\npsychic arceus <@123>\n"
            "bug arceus <@123>\nrock arceus <@123>\n"
            "ghost arceus <@123>\ndragon arceus <@123>\n"
            "dark arceus <@123>\nsteel arceus <@123>\nfairy arceus <@123>",
        )

    def test_all_forms_search_lists_each_arceus_type_for_all_forms_reserver(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {all_forms_reservation_key(1, "Arceus"): [123]},
            1,
            "Arceus",
        )

        lines = "\n".join(embed.description for embed in embeds).splitlines()
        self.assertEqual(len(lines), 18)
        self.assertEqual(lines[0], "normal arceus <@123>")
        self.assertEqual(lines[-1], "fairy arceus <@123>")

    def test_all_forms_search_lists_only_exactly_reserved_types_without_wildcard(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {
                reservation_key(1, "Arceus (Ghost)"): [123],
                reservation_key(1, "Arceus-Fairy"): [456],
            },
            1,
            "Arceus",
        )

        rows = "\n".join(embed.description for embed in embeds).splitlines()
        self.assertEqual(len(rows), 18)
        self.assertIn("ghost arceus <@123>", rows)
        self.assertIn("fairy arceus <@456>", rows)
        self.assertIn("normal arceus", rows)

    def test_all_forms_search_lists_pichu_forms_and_reserver(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {all_forms_reservation_key(1, "Pichu"): [123]},
            1,
            "Pichu",
        )

        self.assertEqual(
            embeds[0].description,
            "pichu <@123>\nspiky-eared pichu <@123>",
        )

    def test_all_forms_search_excludes_regional_forms(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {
                all_forms_reservation_key(1, "Raichu"): [123],
                reservation_key(1, "Raichu-Alola"): [456],
            },
            1,
            "Raichu",
        )

        description = "\n".join(embed.description for embed in embeds)
        self.assertIn("raichu <@123>", description)
        self.assertIn("mega-x raichu <@123>", description)
        self.assertNotIn("alola", description)


    def test_all_forms_search_paginates_form_entries_at_twenty(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [1, 2]}

        embeds = format_all_forms_reservation_embeds(
            reservations,
            1,
            "Arceus",
        )

        self.assertEqual(
            [len(embed.description.splitlines()) for embed in embeds],
            [20, 16],
        )
        self.assertEqual(
            [embed.footer.text for embed in embeds],
            ["Page 1 of 2", "Page 2 of 2"],
        )

    def test_loads_non_regional_form_catalog(self) -> None:
        forms = load_pokemon_forms(Path(__file__).with_name("pokemon_forms.json"))

        self.assertEqual(forms["pichu"][1]["display_name"], "spiky-eared pichu")
        self.assertFalse(
            any("alola" in form["identifier"] for form in forms["raichu"])
        )

    def test_formats_reserve_search_when_pokemon_is_not_reserved(self) -> None:
        embeds = format_pokemon_reserver_embeds({}, 1, "scatterbug")

        self.assertEqual(
            embeds[0].description,
            "No one has scatterbug reserved.",
        )

    def test_paginates_reserve_search_at_twenty_users(self) -> None:
        reservations = {
            reservation_key(1, "scatterbug"): list(range(45))
        }

        embeds = format_pokemon_reserver_embeds(
            reservations,
            1,
            "scatterbug",
        )

        self.assertEqual(
            [len(embed.description.splitlines()) for embed in embeds],
            [20, 20, 5],
        )

    def test_paginates_server_reserve_list_at_twenty_entries(self) -> None:
        reservations = {
            reservation_key(1, f"pokemon{i}"): [i]
            for i in range(45)
        }

        embeds = format_server_reservation_embeds(reservations, 1)

        self.assertEqual(
            [len(embed.description.splitlines()) for embed in embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

    def test_reserve_page_view_enables_arrows_for_available_pages(self) -> None:
        embeds = [
            discord.Embed(description="Page 1"),
            discord.Embed(description="Page 2"),
        ]
        view = ReservationPagesView(embeds, guild_id=1)

        buttons = {button.custom_id: button for button in view.children}
        self.assertTrue(buttons["reserve_pages:previous"].disabled)
        self.assertFalse(buttons["reserve_pages:next"].disabled)

        view.current_page = 1
        view.update_buttons()
        self.assertFalse(buttons["reserve_pages:previous"].disabled)
        self.assertTrue(buttons["reserve_pages:next"].disabled)


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
