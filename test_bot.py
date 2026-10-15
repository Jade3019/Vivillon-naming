import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import discord

from bot import (
    add_shinyhunter,
    add_collection_pokemon,
    all_forms_reservation_key,
    clear_guild_reservations,
    clear_user_collection,
    collection_pokemon_for_user,
    collection_user_ids_for_pokemon,
    split_collection_add_names,
    format_catch_command,
    format_guess,
    format_all_forms_reservation_embeds,
    format_collection_embeds,
    format_collection_add_confirmation,
    format_pokemon_reserver_embeds,
    format_remove_confirmation,
    format_reservation_embeds,
    format_server_reservation_embeds,
    format_shinyhunt_confirmation,
    format_type_spawn_embed,
    format_pc_catch_code_block,
    format_custom_type_spawn_reply,
    fire_companion_icon_filename_for_pokemon,
    is_normal_icon_pokemon,
    normal_companion_icon_filename_for_pokemon,
    is_electric_icon_pokemon,
    electric_companion_icon_filename_for_pokemon,
    is_fire_icon_pokemon,
    is_water_icon_pokemon,
    is_grass_icon_pokemon,
    is_ice_icon_pokemon,
    water_companion_icon_filename_for_pokemon,
    format_spawn_mention_lines,
    format_spawn_reply,
    format_shinyhunt_status,
    is_valid_pokemon_name,
    is_missingno_name,
    is_single_type_fire_pokemon,
    is_single_type_normal_pokemon,
    is_single_type_water_pokemon,
    is_single_type_ice_pokemon,
    is_single_type_electric_pokemon,
    type_icon_filename_for_pokemon,
    load_pokemon_forms,
    load_reservations,
    parse_reserve_add_command,
    parse_reserve_remove_command,
    parse_collection_add_command,
    parse_shinyhunt_command,
    ReservationPagesView,
    remove_reservation,
    remove_reservations,
    remove_collection_pokemon,
    reservation_key,
    reservation_key_for_command,
    reserved_pokemon_for_user,
    reserved_user_ids_for_pokemon,
    save_reservations,
    shinyhunt_pokemon_for_user,
    shinyhunter_user_ids_for_pokemon,
    pokemon_matches_all_forms_reservation,
    POKETWO_COMMAND_BOT_ID,
)


class FireSpawnFormattingTests(unittest.TestCase):
    def test_marks_pure_fire_pokemon_but_not_dual_type_pokemon(self) -> None:
        self.assertTrue(is_single_type_fire_pokemon("Vulpix"))
        self.assertTrue(is_single_type_fire_pokemon("Growlithe"))
        self.assertFalse(is_single_type_fire_pokemon("Charizard"))
        self.assertFalse(is_single_type_fire_pokemon("Rotom Heat"))

    def test_type_spawn_embed_shows_guess_icon_and_catch_command(self) -> None:
        embed = format_type_spawn_embed("Glaceon", 87.5, 789, "ice_type.png")

        self.assertEqual(embed.author.name, "Glaceon: 87.50%")
        self.assertEqual(embed.author.icon_url, "attachment://ice_type.png")
        self.assertEqual(embed.description, "`<@789> c glaceon`")

    def test_pc_catch_copy_uses_fenced_block_and_spawned_pokemon_name(self) -> None:
        self.assertEqual(
            format_pc_catch_code_block("Pikachu"),
            "```\n<@716390085896962058> c pikachu\n```",
        )

    def test_fire_spawns_use_inline_custom_emoji_without_embed(self) -> None:
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Vulpix", 87.5, 789, [123], include_fire=True
            ),
            "Reserved: <@123>\n"
            "## <:fire:1560301436074729532> Vulpix: 87.50%\n"
            "`<@789> c vulpix`",
        )
        self.assertTrue(is_fire_icon_pokemon("Vulpix"))
        self.assertTrue(is_fire_icon_pokemon("Litleo"))
        self.assertFalse(is_fire_icon_pokemon("Charizard"))
        self.assertIsNone(fire_companion_icon_filename_for_pokemon("Vulpix"))
        self.assertTrue(is_water_icon_pokemon("Magikarp"))
        self.assertTrue(is_water_icon_pokemon("Dewgong"))
        self.assertFalse(is_water_icon_pokemon("Gyarados"))
        self.assertTrue(is_normal_icon_pokemon("Eevee"))
        self.assertTrue(is_normal_icon_pokemon("Bibarel"))
        self.assertFalse(is_normal_icon_pokemon("Pidgeot"))
        self.assertTrue(is_electric_icon_pokemon("Pikachu"))
        self.assertTrue(is_electric_icon_pokemon("Heliolisk"))
        self.assertFalse(is_electric_icon_pokemon("Magnemite"))
        self.assertTrue(is_grass_icon_pokemon("Treecko"))
        self.assertTrue(is_grass_icon_pokemon("Scovillain"))
        self.assertFalse(is_grass_icon_pokemon("Bulbasaur"))
        self.assertTrue(is_single_type_ice_pokemon("Glaceon"))
        self.assertTrue(is_ice_icon_pokemon("Glaceon"))
        self.assertTrue(is_ice_icon_pokemon("Darmanitan-Galar-Zen"))
        self.assertTrue(is_ice_icon_pokemon("Lapras"))
        self.assertTrue(is_ice_icon_pokemon("Arctozolt"))
        self.assertFalse(is_ice_icon_pokemon("Charizard"))
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Eevee", 87.5, 789, include_normal=True
            ),
            "## <:Normal:1560305235279482930> Eevee: 87.50%\n"
            "`<@789> c eevee`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Volcanion", 87.5, 789, include_fire=True, include_water=True
            ),
            "## <:water:1560303864094130357> "
            "<:fire:1560301436074729532> Volcanion: 87.50%\n"
            "`<@789> c volcanion`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Litleo", 87.5, 789, include_fire=True, include_normal=True
            ),
            "## <:fire:1560301436074729532> "
            "<:Normal:1560305235279482930> Litleo: 87.50%\n"
            "`<@789> c litleo`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Bibarel", 87.5, 789, include_water=True, include_normal=True
            ),
            "## <:Normal:1560305235279482930> "
            "<:water:1560303864094130357> Bibarel: 87.50%\n"
            "`<@789> c bibarel`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Heliolisk", 87.5, 789, include_electric=True, include_normal=True
            ),
            "## <:Electric:1560306053164572732> "
            "<:Normal:1560305235279482930> Heliolisk: 87.50%\n"
            "`<@789> c heliolisk`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Heat", 87.5, 789, include_fire=True, include_electric=True
            ),
            "## <:fire:1560301436074729532> "
            "<:Electric:1560306053164572732> Rotom Heat: 87.50%\n"
            "`<@789> c rotom heat`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Scovillain", 87.5, 789, include_grass=True, include_fire=True
            ),
            "## <:grass:1560307079896502282> "
            "<:fire:1560301436074729532> Scovillain: 87.50%\n"
            "`<@789> c scovillain`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lotad", 87.5, 789, include_grass=True, include_water=True
            ),
            "## <:grass:1560307079896502282> "
            "<:water:1560303864094130357> Lotad: 87.50%\n"
            "`<@789> c lotad`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Smoliv", 87.5, 789, include_grass=True, include_normal=True
            ),
            "## <:grass:1560307079896502282> "
            "<:Normal:1560305235279482930> Smoliv: 87.50%\n"
            "`<@789> c smoliv`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Mow", 87.5, 789, include_grass=True, include_electric=True
            ),
            "## <:grass:1560307079896502282> "
            "<:Electric:1560306053164572732> Rotom Mow: 87.50%\n"
            "`<@789> c rotom mow`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Glaceon", 87.5, 789, include_ice=True
            ),
            "## <:Ice:1560307867200782386> Glaceon: 87.50%\n"
            "`<@789> c glaceon`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Darmanitan-Galar-Zen",
                87.5,
                789,
                include_fire=True,
                include_ice=True,
            ),
            "## <:Ice:1560307867200782386> "
            "<:fire:1560301436074729532> Darmanitan-Galar-Zen: 87.50%\n"
            "`<@789> c darmanitan-galar-zen`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lapras", 87.5, 789, include_water=True, include_ice=True
            ),
            "## <:Ice:1560307867200782386> "
            "<:water:1560303864094130357> Lapras: 87.50%\n"
            "`<@789> c lapras`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Arctozolt", 87.5, 789, include_electric=True, include_ice=True
            ),
            "## <:Ice:1560307867200782386> "
            "<:Electric:1560306053164572732> Arctozolt: 87.50%\n"
            "`<@789> c arctozolt`",
        )
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertTrue(is_ice_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                format_custom_type_spawn_reply(
                    "Test Pokemon",
                    87.5,
                    789,
                    include_normal=True,
                    include_ice=True,
                ),
                "## <:Normal:1560305235279482930> "
                "<:Ice:1560307867200782386> Test Pokemon: 87.50%\n"
                "`<@789> c test pokemon`",
            )
        self.assertIsNone(fire_companion_icon_filename_for_pokemon("Volcanion"))
        self.assertIsNone(water_companion_icon_filename_for_pokemon("Volcanion"))
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Litleo"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Rotom Heat"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Scovillain"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Darmanitan-Galar-Zen"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Bibarel"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Lanturn"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Ogerpon Wellspring Mask"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Lapras"),
            None,
        )
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertTrue(is_normal_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                normal_companion_icon_filename_for_pokemon("Test Pokemon"),
                None,
            )
        self.assertEqual(
            electric_companion_icon_filename_for_pokemon("Voltorb-Hisui"),
            None,
        )
        self.assertEqual(
            electric_companion_icon_filename_for_pokemon("Arctozolt"),
            None,
        )

    def test_marks_only_single_type_normal_pokemon(self) -> None:
        self.assertTrue(is_single_type_normal_pokemon("Eevee"))
        self.assertFalse(is_single_type_normal_pokemon("Pidgeot"))
        self.assertFalse(is_single_type_normal_pokemon("Girafarig"))

    def test_uses_both_icons_only_for_fire_and_normal_dual_type(self) -> None:
        self.assertIsNone(type_icon_filename_for_pokemon("Eevee"))
        self.assertEqual(type_icon_filename_for_pokemon("Squirtle"), "water_type.png")
        self.assertIsNone(type_icon_filename_for_pokemon("Bibarel"))
        for name in ("Heliolisk", "Helioptile"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        for name in ("Lanturn", "Chinchou", "Rotom Wash"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Pikachu"))
        self.assertIsNone(type_icon_filename_for_pokemon("Decidueye"))
        for name in ("Lotad", "Lombre", "Ludicolo", "Ogerpon Wellspring Mask"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Bulbasaur"))
        for name in ("Smoliv", "Dolliv", "Arboliva", "Deerling", "Sawsbuck"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        for name in ("Voltorb-Hisui", "Electrode-Hisui", "Rotom Mow"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Snivy"))
        self.assertIsNone(type_icon_filename_for_pokemon("Treecko"))
        self.assertEqual(type_icon_filename_for_pokemon("Glaceon"), "ice_type.png")
        self.assertEqual(type_icon_filename_for_pokemon("Cetitan"), "ice_type.png")
        for name in ("Dewgong", "Cloyster", "Lapras", "Arctovish"):
            self.assertEqual(
                type_icon_filename_for_pokemon(name),
                "ice_water_type_icons.png",
            )
        self.assertIsNone(type_icon_filename_for_pokemon("Darmanitan-Galar-Zen"))
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))
        with patch("bot.ICE_AND_ELECTRIC_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))
        self.assertIsNone(type_icon_filename_for_pokemon("Venusaur"))
        self.assertTrue(is_single_type_electric_pokemon("Jolteon"))
        self.assertFalse(is_single_type_electric_pokemon("Raichu-alola"))
        self.assertFalse(is_single_type_electric_pokemon("Magnemite"))
        self.assertTrue(is_single_type_water_pokemon("Magikarp"))
        self.assertFalse(is_single_type_water_pokemon("Gyarados"))
        self.assertFalse(is_single_type_water_pokemon("Lapras"))
        self.assertIsNone(type_icon_filename_for_pokemon("Charizard"))
        with patch(
            "bot.FIRE_AND_NORMAL_TYPE_ALIASES",
            frozenset({"test pokemon"}),
        ):
            self.assertTrue(is_fire_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                fire_companion_icon_filename_for_pokemon("Test Pokemon"),
                None,
            )
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))


class GuessFormatTests(unittest.TestCase):
    def test_recognizes_missingno_aliases(self) -> None:
        for name in ("Missingno.", "missingno", "???"):
            with self.subTest(name=name):
                self.assertTrue(is_missingno_name(name))
        self.assertFalse(is_missingno_name("Pikachu"))

    def test_formats_one_guess_without_a_label(self) -> None:
        self.assertEqual(format_guess("Pikachu", 85), "Pikachu: 85.00%")
        self.assertEqual(format_guess("Absol", 56.86), "Absol: 56.86%")

    def test_formats_plain_poketwo_catch_command(self) -> None:
        self.assertEqual(
            format_catch_command(POKETWO_COMMAND_BOT_ID, "Pikachu"),
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
            "Collection: \n"
            "`<@789> c absol`",
        )

    def test_reservations_override_shinyhunters_in_spawn_reply(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [999], [123, 456]),
            "Absol: 95.00%\n"
            "Reserved: <@999>\n"
            "`<@789> c absol`",
        )

    def test_collection_ping_is_included_with_empty_shinyhunt_line(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [], [123]),
            "Pikachu: 95.00%\n"
            "Shinyhunt: \n"
            "Collection: <@123>\n"
            "`<@789> c pikachu`",
        )

    def test_collection_and_shinyhunt_ping_multiple_members(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [123], [456, 789]),
            "Pikachu: 95.00%\n"
            "Shinyhunt: <@123>\n"
            "Collection: <@456>, <@789>\n"
            "`<@789> c pikachu`",
        )

    def test_reservation_overrides_shinyhunt_and_collection_pings(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [111], [123], [456]),
            "Pikachu: 95.00%\n"
            "Reserved: <@111>\n"
            "`<@789> c pikachu`",
        )


class ReservationPersistenceTests(unittest.TestCase):
    def test_parses_and_deduplicates_multiple_collection_pokemon(self) -> None:
        self.assertEqual(
            parse_collection_add_command("v!cl add Pikachu, eevee, pikachu"),
            ["Pikachu", "eevee"],
        )
        self.assertIsNone(parse_collection_add_command("v!cl add pikachu,,eevee"))
        self.assertIsNone(parse_collection_add_command("v!cl add pikachu!"))

    def test_collection_add_keeps_multiple_members_and_guilds_separate(self) -> None:
        collections = add_collection_pokemon({}, 1, ["Pikachu", "Eevee"], 123)
        collections = add_collection_pokemon(collections, 1, ["Pikachu"], 456)
        collections = add_collection_pokemon(collections, 2, ["Pikachu"], 789)

        self.assertEqual(
            collections[reservation_key(1, "pikachu")],
            [123, 456],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 1, "Pikachu"),
            [123, 456],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 2, "Pikachu"),
            [789],
        )
        self.assertEqual(
            collection_pokemon_for_user(collections, 1, 123),
            ["eevee", "pikachu"],
        )

    def test_collection_add_detects_existing_names_for_the_same_user(self) -> None:
        collections = add_collection_pokemon({}, 1, ["Pikachu"], 123)

        new_names, already_added = split_collection_add_names(
            collections,
            1,
            ["pikachu", "Eevee"],
            123,
        )

        self.assertEqual(new_names, ["Eevee"])
        self.assertEqual(already_added, ["pikachu"])
        self.assertEqual(
            format_collection_add_confirmation(new_names, already_added),
            "Added Eevee to your collection. Pikachu already added to your collection.",
        )

    def test_collection_add_duplicate_response_for_single_pokemon(self) -> None:
        self.assertEqual(
            format_collection_add_confirmation([], ["pikachu"]),
            "Pikachu already added to your collection.",
        )

    def test_collection_remove_only_removes_requesting_user(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, removed, missing = remove_collection_pokemon(
            collections,
            1,
            ["pikachu", "eevee"],
            123,
        )

        self.assertEqual(removed, ["pikachu", "eevee"])
        self.assertEqual(missing, [])
        self.assertEqual(updated, {
            reservation_key(1, "Pikachu"): [456],
            reservation_key(2, "Pikachu"): [123],
        })
        self.assertEqual(collections[reservation_key(1, "Pikachu")], [123, 456])

    def test_collection_remove_reports_names_not_in_users_collection(self) -> None:
        updated, removed, missing = remove_collection_pokemon(
            {reservation_key(1, "Pikachu"): [456]},
            1,
            ["Pikachu", "Eevee"],
            123,
        )

        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})
        self.assertEqual(removed, [])
        self.assertEqual(missing, ["Pikachu", "Eevee"])

    def test_clear_user_collection_preserves_other_users_and_guilds(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_user_collection(collections, 1, 123)

        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(2, "Pikachu"): [123],
            },
        )

    def test_formats_collection_embed_and_paginates_at_twenty(self) -> None:
        embeds = format_collection_embeds(["eevee", "pikachu"])
        self.assertEqual(embeds[0].title, "Your Pokémon Collection")
        self.assertEqual(embeds[0].description, "eevee\npikachu")

        paged_embeds = format_collection_embeds(
            [f"pokemon{i}" for i in range(45)]
        )
        self.assertEqual(
            [len(embed.description.splitlines()) for embed in paged_embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in paged_embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

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

        rows = set("\n".join(embed.description for embed in embeds).splitlines())
        self.assertEqual(
            rows,
            {
                "normal arceus <@123>",
                "normal arceus <@456>",
                "fire arceus <@123>",
                "fire arceus <@789>",
                "water arceus <@123>",
                "water arceus <@987>",
                "electric arceus <@123>",
                "grass arceus <@123>",
                "ice arceus <@123>",
                "fighting arceus <@123>",
                "poison arceus <@123>",
                "ground arceus <@123>",
                "flying arceus <@123>",
                "psychic arceus <@123>",
                "bug arceus <@123>",
                "rock arceus <@123>",
                "ghost arceus <@123>",
                "dragon arceus <@123>",
                "dark arceus <@123>",
                "steel arceus <@123>",
                "fairy arceus <@123>",
            },
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
        self.assertEqual(forms["arceus"][0]["identifier"], "arceus-normal")
        self.assertEqual(forms["arceus"][0]["display_name"], "normal arceus")
        self.assertFalse(
            any(form["identifier"] == "arceus-unknown" for form in forms["arceus"])
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
