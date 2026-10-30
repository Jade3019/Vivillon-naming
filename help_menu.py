"""The `v!help` command list."""

from typing import Final

import discord

HELP_COMMAND_PATTERN: Final[str] = r"^v!help\s*$"

HELP_CATEGORIES: Final[list[tuple[str, list[tuple[str, str]]]]] = [
    (
        "🔍 Spawn Naming",
        [
            ("v!grab", "Reply to a Pokémon list to turn it into a clean grab list."),
        ],
    ),
    (
        "📌 Reserves",
        [
            ("v!r add <pokemon, ...> @member", "Reserve Pokémon for a member (`all <pokemon>` covers every form)."),
            ("v!r remove <pokemon, ...> [@member]", "Remove reserves."),
            ("v!r search <pokemon|@member>", "See who reserved a Pokémon, or what a member reserved."),
            ("v!r list", "Show every reserve in the server."),
            ("v!r e @owner", "Reply to a reserve list to hand those reserves to another member."),
            ("v!r clear", "Clear every reserve in the server."),
        ],
    ),
    (
        "✨ Shiny Hunt & Collection",
        [
            ("v!sh <pokemon>", "Start shiny hunting a Pokémon and get pinged when it spawns."),
            ("v!sh remove <pokemon>", "Stop hunting a Pokémon."),
            ("v!sh clear / clear all", "Clear your hunts, or the whole server's."),
            ("v!cl add <pokemon, ...>", "Add Pokémon to your collection pings."),
            ("v!cl remove <pokemon, ...>", "Remove Pokémon from your collection."),
            ("v!cl list", "Show your collection."),
            ("v!cl clear / clear all", "Clear your collection, or the whole server's."),
            (
                "v!tp / v!typeping",
                "Choose Pokémon types to get pinged for, including dual-type spawns.",
            ),
        ],
    ),
    (
        "🥚 Breeding Boxes & Daycare",
        [
            ("v!box", "Show all your boxes and how full they are (limit 7,500 each)."),
            ("v!box create <name>", "Make a new box."),
            ("v!box append [box] [-c]", "Reply to a Pokétwo list to store its Pokémon; page arrows keep adding."),
            ("v!box list / remove / transfer / copy", "Browse, delete, move or duplicate stored Pokémon and boxes."),
            ("v!box tag / untag / tags / tagged", "Track egg moves on stored Pokémon."),
            ("v!box rename / delete / clear / reset", "Manage or wipe boxes."),
            ("v!dc [box]", "Pull 1-2 breedable pairs with a ready-to-paste daycare command."),
            ("v!dc settings", "Change how pairs are picked and shown."),
            ("v!boxhelp", "Full list of box commands."),
        ],
    ),
    (
        "⚙️ Settings & Utility",
        [
            ("v!settings", "Server settings: turn naming, assisted replies and ping-only mode on or off."),
            ("v!lowaccuracy #channel", "Post a link in that channel whenever a spawn scores under 90% (use `off` to disable)."),
            ("v!afk", "Your personal ping settings for shiny hunts and collections."),
            ("v!profile [@user]", "View your or another member's Pokémon catch stats."),
            ("v!backfill", "Admins: backfill profile catches from readable server history."),
            ("v!settime @role ...", "Choose the roles pinged for timed spawns."),
            ("v!timereset", "Reset that timer."),
            ("v!event", "Start a chat event."),
            ("v!ping", "Check the bot's response time."),
            ("v!api", "See how many Pokémon were recognized recently."),
            ("v!help", "Show this list."),
        ],
    ),
]


def build_help_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Vivillon Command List",
        description="Everything the bot can do, grouped by purpose. Names in `<>` are required, `[]` optional.",
        color=discord.Color.from_rgb(0x9B, 0x8C, 0xE8),
    )
    for title, commands in HELP_CATEGORIES:
        embed.add_field(
            name=title,
            value="\n".join(f"`{usage}`\n-# {text}" for usage, text in commands),
            inline=False,
        )
    embed.set_footer(text="Tip: v!boxhelp explains every box command in detail.")
    return embed
