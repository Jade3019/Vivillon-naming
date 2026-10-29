import image_match
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

import discord
from PIL import Image, ImageOps

from bot import (
    add_shinyhunter,
    clear_shinyhunter,
    add_reservations_bulk,
    build_grab_lines,
    grab_display_name,
    grab_reserve_pairs,
    parse_grab_entries,
    exchange_reservations,
    parse_exchange_list,
    add_collection_pokemon,
    migrate_legacy_all_keys,
    all_forms_reservation_key,
    clear_guild_reservations,
    clear_guild_collection,
    clear_guild_shinyhunts,
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
    format_pc_catch_embed,
    catch_card_files,
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
    format_starboard_embed,
    is_valid_pokemon_name,
    is_image_test_command,
    is_missingno_name,
    is_normal_starboard_pokemon,
    is_single_type_fire_pokemon,
    is_single_type_normal_pokemon,
    is_single_type_water_pokemon,
    is_single_type_ice_pokemon,
    is_single_type_electric_pokemon,
    type_icon_filename_for_pokemon,
    load_pokemon_forms,
    load_server_settings,
    load_starboard_settings,
    load_reservations,
    _org_api_port_from_environment,
    is_known_pokemon_name,
    parse_reserve_add_command,
    parse_reserve_remove_command,
    parse_collection_add_command,
    parse_shinyhunt_command,
    parse_shinyhunt_remove_command,
    ReservationPagesView,
    NamingSettingsView,
    StarboardSettingsView,
    parse_catch_details,
    starboard_art_url,
    starboard_category,
    ServerSettingsView,
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
    remove_shinyhunter,
    pokemon_matches_all_forms_reservation,
    poketwo_incense_action,
    POKETWO_COMMAND_BOT_ID,
    SERVER_ID,
    reservation_key,
    Config,
    NamingBot,
    AFKSettingsView,
    format_profile_iv_record,
    load_afk_settings,
    load_type_pings,
    load_profile_data,
    ProfileIvRecord,
    PROFILE_EMOJI_URLS,
    save_profile_data,
    save_type_pings,
    type_ping_user_ids_for_pokemon,
    TYPE_PING_TYPES,
    TypePingView,
    render_profile_image,
    ProfileView,
    ProfileEditView,
    count_qualifying_sentences,
    ChatEventSession,
    EventMenuView,
    parse_chat_event_duration,
)


class ConfigTests(unittest.TestCase):
    def load_config(self, **environment: str) -> Config:
        variables = {
            "DISCORD_TOKEN": "test-token",
            "POKETWO_BOT_ID": "12345",
            "CODESPACES": "true",
            "CODESPACE_NAME": "bookish-space-xylophone-gx67456vpq4whwpqx",
            **environment,
        }
        with patch.dict("os.environ", variables, clear=True):
            return Config.from_environment()

    def test_rejects_unauthorized_codespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "designated Codespace"):
            self.load_config(CODESPACE_NAME="another-codespace")

    def test_rejects_non_codespace_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "designated Codespace"):
            self.load_config(CODESPACES="false")

    def test_allows_external_host_when_opted_in(self) -> None:
        config = self.load_config(CODESPACES="false", ALLOW_EXTERNAL_HOST="true")
        self.assertEqual(config.poketwo_bot_id, 12345)

    def test_openai_key_is_optional(self) -> None:
        self.assertIsNone(self.load_config().openai_api_key)
        self.assertEqual(
            self.load_config(OPENAI_API_KEY=" abc ").openai_api_key, "abc"
        )

    def test_configures_concurrent_vision_request_limit(self) -> None:
        config = self.load_config(MAX_CONCURRENT_VISION_REQUESTS="8")

        self.assertEqual(config.max_concurrent_vision_requests, 8)


    def test_defaults_to_200_concurrent_vision_requests(self) -> None:
        self.assertEqual(
            self.load_config().max_concurrent_vision_requests,
            200,
        )

    def test_allows_200_concurrent_vision_requests(self) -> None:
        config = self.load_config(MAX_CONCURRENT_VISION_REQUESTS="200")

        self.assertEqual(config.max_concurrent_vision_requests, 200)

    def test_rejects_invalid_vision_request_limit(self) -> None:
        for value in ("0", "-1", "201", "many"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load_config(MAX_CONCURRENT_VISION_REQUESTS=value)

    def test_org_api_port_prefers_explicit_then_host_then_generic_port(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ORG_API_PORT": "1111",
                "SERVER_PORT": "2222",
                "PORT": "3333",
            },
            clear=True,
        ):
            self.assertEqual(_org_api_port_from_environment(), 1111)
        with patch.dict(
            "os.environ", {"SERVER_PORT": "2222", "PORT": "3333"}, clear=True
        ):
            self.assertEqual(_org_api_port_from_environment(), 2222)
        with patch.dict("os.environ", {"PORT": "3333"}, clear=True):
            self.assertEqual(_org_api_port_from_environment(), 3333)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_org_api_port_from_environment(), 8080)

    def test_org_api_port_reports_invalid_environment_value(self) -> None:
        with patch.dict("os.environ", {"SERVER_PORT": "invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "SERVER_PORT"):
                _org_api_port_from_environment()


class RecognitionValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_inconclusive_local_match_uses_vision_prediction(self) -> None:
        import bot

        image_bytes = b"spawn image"
        matcher = Mock(entries=["Finizen"])
        client = Mock()
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(image_bytes, "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Palafin", 97.0)),
            ) as request_prediction,
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=client,
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Palafin", 97.0))
        request_prediction.assert_awaited_once()

    async def test_unverified_vision_vivillon_prediction_is_rejected(self) -> None:
        import bot

        image_bytes = b"spawn image"
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(image_bytes, "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Vivillon", 99.0)),
            ),
            patch("bot.vivillon_form_by_pattern", return_value=None),
        ):
            with self.assertRaisesRegex(
                bot.NoMatchError, "was not image-verified"
            ):
                await bot.recognize_pokemon(
                    "https://example.test/spawn.png",
                    client=Mock(),
                    http=Mock(),
                    model="test-model",
                )


class ApiStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ConfigTests().load_config()
        self.bot = NamingBot(self.config)

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    def test_recognizes_only_poketwo_incense_commands(self) -> None:
        self.assertEqual(
            poketwo_incense_action(
                f"<@{self.config.poketwo_bot_id}> buy incense",
                self.config.poketwo_bot_id,
            ),
            "start",
        )
        self.assertEqual(
            poketwo_incense_action(
                f"<@!{self.config.poketwo_bot_id}> stopincense",
                self.config.poketwo_bot_id,
            ),
            "stop",
        )
        self.assertEqual(
            poketwo_incense_action("p!buy incense", self.config.poketwo_bot_id),
            "start",
        )
        self.assertEqual(
            poketwo_incense_action("p!stopincense", self.config.poketwo_bot_id),
            "stop",
        )
        self.assertIsNone(
            poketwo_incense_action(
                "<@999> buy incense",
                self.config.poketwo_bot_id,
            )
        )
        self.assertIsNone(
            poketwo_incense_action(
                f"<@{self.config.poketwo_bot_id}> buy shard 50",
                self.config.poketwo_bot_id,
            )
        )

    async def test_tracks_incense_commands_across_guilds_and_persists_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.incense_path = Path(directory) / "incenses.json"
            message = Mock()
            message.author.bot = False
            message.author.id = 100
            message.guild.id = SERVER_ID + 1
            message.guild.name = "Other server"
            message.channel.id = 200
            message.channel.name = "incense-room"
            message.content = f"<@{self.config.poketwo_bot_id}> buy incense"

            await self.bot.on_message(message)

            self.assertIn("200", self.bot.active_incenses)
            active = self.bot.current_active_incenses()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["guild"], "Other server")
            self.assertEqual(active[0]["channel"], "incense-room")
            self.assertTrue(self.bot.incense_path.is_file())

            second_server_message = Mock()
            second_server_message.author.bot = False
            second_server_message.author.id = 101
            second_server_message.guild.id = SERVER_ID + 2
            second_server_message.guild.name = "Another server"
            second_server_message.channel.id = 201
            second_server_message.channel.name = "another-incense-room"
            second_server_message.content = "p!buy incense"
            await self.bot.on_message(second_server_message)
            self.assertEqual(len(self.bot.current_active_incenses()), 2)

            message.content = f"<@{self.config.poketwo_bot_id}> stopincense"
            await self.bot.on_message(message)
            active = self.bot.current_active_incenses()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["guild"], "Another server")

    async def test_api_status_counts_incenses_across_all_servers(self) -> None:
        now = int(time.time())
        self.bot.active_incenses = {
            "200": {
                "guild": "First server",
                "channel": "incense-room",
                "guild_id": SERVER_ID,
                "expires_at": now + 3600,
            },
            "201": {
                "guild": "Second server",
                "channel": "incense-room",
                "guild_id": SERVER_ID + 1,
                "expires_at": now + 3600,
            },
        }
        message = Mock()
        message.reply = AsyncMock()

        await self.bot.handle_api_status(message)

        embed = message.reply.await_args.kwargs["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Active Incense"], "2")

    async def test_api_status_tracks_poketwo_incense_spawn_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.incense_path = Path(directory) / "incenses.json"
            message = Mock()
            message.author.bot = True
            message.author.id = self.config.poketwo_bot_id
            message.guild.id = SERVER_ID + 100
            message.guild.name = "Other server"
            message.channel.id = 500
            message.channel.name = "incense-room"
            message.channel.guild = message.guild
            message.content = ""
            message.embeds = [
                discord.Embed(
                    description="Spawns Remaining: 42"
                )
            ]
            message.embeds[0].set_footer(text="Incense: Active")

            await self.bot.on_message(message)

            status_message = Mock()
            status_message.reply = AsyncMock()
            await self.bot.handle_api_status(status_message)
            embed = status_message.reply.await_args.kwargs["embed"]
            fields = {field.name: field.value for field in embed.fields}
            self.assertEqual(fields["Active Incense"], "1")

            inactive_embed = discord.Embed(description="Spawns Remaining: 0")
            inactive_embed.set_footer(text="Incense: Inactive")
            message.embeds = [inactive_embed]
            await self.bot.on_message_edit(Mock(), message)
            status_message.reply.reset_mock()
            await self.bot.handle_api_status(status_message)
            embed = status_message.reply.await_args.kwargs["embed"]
            fields = {field.name: field.value for field in embed.fields}
            self.assertEqual(fields["Active Incense"], "0")

    async def test_naming_settings_toggle_persists_per_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.server_settings_path = Path(directory) / "settings.json"
            self.bot.server_settings = {}

            self.assertEqual(
                self.bot.naming_settings_for_guild(SERVER_ID),
                {"enabled": True, "assisted": True, "pings": False},
            )
            updated = self.bot.toggle_naming_setting(SERVER_ID, "enabled")
            self.assertFalse(updated["enabled"])
            self.assertTrue(updated["assisted"])
            updated = self.bot.toggle_naming_setting(SERVER_ID, "assisted")
            self.assertFalse(updated["assisted"])
            self.assertTrue(
                self.bot.naming_settings_for_guild(SERVER_ID + 1)["enabled"]
            )
            self.assertEqual(
                load_server_settings(self.bot.server_settings_path)[str(SERVER_ID)],
                {"enabled": False, "assisted": False, "pings": False},
            )

    async def test_naming_settings_button_requires_permission_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.server_settings_path = Path(directory) / "settings.json"
            self.bot.server_settings = {}
            view = NamingSettingsView(self.bot, SERVER_ID)
            sections = [
                child
                for child in view.children[0].children
                if isinstance(child, discord.ui.Section)
            ]
            enabled_button = sections[0].accessory
            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.guild_permissions.manage_guild = False
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            await enabled_button.callback(interaction)

            interaction.response.send_message.assert_awaited_once()
            interaction.response.edit_message.assert_not_awaited()
            self.assertTrue(
                self.bot.naming_settings_for_guild(SERVER_ID)["enabled"]
            )
            interaction.user.guild_permissions.manage_guild = True

            await enabled_button.callback(interaction)

            self.assertFalse(
                self.bot.naming_settings_for_guild(SERVER_ID)["enabled"]
            )
            interaction.response.edit_message.assert_awaited_once()
            updated_view = interaction.response.edit_message.await_args.kwargs["view"]
            updated_sections = [
                child
                for child in updated_view.children[0].children
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(updated_sections[0].accessory.label, "Off")

            mode_button = updated_sections[1].accessory
            await mode_button.callback(interaction)
            self.assertFalse(
                self.bot.naming_settings_for_guild(SERVER_ID)["assisted"]
            )
            updated_view = interaction.response.edit_message.await_args.kwargs["view"]
            updated_sections = [
                child
                for child in updated_view.children[0].children
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(updated_sections[1].accessory.label, "Name only")

    async def test_spawn_settings_disable_names_filter_pings_and_remove_copy_text(
        self,
    ) -> None:
        self.bot.image_http = Mock(close=AsyncMock())

        def spawn_message(message_id: int) -> Mock:
            message = Mock()
            message.id = message_id
            message.guild.id = SERVER_ID
            message.channel.id = 400 + message_id
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()
            return message

        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": False,
            "assisted": True,
            "pings": False,
        }
        disabled_message = spawn_message(701)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(disabled_message)
        disabled_message.reply.assert_not_awaited()
        recognize.assert_not_awaited()

        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "pings": True,
        }
        unpinged_message = spawn_message(702)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(unpinged_message)
        unpinged_message.reply.assert_not_awaited()
        recognize.assert_not_awaited()

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.collection_path = Path(directory.name) / "collections.json"
        self.bot.collections = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        save_reservations(self.bot.collection_path, self.bot.collections)
        pinged_message = spawn_message(703)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(pinged_message)

        recognize.assert_awaited_once()
        pinged_message.reply.assert_awaited_once()
        content = pinged_message.reply.await_args.args[0]
        self.assertIn("<@123>", content)
        self.assertIn("Pikachu", content)
        self.assertNotIn("c pikachu", content)
        self.assertIsNone(pinged_message.reply.await_args.kwargs["embed"])

        self.bot.server_settings[str(SERVER_ID)]["pings"] = False
        name_only_message = spawn_message(704)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Charizard", 99.0)),
        ):
            await self.bot.handle_spawn(name_only_message)
        name_only_message.reply.assert_awaited_once()
        name_only_content = name_only_message.reply.await_args.args[0]
        self.assertIn("Charizard", name_only_content)
        self.assertNotIn("Copy Here", name_only_content)
        self.assertNotIn("c charizard", name_only_content)
        self.assertIsNone(name_only_message.reply.await_args.kwargs["embed"])

    async def test_afk_preferences_filter_shinyhunt_and_collection_pings(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "pings": False,
        }
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Absol"): [123]}
        self.bot.collections = {reservation_key(SERVER_ID, "Absol"): [456]}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.shinyhunt_path = Path(directory.name) / "shinyhunts.json"
        self.bot.collection_path = Path(directory.name) / "collections.json"
        save_reservations(self.bot.shinyhunt_path, self.bot.shinyhunters)
        save_reservations(self.bot.collection_path, self.bot.collections)
        self.bot.afk_settings = {
            f"{SERVER_ID}:123": {"shinyhunt": False, "collection": True},
            f"{SERVER_ID}:456": {"shinyhunt": True, "collection": True},
        }
        message = Mock()
        message.id = 705
        message.guild.id = SERVER_ID
        message.channel.id = 1205
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(message)

        message.reply.assert_awaited_once()
        content = message.reply.await_args.args[0]
        self.assertIn("Collection: <@456>", content)
        self.assertNotIn("Shinyhunt:", content)

        self.bot.server_settings[str(SERVER_ID)]["pings"] = True
        self.bot.afk_settings[f"{SERVER_ID}:456"]["collection"] = False
        muted_message = Mock()
        muted_message.id = 706
        muted_message.guild.id = SERVER_ID
        muted_message.channel.id = 1206
        muted_message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        muted_message.embeds = []
        muted_message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(muted_message)

        muted_message.reply.assert_not_awaited()

    async def test_spawns_reload_saved_collection_and_shinyhunt_clear_state(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.collections = {reservation_key(SERVER_ID, "Absol"): [123]}
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Absol"): [456]}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.collection_path = Path(directory.name) / "collections.json"
        self.bot.shinyhunt_path = Path(directory.name) / "shinyhunts.json"
        save_reservations(self.bot.collection_path, {})
        save_reservations(self.bot.shinyhunt_path, {})

        message = Mock()
        message.id = 707
        message.guild.id = SERVER_ID
        message.channel.id = 1207
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(message)

        message.reply.assert_awaited_once()
        content = message.reply.await_args.args[0]
        self.assertNotIn("Collection:", content)
        self.assertNotIn("Shinyhunt:", content)
        self.assertEqual(self.bot.collections, {})
        self.assertEqual(self.bot.shinyhunters, {})

    async def test_api_status_reports_response_metrics_and_load(self) -> None:
        self.bot.pokemon_named_count = 12
        now = time.monotonic()
        self.bot.recognition_durations.extend(
            [(now - 2, 0.02, 0.4), (now - 1, 0.03, 1.2)]
        )
        message = Mock()
        message.reply = AsyncMock()

        await self.bot.handle_api_status(message)

        embed = message.reply.await_args.kwargs["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(len(embed.fields), 15)
        self.assertEqual(
            [field.name for field in embed.fields[:6]],
            [
                "Activity",
                "Active Incense",
                "Store (latest)",
                "Store (avg)",
                "JSON load",
                "CSV load",
            ],
        )
        self.assertTrue(all(field.inline for field in embed.fields))
        self.assertEqual(fields["Pokémons Named"], "12")
        self.assertEqual(fields["Inference Fastest"], "20 ms")
        self.assertEqual(fields["Inference Slowest"], "30 ms")
        self.assertEqual(fields["Inference Avg"], "25 ms")
        self.assertEqual(fields["Inference Latest"], "30 ms")
        self.assertEqual(fields["Response Fastest"], "400 ms")
        self.assertEqual(fields["Response Slowest"], "1200 ms")
        self.assertEqual(fields["Response Avg"], "800 ms")
        self.assertEqual(fields["Response Latest"], "1200 ms")
        self.assertEqual(fields["CSV load"], "Not used")
        self.assertIn("Window: 5 min rolling", embed.footer.text)

    async def test_api_command_is_routed_in_the_configured_server(self) -> None:
        message = Mock()
        message.author.bot = False
        message.channel.guild.id = SERVER_ID
        message.content = "v!api"
        message.embeds = []
        message.attachments = []
        message.guild = Mock()
        self.bot.handle_api_status = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_api_status.assert_awaited_once_with(message)

    async def test_event_command_shows_event_menu(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.content = "v!event"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        self.assertIsInstance(
            message.reply.await_args.kwargs["view"],
            EventMenuView,
        )

    async def test_chat_event_counts_only_qualifying_messages_for_participants(self) -> None:
        channel = Mock()
        channel.id = 456
        session = ChatEventSession(host_id=123, channel=channel)
        session.participant_ids = {123}
        session.sentence_counts = {123: 0}
        session.collecting = True
        self.bot.chat_events[channel.id] = session

        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.id = channel.id
        message.content = "This message has four words. Too short."

        self.bot.track_chat_event_message(message)

        self.assertEqual(session.sentence_counts[123], 1)

    def test_chat_event_sentence_count_requires_four_words_per_sentence(self) -> None:
        self.assertEqual(
            count_qualifying_sentences(
                "This has four words. Too short. Here are exactly four."
            ),
            2,
        )
        self.assertEqual(count_qualifying_sentences("one two three"), 0)

    def test_chat_event_accepts_custom_minutes_and_hours(self) -> None:
        self.assertEqual(parse_chat_event_duration("7 minutes"), (420, "7 minutes"))
        self.assertEqual(parse_chat_event_duration("2 hours"), (7200, "2 hours"))
        self.assertEqual(parse_chat_event_duration("1.5h"), (5400, "1.5 hours"))
        self.assertEqual(parse_chat_event_duration("3"), (180, "3 minutes"))
        for invalid in ("0 minutes", "-2 hours", "seven minutes", "2 days"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(parse_chat_event_duration(invalid))

    async def test_chat_event_requires_at_least_two_signups(self) -> None:
        channel = Mock()
        channel.id = 456
        channel.send = AsyncMock()
        session = ChatEventSession(host_id=123, channel=channel)
        session.participant_ids = {123}
        session.message = Mock()
        session.message.reactions = []
        session.message.clear_reactions = AsyncMock()
        self.bot.chat_events[channel.id] = session

        with patch("bot.asyncio.sleep", new=AsyncMock()):
            await self.bot.run_chat_event(session)

        channel.send.assert_awaited_once()
        self.assertIn("at least 2 participants", channel.send.await_args.args[0])
        self.assertNotIn(channel.id, self.bot.chat_events)

    async def test_settings_command_sends_server_settings_layout(self) -> None:
        message = Mock()
        message.author.bot = False
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!settings"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        reply_kwargs = message.reply.await_args.kwargs
        self.assertFalse(reply_kwargs["mention_author"])
        view = reply_kwargs["view"]
        self.assertIsInstance(view, ServerSettingsView)
        self.assertTrue(view.has_components_v2())
        sections = [
            child
            for child in view.children[0].children
            if isinstance(child, discord.ui.Section)
        ]
        self.assertEqual(len(sections), 4)
        self.assertEqual(
            [section.accessory.label for section in sections],
            ["Open"] * 4,
        )
        self.assertEqual(
            [section.accessory.custom_id for section in sections],
            [
                "server_settings:open:naming",
                "server_settings:open:roles",
                "server_settings:open:starboard",
                "server_settings:open:appearance",
            ],
        )
        interaction = Mock()
        interaction.guild_id = SERVER_ID
        interaction.response.edit_message = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await sections[0].accessory.callback(interaction)

        naming_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(naming_view, NamingSettingsView)

    async def test_afk_command_sends_personal_toggle_layout(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!afk"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        view = message.reply.await_args.kwargs["view"]
        self.assertIsInstance(view, AFKSettingsView)
        self.assertTrue(view.has_components_v2())
        sections = [
            child
            for child in view.children[0].children
            if isinstance(child, discord.ui.Section)
        ]
        self.assertEqual(
            [section.accessory.label for section in sections],
            ["On", "On"],
        )
        self.assertEqual(
            [section.accessory.custom_id for section in sections],
            ["afk_settings:shinyhunt", "afk_settings:collection"],
        )

    async def test_afk_toggle_persists_for_user_and_requires_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.afk_settings_path = Path(directory) / "afk_settings.json"
            self.bot.afk_settings = {}
            view = AFKSettingsView(self.bot, SERVER_ID, 123)
            sections = [
                child
                for child in view.children[0].children
                if isinstance(child, discord.ui.Section)
            ]
            collection_button = sections[1].accessory
            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.id = 456
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            await collection_button.callback(interaction)

            interaction.response.send_message.assert_awaited_once()
            interaction.response.edit_message.assert_not_awaited()
            self.assertTrue(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["collection"]
            )

            interaction.user.id = 123
            await collection_button.callback(interaction)

            self.assertFalse(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["collection"]
            )
            self.assertTrue(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["shinyhunt"]
            )
            self.assertEqual(
                load_afk_settings(self.bot.afk_settings_path),
                {f"{SERVER_ID}:123": {"shinyhunt": True, "collection": False}},
            )
            updated_view = interaction.response.edit_message.await_args.kwargs["view"]
            updated_sections = [
                child
                for child in updated_view.children[0].children
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(updated_sections[1].accessory.label, "Off")


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())
        self.directory = tempfile.TemporaryDirectory()
        self.bot.profile_data_path = Path(self.directory.name) / "profile_data.json"
        (
            self.bot.profiles,
            self.bot.profile_stats,
            self.bot.profile_records,
            self.bot.profile_seen_catch_ids,
        ) = load_profile_data(self.bot.profile_data_path)

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self.directory.cleanup()

    async def test_profile_command_sends_image_and_edit_button(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.author.display_name = "Trainer"
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!profile"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock(return_value=Mock())

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        kwargs = message.reply.await_args.kwargs
        self.assertFalse(kwargs["mention_author"])
        self.assertNotIn("embed", kwargs)
        self.assertEqual(kwargs["file"].filename, "profile.png")
        self.assertIsInstance(kwargs["view"], ProfileView)
        self.assertEqual(kwargs["view"].children[0].label, "Edit")

    async def test_profile_command_can_target_a_mentioned_member(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!profile <@!456>"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock(return_value=Mock())
        self.bot.profile_stats[f"{SERVER_ID}:456"] = {
            "total": 25,
            "shiny": 2,
            "low_iv": 3,
            "high_iv": 4,
            "gmax": 5,
            "missingno": 6,
        }

        await self.bot.on_message(message)

        view = message.reply.await_args.kwargs["view"]
        self.assertEqual(view.user_id, 456)
        self.assertEqual(view.guild_id, SERVER_ID)

    async def test_edit_button_opens_four_personalized_dropdowns(self) -> None:
        profile_view = ProfileView(self.bot, 123, SERVER_ID)
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.send_message = AsyncMock()

        await profile_view.children[0].callback(interaction)

        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertFalse(kwargs["ephemeral"])
        editor = kwargs["view"]
        self.assertIsInstance(editor, ProfileEditView)
        self.assertEqual(
            [select.placeholder for select in editor.children],
            ["Text color", "Background", "Middle background", "Frame"],
        )
        self.assertEqual(
            [option.label for option in editor.children[1].options],
            ["Default"],
        )
        self.assertEqual(
            [option.label for option in editor.children[2].options],
            ["White", "Cosmog"],
        )
        self.assertEqual(
            [option.label for option in editor.children[3].options],
            ["No frame"],
        )

    async def test_dropdown_change_persists_and_refreshes_the_profile(self) -> None:
        profile_view = ProfileView(self.bot, 123, SERVER_ID)
        profile_view.message = Mock()
        profile_view.message.edit = AsyncMock()
        editor = ProfileEditView(profile_view)
        text_color_select = editor.children[0]
        text_color_select._values = ["pink"]
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.defer = AsyncMock()
        interaction.message.edit = AsyncMock()
        interaction.followup.send = AsyncMock()

        await text_color_select.callback(interaction)

        self.assertEqual(self.bot.profile_settings_for_user(123)["text_color"], "pink")
        self.assertEqual(
            load_profile_data(self.bot.profile_data_path)[0]["123"]["text_color"],
            "pink",
        )
        profile_view.message.edit.assert_awaited_once()
        interaction.message.edit.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

    async def test_caught_pokemon_count_is_persistent_and_deduplicated(self) -> None:
        message = Mock()
        message.id = 987654
        message.guild = Mock()
        message.guild.id = SERVER_ID
        message.content = (
            "Congratulations <@123>! You caught a Level 20 Bagon! (50.54%)!"
        )
        message.embeds = []
        message.author.bot = True
        self.bot.track_profile_catch(message)
        self.bot.track_profile_catch(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            1,
        )
        _, profile_stats, profile_records, seen_catch_ids = load_profile_data(
            self.bot.profile_data_path
        )
        self.assertEqual(profile_stats[f"{SERVER_ID}:123"]["total"], 1)
        highest_iv = profile_records[f"{SERVER_ID}:123"]["highest_iv"]
        self.assertEqual((highest_iv.pokemon, highest_iv.iv), ("Bagon", 50.54))
        self.assertEqual(seen_catch_ids, [message.id])

    async def test_each_application_webhook_catch_increments_total(self) -> None:
        self.bot.handle_catch_starboard = AsyncMock()
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.daycare.handle_message = AsyncMock(return_value=False)

        catches = (
            (987655, "Gliscor", "", False),
            (987656, "Unknownmon", "˚", True),
        )
        for message_id, pokemon, suffix, display_name_mention in catches:
            message = Mock()
            message.id = message_id
            message.author.bot = False
            message.author.id = 456
            message.guild.id = SERVER_ID
            message.channel.guild.id = SERVER_ID
            catcher = "@Trainer" if display_name_mention else "<@123>"
            message.content = (
                f"Congratulations {catcher}{suffix}! You caught a Level 36 {pokemon} "
                "♂ (53.23%)!"
            )
            message.mentions = [Mock(id=123)] if display_name_mention else []
            message.embeds = []
            message.webhook_id = 789
            message.application_id = 789
            await self.bot.on_message(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            2,
        )
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (records["highest_iv"].pokemon, records["highest_iv"].iv),
            ("Gliscor", 53.23),
        )
        self.assertEqual(
            (records["lowest_iv"].pokemon, records["lowest_iv"].iv),
            ("Gliscor", 53.23),
        )

    def test_iv_records_track_extrema_and_enrich_edited_catches(self) -> None:
        message = Mock()
        message.id = 987660
        message.guild.id = SERVER_ID
        message.embeds = []
        message.content = (
            "Congratulations <@123>! You caught a Level 40 Rolycoly!"
        )
        self.bot.track_profile_catch(message)

        message.content = (
            "Congratulations <@123>! You caught a Level 40 "
            "Rolycoly![:male:](70.43%)!"
        )
        self.bot.track_profile_catch(message)
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (
                records["highest_iv"].level,
                records["highest_iv"].pokemon,
                records["highest_iv"].gender,
                records["highest_iv"].iv,
            ),
            ("40", "Rolycoly", "Male", 70.43),
        )
        self.assertEqual(
            (
                records["lowest_iv"].level,
                records["lowest_iv"].pokemon,
                records["lowest_iv"].gender,
                records["lowest_iv"].iv,
            ),
            ("40", "Rolycoly", "Male", 70.43),
        )

        catches = (
            (987661, "Bramblin", 56.45, "female"),
            (987662, "Pikachu", 75.0, "male"),
            (987663, "Eevee", 50.0, "female"),
        )
        for message_id, pokemon, iv, gender in catches:
            message = Mock()
            message.id = message_id
            message.guild.id = SERVER_ID
            message.embeds = []
            message.content = (
                f"Congratulations <@123>! You caught a Level 25 "
                f"{pokemon}![:{gender}:]({iv:.2f}%)!"
            )
            self.bot.track_profile_catch(message)

        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (
                records["highest_iv"].level,
                records["highest_iv"].pokemon,
                records["highest_iv"].gender,
                records["highest_iv"].iv,
            ),
            ("25", "Pikachu", "Male", 75.0),
        )
        self.assertEqual(
            (
                records["lowest_iv"].level,
                records["lowest_iv"].pokemon,
                records["lowest_iv"].gender,
                records["lowest_iv"].iv,
            ),
            ("25", "Eevee", "Female", 50.0),
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            4,
        )

    def test_total_uses_catch_announcement_prefix_not_spawn_or_species_parse(
        self,
    ) -> None:
        catch = Mock()
        catch.id = 987657
        catch.guild.id = SERVER_ID
        catch.author.bot = True
        catch.content = "Congratulations <@123>˚! You caught a Level 7 Unknownmon!"
        catch.embeds = []
        spawn = Mock()
        spawn.id = 987658
        spawn.guild.id = SERVER_ID
        spawn.author.bot = True
        spawn.content = "A wild Treecko has appeared!"
        spawn.embeds = []

        self.bot.track_profile_catch(catch)
        self.bot.track_profile_catch(spawn)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            1,
        )

    def test_catch_categories_are_counted_only_in_the_profile_server(self) -> None:
        catch_messages = (
            (
                1001,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 20 Bagon! "
                "(95.00%)! These colors seem unusual... ✨\n"
                "Woah! It seems that this Pokémon has the Gigantamax Factor...",
            ),
            (
                1002,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 4 Eevee! (9.99%)!",
            ),
            (
                1003,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 1 Missingno!",
            ),
            (
                1005,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 10 Pikachu! "
                "(45.00%)! These colors seem unusual... ✨",
            ),
            (
                1004,
                SERVER_ID + 1,
                "Congratulations <@123>! You caught a Level 20 Bagon! (99.00%)!",
            ),
        )
        for message_id, guild_id, content in catch_messages:
            with self.subTest(message_id=message_id):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.content = content
                message.embeds = []
                self.bot.track_profile_catch(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123),
            {
                "total": 4,
                "shiny": 2,
                "low_iv": 1,
                "high_iv": 1,
                "gmax": 1,
                "missingno": 1,
            },
        )
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            {
                name: (record.level, record.pokemon, record.gender, record.iv)
                for name, record in records.items()
            },
            {
                "highest_iv": ("20", "Gigantamax Bagon", None, 95.0),
                "lowest_iv": ("4", "Eevee", None, 9.99),
                "highest_shiny_iv": ("20", "Gigantamax Bagon", None, 95.0),
                "lowest_shiny_iv": ("10", "Pikachu", None, 45.0),
            },
        )
        _, _, profile_records, _ = load_profile_data(self.bot.profile_data_path)
        self.assertEqual(profile_records[f"{SERVER_ID}:123"], records)

    def test_profile_card_keeps_default_backgrounds(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        image = Image.open(render_profile_image(settings, stats))
        self.assertEqual(image.size, (1400, 825))
        self.assertEqual(image.getpixel((700, 400)), (255, 255, 255))
        self.assertEqual(image.getpixel((100, 800)), (41, 42, 47))
        self.assertEqual(image.getpixel((1300, 800)), (41, 42, 47))
        self.assertNotEqual(image.getpixel((81, 375)), (41, 42, 47))
        self.assertEqual(image.getpixel((380, 375)), (41, 42, 47))

    def test_profile_card_uses_selected_cosmog_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["middle_background"] = "cosmog"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(Path(__file__).with_name("middle background") / "Cosmog.png") as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_iv_records_on_the_right(self) -> None:
        self.assertEqual(
            format_profile_iv_record(
                ProfileIvRecord(
                    pokemon="Rolycoly",
                    iv=70.43,
                    level="40",
                    gender="Male",
                )
            ),
            ("Level 40 Rolycoly", "Male | 70.43%"),
        )
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        blank = Image.open(render_profile_image(settings, stats))
        with_records = Image.open(
            render_profile_image(
                settings,
                stats,
                records={
                    "highest_iv": ProfileIvRecord(
                        pokemon="Gliscor",
                        iv=98.25,
                        level="36",
                        gender="Male",
                    )
                },
            )
        )

        self.assertNotEqual(
            blank.crop((950, 200, 1400, 800)).tobytes(),
            with_records.crop((950, 200, 1400, 800)).tobytes(),
        )

    def test_profile_stat_emojis_use_the_requested_symbols(self) -> None:
        self.assertEqual(
            {
                name: PROFILE_EMOJI_URLS[name].rsplit("/", 1)[-1]
                for name in ("low_iv", "high_iv", "shiny")
            },
            {
                "low_iv": "1f4c9.png",
                "high_iv": "1f4c8.png",
                "shiny": "2728.png",
            },
        )

    def test_removed_background_choices_migrate_to_defaults(self) -> None:
        save_profile_data(
            self.bot.profile_data_path,
            {
                "123": {
                    "text_color": "white",
                    "background": "rose",
                    "middle_background": "soft_pink",
                    "frame": "none",
                }
            },
            {},
            {},
            [],
        )

        profiles, _, _, _ = load_profile_data(self.bot.profile_data_path)

        self.assertEqual(profiles["123"]["background"], "default")
        self.assertEqual(profiles["123"]["middle_background"], "white")


class ShinyhuntCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_clear_removes_and_persists_all_of_the_users_hunts(self) -> None:
        self.bot.shinyhunters = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [123],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!sh clear"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.shinyhunt_path = Path(directory) / "shinyhunts.json"

            await self.bot.handle_shinyhunt_command(message)

            self.assertEqual(
                load_reservations(self.bot.shinyhunt_path),
                {
                    reservation_key(SERVER_ID, "Pikachu"): [456],
                    reservation_key(999, "Pikachu"): [123],
                },
            )

        message.reply.assert_awaited_once_with(
            "Your shinyhunt has been cleared.",
            mention_author=False,
        )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                self.bot.shinyhunters,
                SERVER_ID,
                "Pikachu",
            ),
            [456],
        )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                self.bot.shinyhunters,
                SERVER_ID,
                "Eevee",
            ),
            [],
        )

    async def test_clear_all_requires_server_administrator(self) -> None:
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        message = Mock()
        message.content = "v!sh clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = False
        message.reply = AsyncMock()

        await self.bot.handle_shinyhunt_command(message)

        message.reply.assert_awaited_once_with(
            "Only server administrators can clear everyone's shinyhunts.",
            mention_author=False,
        )
        self.assertEqual(
            self.bot.shinyhunters,
            {reservation_key(SERVER_ID, "Pikachu"): [123]},
        )

    async def test_admin_clear_all_confirms_then_clears_only_current_guild(
        self,
    ) -> None:
        self.bot.shinyhunters = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [789],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!sh clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = True
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.shinyhunt_path = Path(directory) / "shinyhunts.json"

            await self.bot.handle_shinyhunt_command(message)

            message.reply.assert_awaited_once()
            view = message.reply.await_args.kwargs["view"]
            interaction = Mock()
            interaction.user.id = 123
            interaction.user.guild_permissions.administrator = True
            interaction.guild_id = SERVER_ID
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()
            confirm_button = next(
                button for button in view.children if button.label == "Yes"
            )
            await confirm_button.callback(interaction)

            expected = {reservation_key(999, "Pikachu"): [123]}
            self.assertEqual(self.bot.shinyhunters, expected)
            self.assertEqual(
                load_reservations(self.bot.shinyhunt_path),
                expected,
            )
            interaction.response.edit_message.assert_awaited_once_with(
                content="Everyone's shinyhunts in this server have been cleared.",
                view=None,
            )


class CollectionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_clear_all_requires_server_administrator(self) -> None:
        self.bot.collections = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        message = Mock()
        message.content = "v!cl clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = False
        message.reply = AsyncMock()

        await self.bot.handle_collection_command(message)

        message.reply.assert_awaited_once_with(
            "Only server administrators can clear everyone's collection.",
            mention_author=False,
        )
        self.assertEqual(
            self.bot.collections,
            {reservation_key(SERVER_ID, "Pikachu"): [123]},
        )

    async def test_admin_clear_all_confirms_then_clears_only_current_guild(self) -> None:
        self.bot.collections = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [789],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!cl clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = True
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.collection_path = Path(directory) / "collections.json"

            await self.bot.handle_collection_command(message)

            message.reply.assert_awaited_once()
            self.assertIn("view", message.reply.await_args.kwargs)
            self.assertEqual(
                self.bot.collections,
                {
                    reservation_key(SERVER_ID, "Pikachu"): [123, 456],
                    reservation_key(SERVER_ID, "Eevee"): [789],
                    reservation_key(999, "Pikachu"): [123],
                },
            )

            view = message.reply.await_args.kwargs["view"]
            interaction = Mock()
            interaction.user.id = 123
            interaction.user.guild_permissions.administrator = True
            interaction.guild_id = SERVER_ID
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            confirm_button = next(
                button for button in view.children if button.label == "Yes"
            )
            await confirm_button.callback(interaction)

            self.assertEqual(
                load_reservations(self.bot.collection_path),
                {reservation_key(999, "Pikachu"): [123]},
            )
            self.assertEqual(
                self.bot.collections,
                {reservation_key(999, "Pikachu"): [123]},
            )
            interaction.response.edit_message.assert_awaited_once_with(
                content="Everyone's Pokémon collection in this server has been cleared.",
                view=None,
            )


class TypePingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    def test_selected_types_match_either_pokemon_type(self) -> None:
        type_pings = {
            f"{SERVER_ID}:123": ["normal"],
            f"{SERVER_ID}:456": ["fire"],
            f"{SERVER_ID}:789": ["normal", "fire"],
            f"{SERVER_ID + 1}:999": ["normal"],
        }

        self.assertEqual(
            type_ping_user_ids_for_pokemon(
                type_pings,
                SERVER_ID,
                ["fire", "normal"],
            ),
            [123, 456, 789],
        )

    async def test_type_ping_commands_edit_and_persist_multiple_selections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            for content in ("v!tp", "v!typeping"):
                message = Mock()
                message.author.bot = False
                message.author.id = 123
                message.guild.id = SERVER_ID
                message.channel.guild.id = SERVER_ID
                message.content = content
                message.embeds = []
                message.attachments = []
                message.reply = AsyncMock()

                await self.bot.on_message(message)

                message.reply.assert_awaited_once()
                view = message.reply.await_args.kwargs["view"]
                self.assertIsInstance(view, TypePingView)
                self.assertEqual(
                    message.reply.await_args.kwargs["embed"].title,
                    "Type Pings",
                )
                type_select = next(
                    child
                    for child in view.children
                    if isinstance(child, discord.ui.Select)
                )
                self.assertEqual(len(type_select.options), len(TYPE_PING_TYPES))
                self.assertEqual(type_select.max_values, len(TYPE_PING_TYPES))
                self.assertEqual(type_select.min_values, 0)
                self.assertFalse(any(option.default for option in type_select.options))

            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.id = 123
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()
            interaction.followup.send = AsyncMock()
            view = message.reply.await_args.kwargs["view"]
            type_select = next(
                child
                for child in view.children
                if isinstance(child, discord.ui.Select)
            )
            type_select._values = ["normal", "fire"]

            await type_select.callback(interaction)

            self.assertEqual(
                self.bot.type_pings,
                {f"{SERVER_ID}:123": ["fire", "normal"]},
            )
            self.assertEqual(
                load_type_pings(self.bot.type_ping_path),
                {f"{SERVER_ID}:123": ["fire", "normal"]},
            )
            updated_view = interaction.response.edit_message.await_args.kwargs["view"]
            updated_select = next(
                child
                for child in updated_view.children
                if isinstance(child, discord.ui.Select)
            )
            self.assertEqual(
                {option.value for option in updated_select.options if option.default},
                {"normal", "fire"},
            )
            interaction.followup.send.assert_awaited_with(
                "Type pings updated for Fire and Normal.",
                ephemeral=True,
            )

            all_on = next(
                child
                for child in updated_view.children
                if isinstance(child, discord.ui.Button) and child.label == "All On"
            )
            await all_on.callback(interaction)
            self.assertEqual(
                self.bot.type_pings[f"{SERVER_ID}:123"],
                list(TYPE_PING_TYPES),
            )
            all_on_view = interaction.response.edit_message.await_args.kwargs["view"]
            all_on_select = next(
                child
                for child in all_on_view.children
                if isinstance(child, discord.ui.Select)
            )
            self.assertTrue(all(option.default for option in all_on_select.options))

            all_off = next(
                child
                for child in all_on_view.children
                if isinstance(child, discord.ui.Button) and child.label == "All Off"
            )
            await all_off.callback(interaction)
            self.assertEqual(self.bot.type_pings, {})
            self.assertEqual(load_type_pings(self.bot.type_ping_path), {})

    async def test_type_pings_wake_and_match_dual_type_spawns_in_pings_mode(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "pings": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            self.bot.type_pings = {
                f"{SERVER_ID}:123": ["normal"],
                f"{SERVER_ID}:456": ["fire"],
            }
            save_type_pings(self.bot.type_ping_path, self.bot.type_pings)
            self.bot.collections = {
                reservation_key(SERVER_ID, "Pyroar"): [123]
            }
            self.bot.collection_path = Path(directory) / "collections.json"
            save_reservations(self.bot.collection_path, self.bot.collections)

            message = Mock()
            message.id = 708
            message.guild.id = SERVER_ID
            message.channel.id = 1208
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Pyroar", 99.0)),
            ) as recognize:
                await self.bot.handle_spawn(message)

            recognize.assert_awaited_once()
            message.reply.assert_awaited_once()
            content = message.reply.await_args.args[0]
            self.assertIn("Pyroar: 99.00%", content.splitlines()[0])
            self.assertIn("Collection: <@123>", content)
            self.assertIn("Typeping: <@123>, <@456>", content)
            self.assertLess(content.index("Pyroar:"), content.index("Collection:"))
            self.assertEqual(content.count("<@123>"), 2)


class CatchStarboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    def test_parses_shiny_catch_details_and_only_shows_explicit_chain(self) -> None:
        details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Bagon ♀! "
            "(50.54%)! These colors seem unusual... ✨ Shiny streak reset. (554)"
        )

        self.assertIsNotNone(details)
        self.assertEqual(details.user_id, 123)
        self.assertEqual(details.pokemon, "Bagon")
        self.assertEqual(details.level, "20")
        self.assertEqual(details.iv, "50.54%")
        self.assertEqual(details.gender, "Female")
        self.assertTrue(details.shiny)
        self.assertEqual(details.chain, 554)
        self.assertEqual(starboard_category(details), "shiny")
        shiny_embed = format_starboard_embed(
            details,
            "shiny",
            discord.utils.utcnow(),
        )
        self.assertEqual(
            shiny_embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/shiny/371.png",
        )
        self.assertIsNone(shiny_embed.image.url)
        self.assertEqual(shiny_embed.fields, [])
        self.assertIn("**Caught by:** <@123>", shiny_embed.description)
        self.assertIn("**Pokémon:** Bagon", shiny_embed.description)
        self.assertIn("**Level:** 20", shiny_embed.description)
        self.assertIn("**IV:** 50.54%", shiny_embed.description)
        self.assertIn("**Gender:** Female", shiny_embed.description)
        self.assertIn("**Shiny chain:** 554", shiny_embed.description)

        no_chain = parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Bagon! "
            "(50.54%)! These colors seem unusual... ✨"
        )
        self.assertIsNotNone(no_chain)
        self.assertIsNone(no_chain.chain)
        no_chain_embed = format_starboard_embed(
            no_chain,
            "shiny",
            discord.utils.utcnow(),
        )
        self.assertNotIn("**Shiny chain:**", no_chain_embed.description)

    def test_normal_starboard_matches_requested_forms_and_all_form_families(
        self,
    ) -> None:
        for pokemon_name in (
            "Alolan Ninetales",
            "Galarian Zen Darmanitan",
            "Perrserker",
            "Hisuian Zorua",
            "Combat Breed Tauros",
            "Fighting Arceus",
            "Douse Drive Genesect",
            "Wellspring-Mask Ogerpon",
            "Rapid Strike Urshifu",
            "Zenith Marshadow",
            "Partner Pikachu",
            "Zygarde Cell",
            "Gigantamax Urshifu",
        ):
            with self.subTest(pokemon_name=pokemon_name):
                self.assertTrue(is_normal_starboard_pokemon(pokemon_name))
        self.assertFalse(is_normal_starboard_pokemon("Pikachu"))

    def test_normal_starboard_uses_naming_thumbnails_for_forms(self) -> None:
        examples = (("Flying Silvally", "773"),)
        for pokemon, sprite_id in examples:
            with self.subTest(pokemon=pokemon):
                details = parse_catch_details(
                    f"Congratulations <@123>! You caught a Level 22 {pokemon}! "
                    "(51.08%)!"
                )

                self.assertIsNotNone(details)
                self.assertEqual(
                    starboard_art_url(details),
                    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                    f"sprites/pokemon/other/home/{sprite_id}.png",
                )
                embed = format_starboard_embed(
                    details,
                    "normal_pokemon",
                    discord.utils.utcnow(),
                )
                self.assertEqual(
                    embed.thumbnail.url,
                    "attachment://flyingsilvally.png",
                )

        zygarde_details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 22 Zygarde Cell! "
            "(51.08%)!"
        )
        self.assertIsNotNone(zygarde_details)
        self.assertEqual(
            starboard_art_url(zygarde_details),
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/10118.png",
        )
        zygarde_embed = format_starboard_embed(
            zygarde_details,
            "normal_pokemon",
            discord.utils.utcnow(),
        )
        self.assertEqual(
            zygarde_embed.thumbnail.url,
            "attachment://zygardecell.png",
        )

    def test_categorizes_high_iv_low_iv_missingno_and_gigantamax(self) -> None:
        examples = (
            (
                "Congratulations <@123>! You caught a Level 37 Pichu! (95.16%)!",
                "high_iv",
                "Pichu",
            ),
            (
                "Congratulations <@123>! You caught a Level 18 Archer! (8.60%)!",
                "low_iv",
                "Archer",
            ),
            (
                "Congratulations <@123>! You caught a Level ??? ???! (???)!",
                "missingno",
                "Missingno",
            ),
            (
                "Congratulations <@123>! You caught a ???! (???)!",
                "missingno",
                "Missingno",
            ),
            (
                "Congratulations <@123>! You caught a Level 30 Charizard ♀! "
                "(50.54%)! Gigantamax Factor",
                "gigantamax",
                "Gigantamax Charizard",
            ),
        )
        for text, expected_category, expected_name in examples:
            with self.subTest(expected_category=expected_category):
                details = parse_catch_details(text)
                self.assertIsNotNone(details)
                self.assertEqual(details.pokemon, expected_name)
                self.assertEqual(starboard_category(details), expected_category)
                if expected_category == "missingno":
                    missingno_embed = format_starboard_embed(
                        details,
                        expected_category,
                        discord.utils.utcnow(),
                    )
                    self.assertEqual(missingno_embed.fields, [])
                    self.assertIn("**Level:** ???", missingno_embed.description)
                    self.assertIn("**IV:** ???", missingno_embed.description)
                if expected_category == "gigantamax":
                    gigantamax_embed = format_starboard_embed(
                        details,
                        expected_category,
                        discord.utils.utcnow(),
                    )
                    self.assertEqual(gigantamax_embed.fields, [])
                    self.assertIn(
                        f"**Pokémon:** {expected_name}",
                        gigantamax_embed.description,
                    )
                    self.assertIn("**Level:** 30", gigantamax_embed.description)

    def test_starboard_embed_has_requested_fields_timestamp_and_artwork(self) -> None:
        details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 37 Pincurchin! (95.16%)!"
        )
        self.assertIsNotNone(details)
        caught_at = discord.utils.utcnow()
        embed = format_starboard_embed(
            details,
            "high_iv",
            caught_at,
        )

        self.assertEqual(embed.fields, [])
        self.assertIn("**Caught by:** <@123>", embed.description)
        self.assertIn("**Pokémon:** Pincurchin", embed.description)
        self.assertIn("**IV:** 95.16%", embed.description)
        self.assertIn("**Level:** 37", embed.description)
        self.assertEqual(embed.timestamp, caught_at)
        self.assertEqual(
            embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/871.png",
        )
        self.assertIsNone(embed.image.url)
        self.assertEqual(embed.footer.text, "Caught at")
        shiny_details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Grookey! "
            "(50.54%)! These colors seem unusual... ✨"
        )
        self.assertEqual(
            starboard_art_url(shiny_details),
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/shiny/810.png",
        )
        self.assertEqual(
            starboard_art_url(shiny_details, use_3d_shiny_model=True),
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/grookey.gif",
        )
        articuno_details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 50 Articuno! "
            "These colors seem unusual... ✨"
        )
        self.assertEqual(
            starboard_art_url(articuno_details, use_3d_shiny_model=True),
            "https://projectpokemon.org/images/shiny-sprite/articuno.gif",
        )
        wiglett_details = parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Wiglett! "
            "These colors seem unusual... ✨"
        )
        self.assertEqual(
            starboard_art_url(wiglett_details, use_3d_shiny_model=True),
            "https://play.pokemonshowdown.com/sprites/ani-shiny/wiglett.gif",
        )
        shiny_model_embed = format_starboard_embed(
            shiny_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
            test_preview=True,
        )
        self.assertEqual(
            shiny_model_embed.thumbnail.url,
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/grookey.gif",
        )
        self.assertIsNone(shiny_model_embed.image.url)
        self.assertIn("PKParaiso", shiny_model_embed.footer.text)

        actual_shiny_embed = format_starboard_embed(
            shiny_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
        )
        self.assertEqual(actual_shiny_embed.footer.text, "Caught at")

        wiglett_embed = format_starboard_embed(
            wiglett_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
        )
        self.assertEqual(
            wiglett_embed.thumbnail.url,
            "https://play.pokemonshowdown.com/sprites/ani-shiny/wiglett.gif",
        )
        self.assertEqual(wiglett_embed.footer.text, "Caught at")

        galarian_articuno = parse_catch_details(
            "Congratulations <@123>! You caught a Level 50 Galarian Articuno! "
            "These colors seem unusual... ✨"
        )
        self.assertEqual(
            starboard_art_url(
                galarian_articuno,
                use_3d_shiny_model=True,
            ),
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/articuno-galar.gif",
        )

    async def test_starboard_channels_save_per_server_and_render_settings_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}

            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)

            self.assertEqual(
                load_starboard_settings(self.bot.starboard_settings_path)[
                    str(SERVER_ID)
                ],
                {
                    "normal_channel": 101,
                    "shiny_channel": 202,
                    "normal_pokemon_channel": 303,
                    "shiny_base_name": None,
                    "shiny_count": 0,
                },
            )
            view = StarboardSettingsView(self.bot, SERVER_ID)
            self.assertTrue(view.has_components_v2())
            component_ids = {
                item.custom_id
                for item in view.walk_children()
                if getattr(item, "custom_id", None)
            }
            self.assertIn("server_settings:starboard:select:normal", component_ids)
            self.assertIn("server_settings:starboard:select:shiny", component_ids)
            self.assertIn(
                "server_settings:starboard:select:normal_pokemon",
                component_ids,
            )

    async def test_shiny_catch_posts_to_both_boards_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            main_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            channels = {101: main_channel, 202: shiny_channel}
            self.bot.get_channel = Mock(side_effect=channels.get)
            message = Mock()
            message.id = 456
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 20 Bagon ♀! "
                "(50.54%)! These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.on_message(message)
            await self.bot.on_message(message)

            main_channel.send.assert_awaited_once()
            shiny_channel.send.assert_awaited_once()
            self.assertEqual(
                main_channel.send.await_args.kwargs["embed"].title,
                "✨ Shiny Capture ✨",
            )
            self.assertFalse(
                shiny_channel.send.await_args.kwargs["allowed_mentions"].users
            )

    async def test_normal_starboard_posts_listed_catch_with_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 461
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 22 Obstagoon! "
                "(42.12%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = normal_channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertEqual(embed.fields, [])
            self.assertIn("**Caught by:** <@123>", embed.description)
            self.assertIn("**Pokémon:** Obstagoon", embed.description)
            self.assertIn("**Level:** 22", embed.description)
            self.assertIn("**IV:** 42.12%", embed.description)
            self.assertEqual(
                embed.thumbnail.url,
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                "sprites/pokemon/other/official-artwork/862.png",
            )
            self.assertIsNone(embed.image.url)
            self.assertEqual(embed.timestamp, message.created_at)
            button = normal_channel.send.await_args.kwargs["view"].children[0]
            self.assertEqual(button.label, "Jump to message")
            self.assertEqual(button.style, discord.ButtonStyle.link)
            self.assertEqual(
                button.url,
                f"https://discord.com/channels/{SERVER_ID}/304/{message.id}",
            )

    async def test_normal_starboard_attaches_custom_form_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 462
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 22 Zygarde Cell! "
                "(51.08%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            send_kwargs = normal_channel.send.await_args.kwargs
            self.assertEqual(
                send_kwargs["embed"].thumbnail.url,
                "attachment://zygardecell.png",
            )
            self.assertEqual(
                send_kwargs["file"].filename,
                "zygardecell.png",
            )
            send_kwargs["file"].close()

    async def test_normal_starboard_accepts_catch_text_from_other_bot_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 472
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id + 1
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 12 Xurkitree ♀ "
                "(54.84%)! Added to Pokédex."
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = normal_channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertIn("**Pokémon:** Xurkitree", embed.description)

    async def test_normal_starboard_posts_catch_with_curly_apostrophe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 462
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 10 "
                "Galarian Farfetch’d ♀! (62.90%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = normal_channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertIn("**Pokémon:** Galarian Farfetch'd", embed.description)
            self.assertIn("**Level:** 10", embed.description)

    async def test_normal_starboard_posts_in_unlisted_guild_for_new_and_edited_catches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)

            for message_id, use_edit in ((463, False), (464, True)):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = self.bot.config.poketwo_bot_id
                message.created_at = discord.utils.utcnow()
                message.content = (
                    "Congratulations <@123>! You caught a Level 22 Perrserker! "
                    "(62.90%)!"
                )
                message.embeds = []

                if use_edit:
                    await self.bot.on_message_edit(Mock(), message)
                else:
                    await self.bot.on_message(message)

            self.assertEqual(normal_channel.send.await_count, 2)

    async def test_vtest_posts_labeled_preview_for_listed_pokemon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 474
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/xurkitree.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Xurkitree", 100.0)),
            ):
                await self.bot.handle_spawn(message, test_mode=True)

            normal_channel.send.assert_awaited_once()
            embed = normal_channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "🧪 TEST — ⭐ Pokémon Spotlight")
            self.assertIn("**Caught by:** <@123>", embed.description)
            self.assertIn("**Pokémon:** Xurkitree", embed.description)
            self.assertIn("**Level:** Unknown", embed.description)
            self.assertIn("**IV:** Unknown", embed.description)
            self.assertEqual(embed.footer.text, "Test preview — not an actual catch")
            self.assertEqual(
                embed.description,
                "\n".join(
                    (
                        "**Caught by:** <@123>",
                        "**Pokémon:** Xurkitree",
                        "**Level:** Unknown",
                        "**IV:** Unknown",
                    )
                ),
            )
            button = normal_channel.send.await_args.kwargs["view"].children[0]
            self.assertEqual(
                button.url,
                f"https://discord.com/channels/{SERVER_ID}/304/474",
            )
            message.reply.assert_awaited_once()

    async def test_vtest_uses_custom_form_name_and_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 475
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/partner-pikachu.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Partner Pikachu", 100.0)),
            ):
                await self.bot.handle_spawn(message, test_mode=True)

            normal_channel.send.assert_awaited_once()
            send_kwargs = normal_channel.send.await_args.kwargs
            self.assertIn(
                "**Pokémon:** Partner Pikachu",
                send_kwargs["embed"].description,
            )
            self.assertEqual(
                send_kwargs["embed"].thumbnail.url,
                "attachment://partnerpikachu.png",
            )
            self.assertEqual(send_kwargs["file"].filename, "partnerpikachu.png")
            send_kwargs["file"].close()

    async def test_vtest_shiny_posts_preview_to_shinyboard_and_vivillon_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202, "shiny-board")
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            shiny_channel = Mock(send=AsyncMock())
            vivillon_channel = Mock(send=AsyncMock())
            normal_pokemon_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={
                    101: vivillon_channel,
                    202: shiny_channel,
                    303: normal_pokemon_channel,
                }.get
            )
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 475
            message.content = "v!test shiny"
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.author.bot = False
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/pikachu.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Galarian Articuno", 100.0)),
            ):
                await self.bot.on_message(message)

            shiny_channel.send.assert_awaited_once()
            vivillon_channel.send.assert_awaited_once()
            normal_pokemon_channel.send.assert_not_awaited()
            for channel in (shiny_channel, vivillon_channel):
                embed = channel.send.await_args.kwargs["embed"]
                self.assertEqual(embed.title, "🧪 TEST — ✨ Shiny Capture ✨")
                self.assertEqual(embed.fields, [])
                self.assertIn("**Caught by:** <@123>", embed.description)
                self.assertIn("**Pokémon:** Galarian Articuno", embed.description)
                self.assertIn("**Level:** Unknown", embed.description)
                self.assertIn("**IV:** Unknown", embed.description)
                self.assertTrue(
                    embed.footer.text.startswith(
                        "Test preview — not an actual catch"
                    )
                )
                self.assertIsNone(embed.image.url)
                self.assertEqual(
                    channel.send.await_args.kwargs["view"].children[0].url,
                    f"https://discord.com/channels/{SERVER_ID}/304/475",
                )
            shiny_embed = shiny_channel.send.await_args.kwargs["embed"]
            self.assertEqual(
                shiny_embed.thumbnail.url,
                "https://projectpokemon.org/images/sprites-models/"
                "swsh-shiny-sprites/articuno-galar.gif",
            )
            self.assertIn("PKParaiso", shiny_embed.footer.text)
            vivillon_embed = vivillon_channel.send.await_args.kwargs["embed"]
            self.assertEqual(
                vivillon_embed.thumbnail.url,
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                "sprites/pokemon/other/home/shiny/10169.png",
            )
            self.assertNotIn("PKParaiso", vivillon_embed.footer.text)

    async def test_real_shiny_featured_catch_skips_normal_starboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal", 101)
            self.bot.set_starboard_channel(guild_id, "shiny", 202, "shiny-board")
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            vivillon_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            shiny_channel.name = "shiny-board"
            shiny_channel.edit = AsyncMock()
            normal_pokemon_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={
                    101: vivillon_channel,
                    202: shiny_channel,
                    303: normal_pokemon_channel,
                }.get
            )
            message = Mock()
            message.id = 476
            message.guild.id = guild_id
            message.channel.id = 304
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 50 Galarian Articuno! "
                "These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.handle_catch_starboard(message)

            vivillon_channel.send.assert_awaited_once()
            shiny_channel.send.assert_awaited_once()
            normal_pokemon_channel.send.assert_not_awaited()

    async def test_normal_starboard_posts_catch_detection_embeds_from_other_bots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)

            for message_id, title, pokemon, trainer in (
                (465, "🌎 Regional Catch Detected!", "Hisuian Qwilfish", "<@123> 🌟"),
                (466, "⭐ Rare Catch Detected!", "Ogerpon", "<@123> 🌟"),
                (467, "🌎 Regional Catch Detected!", "Obstagoon", "@KillerX"),
                (468, "⭐ Rare Catch Detected!", "Azelf", "@KillerX"),
                (469, "⭐ Rare Catch Detected!", "Dialga", "@A"),
                (470, "🌎 Regional Catch Detected!", "Galarian Slowbro", "@Slyng Organizer"),
                (471, "⭐ Rare Catch Detected!", "Zapdos", None),
            ):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = 987654321
                message.created_at = discord.utils.utcnow()
                embed = discord.Embed(title=title)
                if trainer is not None:
                    embed.add_field(name="Trainer :", value=trainer, inline=True)
                embed.add_field(name="Pokemon :", value=pokemon, inline=True)
                embed.add_field(name="Level :", value="15", inline=True)
                embed.add_field(name="IVs :", value="54.30%", inline=True)
                embed.set_footer(text="Catch Detection System")
                message.embeds = [embed]
                message.content = ""

                await self.bot.on_message(message)

            self.assertEqual(normal_channel.send.await_count, 7)
            sent_embeds = [
                call.kwargs["embed"]
                for call in normal_channel.send.await_args_list
            ]
            self.assertEqual(
                [
                    next(
                        line
                        for line in embed.description.splitlines()
                        if line.startswith("**Pokémon:** ")
                    ).removeprefix("**Pokémon:** ")
                    for embed in sent_embeds
                ],
                [
                    "Hisuian Qwilfish",
                    "Ogerpon",
                    "Obstagoon",
                    "Azelf",
                    "Dialga",
                    "Galarian Slowbro",
                    "Zapdos",
                ],
            )
            self.assertEqual(
                [
                    call.kwargs["view"].children[0].url
                    for call in normal_channel.send.await_args_list
                ],
                [
                    f"https://discord.com/channels/{guild_id}/304/{message_id}"
                    for message_id in (465, 466, 467, 468, 469, 470, 471)
                ],
            )
            self.assertIn("**Caught by:** @KillerX", sent_embeds[2].description)
            self.assertIn("**Caught by:** @A", sent_embeds[4].description)
            self.assertIn("**Caught by:** Unknown", sent_embeds[6].description)

    async def test_catch_detection_description_rows_post_pokemon_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 467
            message.guild.id = guild_id
            message.channel.id = 304
            message.channel.guild.id = guild_id
            message.author.bot = True
            message.author.id = 987654321
            message.created_at = discord.utils.utcnow()
            embed = discord.Embed(
                title="⭐ Rare Catch Detected!",
                description=(
                    "Trainer : <@123>\n"
                    "Pokemon : Tapu Fini\n"
                    "Level : 34\n"
                    "IVs : 40.32%"
                ),
            )
            embed.set_footer(text="Catch Detection System")
            message.embeds = [embed]
            message.content = ""

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            sent_embed = normal_channel.send.await_args.kwargs["embed"]
            self.assertIn("**Pokémon:** Tapu Fini", sent_embed.description)

    async def test_catch_detection_special_categories_use_vivillon_and_shinyboards(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal", 101)
            self.bot.set_starboard_channel(guild_id, "shiny", 202, "shiny-board")
            vivillon_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock(), edit=AsyncMock())
            shiny_channel.name = "shiny-board"
            self.bot.get_channel = Mock(
                side_effect={101: vivillon_channel, 202: shiny_channel}.get
            )

            catches = (
                (467, "High-IV Catch Detected!", "Regieleki", "95.16%", "38"),
                (468, "Low-IV Catch Detected!", "Galarian Linoone", "8.60%", "1"),
                (469, "Shiny Catch Detected!", "Bagon", "54.30%", "15"),
                (
                    470,
                    "Gigantamax Catch Detected!",
                    "Rillaboom",
                    "54.30%",
                    "15",
                ),
                (471, "MissingNo. Catch Detected!", "MissingNo.", "???", "???"),
            )
            for message_id, title, pokemon, ivs, level in catches:
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = 987654321
                message.created_at = discord.utils.utcnow()
                embed = discord.Embed(title=title)
                embed.add_field(name="Trainer", value="<@123>", inline=True)
                embed.add_field(name="Pokemon", value=pokemon, inline=True)
                embed.add_field(name="Level", value=level, inline=True)
                embed.add_field(name="IVs", value=ivs, inline=True)
                embed.set_footer(text="Catch Detection System")
                message.embeds = [embed]
                message.content = ""

                await self.bot.on_message(message)

            self.assertEqual(vivillon_channel.send.await_count, 5)
            self.assertEqual(
                [
                    call.kwargs["embed"].title
                    for call in vivillon_channel.send.await_args_list
                ],
                [
                    "📈 High-IV Capture",
                    "📉 Low-IV Capture",
                    "✨ Shiny Capture ✨",
                    "🌟 Gigantamax Capture",
                    "❔ MissingNo. Capture",
                ],
            )
            shiny_channel.send.assert_awaited_once()

    async def test_missingno_catch_posts_to_the_main_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            main_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=main_channel)
            message = Mock()
            message.id = 457
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level ??? ???! (???)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            main_channel.send.assert_awaited_once()
            embed = main_channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "❔ MissingNo. Capture")
            self.assertEqual(embed.fields, [])
            self.assertIn("**Caught by:** <@123>", embed.description)
            self.assertIn("**Pokémon:** Missingno", embed.description)
            self.assertIn("**Level:** ???", embed.description)
            self.assertIn("**IV:** ???", embed.description)

    async def test_shiny_catches_increment_and_persist_the_channel_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(
                SERVER_ID,
                "shiny",
                202,
                "shiny-board",
            )
            shiny_channel = Mock(send=AsyncMock(), edit=AsyncMock())
            shiny_channel.name = "shiny-board"
            self.bot.get_channel = Mock(return_value=shiny_channel)

            for message_id in (459, 460):
                message = Mock()
                message.id = message_id
                message.guild.id = SERVER_ID
                message.channel.id = 303
                message.channel.guild.id = SERVER_ID
                message.author.bot = True
                message.author.id = self.bot.config.poketwo_bot_id
                message.created_at = discord.utils.utcnow()
                message.content = (
                    "Congratulations <@123>! You caught a Level 20 Bagon! "
                    "(50.54%)! These colors seem unusual... ✨"
                )
                message.embeds = []

                await self.bot.on_message(message)

            self.assertEqual(shiny_channel.send.await_count, 2)
            self.assertEqual(
                shiny_channel.edit.await_args_list,
                [
                    call(
                        name="shiny-board-1",
                        reason="Update shiny catch count",
                    ),
                    call(
                        name="shiny-board-2",
                        reason="Update shiny catch count",
                    ),
                ],
            )
            self.assertEqual(
                load_starboard_settings(self.bot.starboard_settings_path)[
                    str(SERVER_ID)
                ]["shiny_count"],
                2,
            )

    async def test_shiny_gigantamax_uses_the_matching_embed_on_each_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            main_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={101: main_channel, 202: shiny_channel}.get
            )
            message = Mock()
            message.id = 458
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 30 Corviknight ♀! "
                "(95.16%)! Gigantamax Factor. These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.on_message(message)

            self.assertEqual(
                main_channel.send.await_args.kwargs["embed"].title,
                "🌟 Gigantamax Capture",
            )
            self.assertEqual(
                shiny_channel.send.await_args.kwargs["embed"].title,
                "✨ Shiny Capture ✨",
            )
            self.assertIn(
                "**Gender:** Female",
                shiny_channel.send.await_args.kwargs["embed"].description,
            )


class ImageTestCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ConfigTests().load_config()
        self.bot = NamingBot(self.config)
        self.bot.handle_spawn = AsyncMock()

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_test_command_with_image_runs_spawn_handler_in_test_mode(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 99
        message.channel = unittest.mock.Mock()
        message.channel.guild.id = SERVER_ID
        message.content = "v!test"
        message.embeds = []
        message.attachments = [
            unittest.mock.Mock(content_type="image/png", url="https://example.test/missingno.png")
        ]
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_spawn.assert_awaited_once_with(
            message,
            test_mode=True,
            shiny_test_mode=False,
        )
        message.reply.assert_not_awaited()

    async def test_test_command_without_image_explains_usage(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 99
        message.channel = unittest.mock.Mock()
        message.channel.guild.id = SERVER_ID
        message.content = "v!test"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_spawn.assert_not_awaited()
        message.reply.assert_awaited_once_with(
            "Attach an image to `v!test` or `v!test shiny` "
            "to test spawn recognition.",
            mention_author=False,
        )

    def test_only_exact_test_command_matches(self) -> None:
        self.assertTrue(is_image_test_command("v!test"))
        self.assertTrue(is_image_test_command("v!test shiny"))
        self.assertTrue(is_image_test_command("V!TEST SHINY  "))
        self.assertTrue(is_image_test_command("V!TEST  "))
        self.assertFalse(is_image_test_command("v!test now"))
        self.assertFalse(is_image_test_command("v!test shiny now"))
        self.assertFalse(is_image_test_command("test"))

    async def test_real_missingno_blocks_poketwo_until_vr_command(self) -> None:
        self.bot.handle_spawn = NamingBot.handle_spawn.__get__(self.bot, NamingBot)
        self.bot.image_http = Mock(close=AsyncMock())
        spawn = Mock()
        spawn.id = 123
        spawn.channel.id = 456
        spawn.channel.guild.id = SERVER_ID
        spawn.channel.set_permissions = AsyncMock()
        spawn.attachments = [
            Mock(content_type="image/png", url="https://example.test/missingno.png")
        ]
        spawn.embeds = []
        spawn.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Missingno", 100.0)),
        ):
            await self.bot.handle_spawn(spawn)

        self.assertIn(456, self.bot.muted_poketwo_channels)
        self.assertEqual(self.bot.pokemon_named_count, 1)
        self.assertEqual(len(self.bot.recognition_durations), 1)
        spawn.channel.set_permissions.assert_awaited_once()
        self.assertIs(spawn.channel.set_permissions.await_args.kwargs["send_messages"], False)

        poketwo_message = Mock()
        poketwo_message.author.bot = True
        poketwo_message.author.id = self.config.poketwo_bot_id
        poketwo_message.channel.id = 456
        poketwo_message.channel.guild.id = SERVER_ID
        poketwo_message.content = "A wild Pokémon has appeared!"
        poketwo_message.embeds = []
        poketwo_message.attachments = [
            Mock(content_type="image/png", url="https://example.test/another.png")
        ]
        self.bot.handle_spawn = AsyncMock()
        await self.bot.on_message(poketwo_message)
        self.bot.handle_spawn.assert_awaited_once_with(poketwo_message)

        reserve_command = Mock()
        reserve_command.author.bot = False
        reserve_command.author.id = 789
        reserve_command.channel.id = 456
        reserve_command.channel.guild.id = SERVER_ID
        reserve_command.channel.set_permissions = AsyncMock()
        reserve_command.reply = AsyncMock()
        reserve_command.content = "v!r list"
        reserve_command.embeds = []
        reserve_command.attachments = []
        self.bot.handle_reserve_command = AsyncMock()
        await self.bot.on_message(reserve_command)

        self.assertNotIn(456, self.bot.muted_poketwo_channels)
        reserve_command.channel.set_permissions.assert_awaited_once()
        reserve_command.reply.assert_awaited_once_with(
            "Channel unpaused.", mention_author=False
        )
        self.bot.handle_reserve_command.assert_awaited_once_with(reserve_command)

    async def test_channel_filter_allows_both_configured_servers_only(self) -> None:
        allowed_channel = Mock()
        allowed_channel.guild.id = SERVER_ID
        allowed_channel.id = 456
        another_allowed_channel = Mock()
        another_allowed_channel.guild.id = 1543384606630481920
        another_allowed_channel.id = 789
        other_server_channel = Mock()
        other_server_channel.guild.id = SERVER_ID + 1

        self.assertTrue(self.bot.is_allowed_channel(allowed_channel))
        self.assertTrue(self.bot.is_allowed_channel(another_allowed_channel))
        self.assertFalse(self.bot.is_allowed_channel(other_server_channel))
        self.assertFalse(self.bot.is_allowed_channel(Mock()))


class FireSpawnFormattingTests(unittest.TestCase):
    def test_marks_pure_fire_pokemon_but_not_dual_type_pokemon(self) -> None:
        self.assertTrue(is_single_type_fire_pokemon("Vulpix"))
        self.assertTrue(is_single_type_fire_pokemon("Growlithe"))
        self.assertFalse(is_single_type_fire_pokemon("Charizard"))
        self.assertFalse(is_single_type_fire_pokemon("Rotom Heat"))

    def test_type_spawn_embed_shows_icon_and_catch_command(self) -> None:
        embed = format_type_spawn_embed("Glaceon", 87.5, 789, "ice_type.png")

        self.assertNotIn("author", embed.to_dict())
        self.assertEqual(embed.thumbnail.url, "attachment://ice_type.png")
        self.assertEqual(embed.description, "`@Pokétwo#8236 c glaceon`")

    def test_pc_catch_embed_shows_copy_label_and_spawned_pokemon_name(self) -> None:
        embed = format_pc_catch_embed("Pikachu")

        self.assertEqual(
            embed.title,
            "Catch Pikachu",
        )
        self.assertEqual(
            embed.description,
            "Copy Below\n```\n@Pokétwo#8236 c pikachu\n```",
        )

    def test_meowstic_spawn_uses_species_name_without_gender_prefix(self) -> None:
        embed = format_pc_catch_embed("Male Meowstic")

        self.assertEqual(format_guess("Male Meowstic", 100), "Meowstic: 100.00%")
        self.assertEqual(
            format_catch_command(789, "Male Meowstic"),
            "@Pokétwo#8236 c meowstic",
        )
        self.assertEqual(embed.title, "Catch Meowstic")
        self.assertEqual(
            embed.description,
            "Copy Below\n```\n@Pokétwo#8236 c meowstic\n```",
        )

    def test_zygarde_catch_embed_uses_ten_percent_form_sprite(self) -> None:
        embed = format_pc_catch_embed("Zygarde")

        self.assertEqual(embed.title, "Catch Zygarde")
        self.assertEqual(
            embed.description,
            "Copy Below\n```\n@Pokétwo#8236 c zygarde\n```",
        )
        self.assertEqual(
            embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/official-artwork/10118.png",
        )

    def test_custom_pokemon_catch_card_uses_bundled_thumbnail(self) -> None:
        for name in ("Koraidon", "Mosslax", "Peakychu"):
            with self.subTest(name=name):
                filename = f"{name.lower()}.png"
                embed = format_pc_catch_embed(name)
                files = catch_card_files(name)

                self.assertEqual(embed.thumbnail.url, f"attachment://{filename}")
                self.assertEqual([file.filename for file in files], [filename])
        self.assertEqual(catch_card_files("Pikachu"), [])

    def test_custom_form_catch_cards_show_form_but_copy_species_name(self) -> None:
        forms = (
            ("Partner Pikachu", "Pikachu"),
            ("Gliding Build Koraidon", "Koraidon"),
            ("Zenith Marshadow", "Marshadow"),
            ("Galarian Zen Darmanitan", "Darmanitan"),
            ("Zygarde Cell", "Zygarde"),
            ("Combat Breed Tauros", "Tauros"),
        )
        for form, species in forms:
            with self.subTest(form=form):
                embed = format_pc_catch_embed(species, form)
                files = catch_card_files(species, form)
                reply = format_spawn_reply(
                    species,
                    100,
                    POKETWO_COMMAND_BOT_ID,
                    guess_name=form,
                )
                filename = "".join(
                    character for character in form.casefold()
                    if character.isalnum()
                ) + ".png"

                self.assertEqual(embed.title, f"Catch {form}")
                self.assertEqual(
                    embed.description,
                    f"Copy Below\n```\n@Pokétwo#8236 c {species.casefold()}\n```",
                )
                self.assertEqual(embed.thumbnail.url, f"attachment://{filename}")
                self.assertEqual([file.filename for file in files], [filename])
                self.assertTrue(reply.startswith(f"{form}: 100.00%"))
                self.assertIn(f"c {species.casefold()}", reply)
                for file in files:
                    file.close()

    def test_custom_form_uses_its_artwork_on_normal_starboard(self) -> None:
        forms = (
            "Partner Pikachu",
            "Gliding Build Koraidon",
            "Zenith Marshadow",
            "Galarian Zen Darmanitan",
            "Zygarde Cell",
            "Combat Breed Tauros",
        )
        for form in forms:
            with self.subTest(form=form):
                details = parse_catch_details(
                    f"Congratulations <@123>! You caught a Level 22 {form}! "
                    "(51.08%)!"
                )
                self.assertIsNotNone(details)
                embed = format_starboard_embed(
                    details,
                    "normal_pokemon",
                    discord.utils.utcnow(),
                )
                filename = "".join(
                    character for character in form.casefold()
                    if character.isalnum()
                ) + ".png"

                self.assertEqual(
                    embed.thumbnail.url,
                    f"attachment://{filename}",
                )
                self.assertTrue(
                    (Path(__file__).with_name("assets") / "thumbnails" / filename)
                    .is_file()
                )

    def test_unown_variant_thumbnail_is_chosen_by_variant(self) -> None:
        self.assertEqual(image_match.base_pokemon_name("Unown Variant 3"), "Unown")
        self.assertEqual(image_match.base_pokemon_name("Tauros"), "Tauros")
        embed = format_pc_catch_embed("Unown", "Unown Variant 3")
        files = catch_card_files("Unown", "Unown Variant 3")

        self.assertEqual(embed.thumbnail.url, "attachment://unownvariant3.png")
        self.assertEqual([file.filename for file in files], ["unownvariant3.png"])
        self.assertEqual(catch_card_files("Unown"), [])

    def test_hangry_morpeko_uses_own_thumbnail_but_is_named_morpeko(self) -> None:
        self.assertEqual(image_match.species_display_name("Hangry Morpeko"), "Morpeko")
        embed = format_pc_catch_embed("Morpeko", "Hangry Morpeko")
        files = catch_card_files("Morpeko", "Hangry Morpeko")

        self.assertEqual(embed.title, "Catch Morpeko")
        self.assertEqual(embed.thumbnail.url, "attachment://hangrymorpeko.png")
        self.assertEqual([file.filename for file in files], ["hangrymorpeko.png"])
        self.assertEqual(catch_card_files("Morpeko"), [])

    def test_collection_all_pokemon_lists_every_form_and_matches_spawns(self) -> None:
        collections = add_collection_pokemon({}, 1, ["all deerling", "pikachu"], 5)

        self.assertEqual(
            collection_pokemon_for_user(collections, 1, 5),
            [
                "autumn deerling",
                "pikachu",
                "spring deerling",
                "summer deerling",
                "winter deerling",
            ],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 1, "Summer Deerling"), [5]
        )
        self.assertEqual(
            split_collection_add_names(collections, 1, ["all deerling"], 5),
            ([], ["all deerling"]),
        )
        self.assertEqual(
            format_collection_add_confirmation(["all deerling"], []),
            "Added All forms of deerling to your collection.",
        )
        updated, removed, missing = remove_collection_pokemon(
            collections, 1, ["all deerling"], 5
        )
        self.assertEqual(removed, ["all deerling"])
        self.assertEqual(collection_pokemon_for_user(updated, 1, 5), ["pikachu"])

    def test_legacy_all_collection_keys_are_migrated(self) -> None:
        migrated = migrate_legacy_all_keys({"1:all deerling": [5], "1:eevee": [5]})

        self.assertEqual(migrated, {"1:*:deerling": [5], "1:eevee": [5]})

    def test_fire_spawns_use_inline_custom_emoji_without_embed(self) -> None:
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Vulpix", 87.5, 789, [123], include_fire=True
            ),
            "<:fire:1560301436074729532> Vulpix: 87.50%\n"
            "Reserved: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c vulpix`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Vulpix",
                87.5,
                789,
                collection_user_ids=[456],
                include_fire=True,
                type_ping_user_ids=[123],
            ),
            "<:fire:1560301436074729532> Vulpix: 87.50%\n"
            "Collection: <@456>\n"
            "Typeping: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c vulpix`",
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
            "<:Normal:1560305235279482930> Eevee: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c eevee`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Volcanion", 87.5, 789, include_fire=True, include_water=True
            ),
            "<:water:1560303864094130357> "
            "<:fire:1560301436074729532> Volcanion: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c volcanion`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Litleo", 87.5, 789, include_fire=True, include_normal=True
            ),
            "<:fire:1560301436074729532> "
            "<:Normal:1560305235279482930> Litleo: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c litleo`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Bibarel", 87.5, 789, include_water=True, include_normal=True
            ),
            "<:Normal:1560305235279482930> "
            "<:water:1560303864094130357> Bibarel: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c bibarel`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Heliolisk", 87.5, 789, include_electric=True, include_normal=True
            ),
            "<:Electric:1560306053164572732> "
            "<:Normal:1560305235279482930> Heliolisk: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c heliolisk`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Heat", 87.5, 789, include_fire=True, include_electric=True
            ),
            "<:fire:1560301436074729532> "
            "<:Electric:1560306053164572732> Rotom Heat: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c rotom heat`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Scovillain", 87.5, 789, include_grass=True, include_fire=True
            ),
            "<:grass:1560307079896502282> "
            "<:fire:1560301436074729532> Scovillain: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c scovillain`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lotad", 87.5, 789, include_grass=True, include_water=True
            ),
            "<:grass:1560307079896502282> "
            "<:water:1560303864094130357> Lotad: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c lotad`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Smoliv", 87.5, 789, include_grass=True, include_normal=True
            ),
            "<:grass:1560307079896502282> "
            "<:Normal:1560305235279482930> Smoliv: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c smoliv`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Mow", 87.5, 789, include_grass=True, include_electric=True
            ),
            "<:grass:1560307079896502282> "
            "<:Electric:1560306053164572732> Rotom Mow: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c rotom mow`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Glaceon", 87.5, 789, include_ice=True
            ),
            "<:Ice:1560307867200782386> Glaceon: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c glaceon`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Darmanitan-Galar-Zen",
                87.5,
                789,
                include_fire=True,
                include_ice=True,
            ),
            "<:Ice:1560307867200782386> "
            "<:fire:1560301436074729532> Darmanitan-Galar-Zen: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c darmanitan-galar-zen`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lapras", 87.5, 789, include_water=True, include_ice=True
            ),
            "<:Ice:1560307867200782386> "
            "<:water:1560303864094130357> Lapras: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c lapras`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Arctozolt", 87.5, 789, include_electric=True, include_ice=True
            ),
            "<:Ice:1560307867200782386> "
            "<:Electric:1560306053164572732> Arctozolt: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c arctozolt`",
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
                "<:Normal:1560305235279482930> "
                "<:Ice:1560307867200782386> Test Pokemon: 87.50%\n"
                "**Copy Here >** `@Pokétwo#8236 c test pokemon`",
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
        self.assertIsNone(normal_companion_icon_filename_for_pokemon("Bibarel"))
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
            "@Pokétwo#8236 c pikachu",
        )

    def test_formats_guess_and_command_on_separate_lines(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 85, 716390085896962058),
            "Pikachu: 85.00%\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_squawkabilly_color_forms_use_the_species_name(self) -> None:
        for form_name in (
            "Blue-Plumage Squawkabilly",
            "Green-Plumage Squawkabilly",
            "White-Plumage Squawkabilly",
            "Yellow-Plumage Squawkabilly",
        ):
            with self.subTest(form_name=form_name):
                species_name = image_match.species_display_name(form_name)
                self.assertEqual(
                    format_spawn_reply(species_name, 100, POKETWO_COMMAND_BOT_ID),
                    "Squawkabilly: 100.00%\n"
                    "**Copy Here >** `@Pokétwo#8236 c squawkabilly`",
                )

    def test_formats_only_the_reserved_members_as_mentions(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 716390085896962058, [123, 456]),
            "Pikachu: 95.00%\n"
            "Reserved: <@123>, <@456>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_formats_shinyhunters_without_empty_collection_line(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [], [123, 456]),
            "Absol: 95.00%\n"
            "Shinyhunt: <@123>, <@456>\n"
            "**Copy Here >** `@Pokétwo#8236 c absol`",
        )

    def test_reservations_override_shinyhunters_in_spawn_reply(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [999], [123, 456]),
            "Absol: 95.00%\n"
            "Reserved: <@999>\n"
            "**Copy Here >** `@Pokétwo#8236 c absol`",
        )

    def test_collection_ping_is_included_without_empty_shinyhunt_line(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [], [123]),
            "Pikachu: 95.00%\n"
            "Collection: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_collection_and_shinyhunt_ping_multiple_members(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [123], [456, 789]),
            "Pikachu: 95.00%\n"
            "Shinyhunt: <@123>\n"
            "Collection: <@456>, <@789>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_typeping_has_its_own_line_after_collection(self) -> None:
        self.assertEqual(
            format_spawn_reply(
                "Pikachu",
                95,
                789,
                [],
                [123],
                [456],
                [789, 101],
            ),
            "Pikachu: 95.00%\n"
            "Shinyhunt: <@123>\n"
            "Collection: <@456>\n"
            "Typeping: <@789>, <@101>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_reservation_overrides_all_other_ping_categories(self) -> None:
        self.assertEqual(
            format_spawn_reply(
                "Pikachu",
                95,
                789,
                [111],
                [123],
                [456],
                [789],
            ),
            "Pikachu: 95.00%\n"
            "Reserved: <@111>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )


class AllFormsMatchingTests(unittest.TestCase):
    def test_all_marshadow_matches_other_forms_of_marshadow(self) -> None:
        for name in ("Marshadow", "Zenith Marshadow", "Marshadow (Zenith)", "Mega Marshadow"):
            with self.subTest(name=name):
                self.assertTrue(pokemon_matches_all_forms_reservation(name, "marshadow"))

    def test_all_forms_does_not_match_other_species(self) -> None:
        self.assertFalse(pokemon_matches_all_forms_reservation("Mewtwo", "mew"))
        self.assertFalse(pokemon_matches_all_forms_reservation("Mega Mewtwo X", "mew"))


class ReservationExchangeTests(unittest.TestCase):
    def test_parses_member_lines_with_multiple_pokemon(self) -> None:
        text = "<@1> - pikachu, Eevee\n<@2> - all arceus\nnoise\n<@3> – sylveon"

        self.assertEqual(
            parse_exchange_list(text),
            [(1, ["pikachu", "Eevee"]), (2, ["all arceus"]), (3, ["sylveon"])],
        )

    def test_moves_only_reservations_held_by_the_source(self) -> None:
        reservations = {
            "10:pikachu": [100, 5],
            "10:eevee": [5],
            "10:*:arceus": [100],
        }
        updated, moved, skipped = exchange_reservations(
            reservations,
            10,
            100,
            [(1, ["pikachu", "eevee"]), (2, ["all arceus"])],
        )

        self.assertEqual(updated["10:pikachu"], [5, 1])
        self.assertEqual(updated["10:eevee"], [5])
        self.assertEqual(updated["10:*:arceus"], [2])
        self.assertEqual(moved, [(1, "pikachu"), (2, "all arceus")])
        self.assertEqual(skipped, [(1, "eevee")])
        self.assertEqual(reservations["10:pikachu"], [100, 5])


class AllFormsExchangeTests(unittest.TestCase):
    def test_all_marshadow_moves_every_marshadow_form(self) -> None:
        reservations = {
            "10:*:marshadow": [100],
            "10:marshadow": [100],
            "10:zenith marshadow": [100, 7],
            "10:mew": [100],
        }
        updated, moved, skipped = exchange_reservations(
            reservations, 10, 100, [(1, ["all marshadow"])]
        )

        self.assertEqual(updated["10:*:marshadow"], [1])
        self.assertEqual(updated["10:marshadow"], [1])
        self.assertEqual(updated["10:zenith marshadow"], [7, 1])
        self.assertEqual(updated["10:mew"], [100])
        self.assertEqual(moved, [(1, "all marshadow")])
        self.assertEqual(skipped, [])


class RegionalExchangeTests(unittest.TestCase):
    def test_all_articuno_exchange_includes_regional_forms(self) -> None:
        reservations = {
            "10:*:articuno": [100],
            "10:articuno": [100],
            "10:galarian articuno": [100],
            "10:articuno (galar)": [100],
            "10:zapdos": [100],
        }
        updated, moved, _ = exchange_reservations(
            reservations, 10, 100, [(1, ["all articuno"])]
        )

        for key in (
            "10:*:articuno",
            "10:articuno",
            "10:galarian articuno",
            "10:articuno (galar)",
        ):
            self.assertEqual(updated[key], [1])
        self.assertEqual(updated["10:zapdos"], [100])
        self.assertEqual(moved, [(1, "all articuno")])


class GrabListTests(unittest.TestCase):
    def test_parses_search_lines_and_mentions(self) -> None:
        entries = parse_grab_entries(
            ["pikachu <@1>\n- eevee\nall forms of arceus <@2> <@3>"]
        )

        self.assertEqual(
            entries,
            [("pikachu", [1]), ("eevee", []), ("all arceus", [2, 3])],
        )

    def test_parses_labelled_org_reserve_list(self) -> None:
        text = (
            "📜 **Org Reserve List**\n\n"
            "**Regional** — <@1> - Zorua\n"
            "**Eevos** — <@2> - Absol\n"
            "**Booster** — <@3> - Cutiefly\n"
            "**Booster 2** — <@2> - Missingno"
        )

        self.assertEqual(
            parse_grab_entries([text]),
            [("Zorua", [1]), ("Absol", [2]), ("Cutiefly", [3]), ("Missingno", [2])],
        )

    def test_parses_plain_and_comma_lists(self) -> None:
        self.assertEqual(
            parse_grab_entries(["Mewtwo\n1. Mr. Mime, Galarian Articuno <@4>\nhello"]),
            [("Mewtwo", []), ("Mr. Mime", [4]), ("Galarian Articuno", [4])],
        )

    def test_order_all_forms_and_emoji_cycle(self) -> None:
        entries = [("sylveon", [1]), ("trapinch", []), ("urshifu", []), ("ditto", [])]

        self.assertEqual(
            build_grab_lines(entries, ordered=True, all_forms=True, emojis=["🔥", "💧"]),
            ["🔥 Ditto", "💧 Sylveon", "🔥 Trapinch", "💧 All urshifu"],
        )
        self.assertEqual(
            build_grab_lines(entries, ordered=False, all_forms=False, emojis=[]),
            ["Sylveon", "Trapinch", "Urshifu", "Ditto"],
        )

    def test_grab_display_names(self) -> None:
        self.assertEqual(grab_display_name("pikachu"), "Pikachu")
        self.assertEqual(grab_display_name("all urshifu"), "All forms of urshifu")

    def test_bulk_add_gives_each_pokemon_to_its_user(self) -> None:
        pairs = grab_reserve_pairs(
            [("pikachu", [1]), ("alcremie", [2]), ("eevee", [])], False
        )
        updated = add_reservations_bulk({"5:pikachu": [9]}, 5, pairs)

        self.assertEqual(updated["5:pikachu"], [9, 1])
        self.assertEqual(updated["5:alcremie"], [2])
        self.assertNotIn("5:eevee", updated)


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

    def test_clear_guild_collection_preserves_other_guilds(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_guild_collection(collections, 1)

        self.assertEqual(updated, {reservation_key(2, "Pikachu"): [123]})
        self.assertEqual(collections[reservation_key(1, "Pikachu")], [123, 456])

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

    def test_parses_shinyhunt_removal_name(self) -> None:
        self.assertEqual(
            parse_shinyhunt_remove_command("v!sh remove Pikachu"),
            "Pikachu",
        )
        self.assertEqual(
            parse_shinyhunt_remove_command("v!sh remove all Arceus"),
            "all Arceus",
        )
        self.assertIsNone(parse_shinyhunt_remove_command("v!sh remove"))
        self.assertIsNone(
            parse_shinyhunt_remove_command("v!sh remove pikachu, eevee")
        )

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

    def test_shinyhunt_removal_only_removes_requesting_user(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, removed = remove_shinyhunter(shinyhunters, 1, "pikachu", 123)

        self.assertTrue(removed)
        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(1, "Eevee"): [123],
                reservation_key(2, "Pikachu"): [123],
            },
        )
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123, 456])

    def test_shinyhunt_removal_reports_missing_selection(self) -> None:
        updated, removed = remove_shinyhunter(
            {reservation_key(1, "Pikachu"): [456]},
            1,
            "Pikachu",
            123,
        )

        self.assertFalse(removed)
        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})

    def test_clears_only_the_requesting_users_hunts_in_one_guild(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, cleared = clear_shinyhunter(shinyhunters, 1, 123)

        self.assertTrue(cleared)
        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(2, "Pikachu"): [123],
            },
        )
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123, 456])

    def test_shinyhunt_clear_reports_when_no_hunt_was_found(self) -> None:
        shinyhunters = {reservation_key(1, "Pikachu"): [456]}

        updated, cleared = clear_shinyhunter(shinyhunters, 1, 123)

        self.assertFalse(cleared)
        self.assertEqual(updated, shinyhunters)

    def test_clear_guild_shinyhunts_preserves_other_guilds(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_guild_shinyhunts(shinyhunters, 1)

        self.assertEqual(updated, {reservation_key(2, "Pikachu"): [123]})
        self.assertEqual(
            shinyhunters[reservation_key(1, "Pikachu")],
            [123, 456],
        )

    def test_shinyhunt_removal_supports_all_forms(self) -> None:
        shinyhunters = {
            all_forms_reservation_key(1, "Arceus"): [123, 456],
        }

        updated, removed = remove_shinyhunter(
            shinyhunters,
            1,
            "all arceus",
            123,
        )

        self.assertTrue(removed)
        self.assertEqual(
            updated,
            {all_forms_reservation_key(1, "Arceus"): [456]},
        )

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
        reservations = {
            all_forms_reservation_key(1, "Marshadow"): [123],
            all_forms_reservation_key(1, "Urshifu"): [123],
        }

        self.assertEqual(
            reserved_pokemon_for_user(reservations, 1, 123),
            [
                "all forms of marshadow",
                "rapid strike gmax urshifu",
                "rapid strike urshifu",
                "single strike gmax urshifu",
                "single-strike urshifu",
            ],
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
            {
                all_forms_reservation_key(1, "Marshadow"): [123],
                all_forms_reservation_key(1, "Zacian"): [456],
            },
            1,
        )

        self.assertEqual(
            embeds[0].description,
            "all forms of marshadow <@123>\n"
            "crowned zacian <@456>\n"
            "zacian <@456>",
        )

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

    def test_accepts_special_pokemon_names_in_user_commands(self) -> None:
        for name in (
            "Chef Dente",
            "Prof Tangrowth",
            "Peakychu",
            "DJ Rotom",
            "Smearguru",
            "Mosslax",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_known_pokemon_name(name))
                self.assertEqual(parse_shinyhunt_command(f"v!sh {name}"), name)
                self.assertEqual(parse_collection_add_command(f"v!cl add {name}"), [name])
                self.assertEqual(
                    parse_reserve_add_command(f"v!r add {name} <@319>"),
                    ([name], 319),
                )

    def test_rejects_multiple_candidates_and_unexpected_symbols(self) -> None:
        self.assertFalse(is_valid_pokemon_name("Gothorita / Gothita"))
        self.assertFalse(is_valid_pokemon_name("Gothorita!"))


class OrgReservesTests(unittest.TestCase):
    def test_validation_and_restrictions(self):
        import tempfile
        from org_api import OrgError, OrgReserves

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "r.json").write_text(
                '{"slots": {"s": {"allowed": ["Pikachu"]}}}', encoding="utf-8"
            )
            org = OrgReserves(root / "o.json", root / "r.json", ["Pikachu", "Eevee"])
            self.assertEqual(org.validate("all pikachu", "s"), ("Pikachu", True))
            with self.assertRaises(OrgError):
                org.validate("Eevee", "s")
            with self.assertRaises(OrgError):
                org.validate("Nope", None)
            self.assertTrue(org.add("Pikachu", 1, "s"))
            self.assertFalse(org.add("Pikachu", 1, "s"))
            self.assertEqual(org.reset(), 1)
            self.assertEqual(org.entries, [])

    def test_shared_org_restrictions_apply_to_all_configured_slots(self):
        from org_api import OrgError, OrgReserves

        slot_names = (
            "rares",
            "regionals",
            "gmax",
            "eevos",
            "paradox",
            "slot1",
            "slot2",
            "slot3",
            "slot4",
            "donator",
            "boostie",
        )
        org = OrgReserves(
            Path(__file__).with_name("org_reserves.json"),
            Path(__file__).with_name("org_restrictions.json"),
            ["Abomasnow", "Orbeetle", "Gmax Orbeetle"],
        )

        self.assertEqual(set(org.restrictions), set(slot_names))
        shared_rule = org.restrictions[slot_names[0]]
        for slot in slot_names:
            with self.subTest(slot=slot):
                self.assertEqual(org.restrictions[slot], shared_rule)
                self.assertEqual(org.validate("Abomasnow", slot), ("Abomasnow", False))
                with self.assertRaises(OrgError):
                    org.validate("Orbeetle", slot)
                with self.assertRaises(OrgError):
                    org.validate("Gmax Orbeetle", slot)


class OrgApiValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_rpc_matches_org_reserves_for_every_slot(self) -> None:
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgError, OrgReserves, create_app

        slots = (
            "rares",
            "regionals",
            "gmax",
            "eevos",
            "paradox",
            "slot1",
            "slot2",
            "slot3",
            "slot4",
            "donator",
            "boostie",
        )
        org = OrgReserves(
            Path(__file__).with_name("org_reserves.json"),
            Path(__file__).with_name("org_restrictions.json"),
            ["Abomasnow", "Orbeetle"],
        )
        app = create_app("test-api-key", org, 1, lambda *_: None, lambda *_: False)

        async with TestClient(TestServer(app)) as client:
            for slot in slots:
                for pokemon in ("Abomasnow", "Orbeetle"):
                    try:
                        name, all_forms = org.validate(pokemon, slot)
                        expected = {
                            "success": True,
                            "valid": True,
                            "pokemon": f"All {name}" if all_forms else name,
                        }
                    except OrgError as error:
                        expected = {"success": False, "error": error.message}
                    response = await client.post(
                        "/api/org/validate",
                        json={"pokemon": pokemon, "slot": slot},
                        headers={"Authorization": "Bearer test-api-key"},
                    )
                    self.assertEqual(
                        response.status, 200 if expected["success"] else 403
                    )
                    self.assertEqual(await response.json(), expected)


class TypeEmojiTests(unittest.TestCase):
    def test_dual_type_pokemon_get_both_emojis_in_order(self) -> None:
        import bot

        self.assertEqual(
            bot.type_emoji_text("Charizard"),
            f"{bot.TYPE_EMOJIS['fire']}{bot.TYPE_EMOJIS['flying']}",
        )

    def test_forms_use_their_own_types(self) -> None:
        import bot

        self.assertEqual(bot.pokemon_types_for("Heat Rotom"), ["electric", "fire"])
        self.assertEqual(bot.pokemon_types_for("Bug Silvally", "Silvally"), ["bug"])
        self.assertEqual(bot.pokemon_types_for("Icy-Snow Vivillon"), ["bug", "flying"])

    def test_every_type_has_an_emoji_and_reply_leads_with_it(self) -> None:
        import bot

        self.assertEqual(len(bot.TYPE_EMOJIS), 18)
        reply = bot.format_typed_spawn_reply(
            "Gengar",
            100.0,
            1,
            bot.type_emoji_text("Gengar"),
            [],
            [123],
            [456],
            [789],
        )
        lines = reply.splitlines()
        self.assertTrue(lines[0].startswith(bot.TYPE_EMOJIS["ghost"]))
        self.assertIn("Gengar: 100.00%", lines[0])
        self.assertEqual(
            lines[1:4],
            [
                "Shinyhunt: <@123>",
                "Collection: <@456>",
                "Typeping: <@789>",
            ],
        )


if __name__ == "__main__":
    unittest.main()
