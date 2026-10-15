import asyncio
import base64
import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiohttp
import discord
from openai import AsyncOpenAI, OpenAIError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vivillon_naming")

SPAWN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bwild\s+(?:pokemon|pok[eé]mon)\b", re.IGNORECASE
)
RESERVE_ROLE_ID: Final[int] = 1532820386511720579
SHINYHUNT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!sh\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+add\s+(.+?)\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
RESERVE_SEARCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+search\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
RESERVE_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+remove\s+(.+?)(?:(?:\s*,\s*|\s+)<@!?(\d+)>)?\s*$",
    re.IGNORECASE,
)
RESERVATION_EMBED_DESCRIPTION_LIMIT: Final[int] = 3800

@dataclass(frozen=True)
class Config:
    discord_token: str
    openai_api_key: str
    poketwo_bot_id: int
    allowed_channel_id: int | None
    openai_model: str

    @classmethod
    def from_environment(cls) -> "Config":
        discord_token = os.environ.get("DISCORD_TOKEN")
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        poketwo_bot_id = os.environ.get("POKETWO_BOT_ID")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN is required")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not poketwo_bot_id:
            raise ValueError("POKETWO_BOT_ID is required")

        channel_id = os.environ.get("ALLOWED_CHANNEL_ID")
        try:
            return cls(
                discord_token=discord_token,
                openai_api_key=openai_api_key,
                poketwo_bot_id=int(poketwo_bot_id),
                allowed_channel_id=int(channel_id) if channel_id else None,
                openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            )
        except ValueError as error:
            raise ValueError(
                "POKETWO_BOT_ID and ALLOWED_CHANNEL_ID must be numeric Discord IDs"
            ) from error


def message_text(message: discord.Message) -> str:
    parts = [message.content]
    for embed in message.embeds:
        parts.extend((embed.title or "", embed.description or ""))
        parts.extend(f"{field.name}: {field.value}" for field in embed.fields)
    return "\n".join(part for part in parts if part)


def image_url(message: discord.Message) -> str | None:
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                return attachment.url
    for embed in message.embeds:
        for image in (embed.image, embed.thumbnail):
            if image.url:
                return image.url
    return None


async def recognize_pokemon(
    url: str,
    *,
    client: AsyncOpenAI,
    http: aiohttp.ClientSession,
    model: str,
) -> tuple[str, float]:
    async with http.get(url) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError(f"Spawn image URL returned non-image content: {content_type}")
        image_bytes = await response.read()

    if not image_bytes:
        raise ValueError("Spawn image was empty")

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    result = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Identify the Pokémon species shown in this Pokétwo wild-spawn "
                    "image. The species may be any Pokémon in the National Pokédex "
                    "through #1026. Base the answer on the Pokémon's visible body, "
                    "face, and distinctive features, not the background or habitat. "
                    "Carefully distinguish visually similar species before choosing. "
                    "For example, Eldegoss has a large round white cotton puff with "
                    "small brown seeds around a yellow-green leafy face; Shaymin's "
                    "Land Forme is a small white quadruped with green hedgehog-like "
                    "back fur and a pink flower by its ear, not a cotton puff. "
                    "Lumineon is a fish with a dark blue body, pink eyes, and very "
                    "large wing-like fins with pale blue edges and dark scalloped "
                    "markings; do not mistake its fins for wings or use the underwater "
                    "background alone to identify it. "
                    "Houndour is a small dark canine with an orange muzzle and pale "
                    "bone-like bands around its legs and back; distinguish its dog-like "
                    "body from other dark quadruped Pokémon. "
                    "Duskull is a small floating gray ghost with a skull-shaped white "
                    "mask, one visible glowing red eye in a dark socket, and a single "
                    "curved horn; do not confuse it with other skull-faced Ghost Pokémon. "
                    "Staravia is a gray-and-white bird with an angular white face marking, "
                    "orange beak and feet, a dark swept-up crest with a rounded curl, and "
                    "a black chest marking; distinguish it from smaller Starly and the "
                    "larger Staraptor. "
                    "Tinkatink is a small pink humanoid Pokémon with a round head, "
                    "pointed top tuft, gray diamond-shaped chest plate, and an oversized "
                    "rough gray hammer it holds; identify the pink hammer-wielder rather "
                    "than its hammer as a separate object. "
                    "Dewpider is a small spider Pokémon with a round blue bubble of water "
                    "over its head, a blue face with large eyes, and slender lime-green "
                    "legs; do not mistake the water bubble around its head for a body part "
                    "or identify it only from a watery setting. "
                    "Pansage is a small green monkey-like Pokémon with very large round "
                    "ears, a pale cream face and hands, a leafy green tuft on top of its "
                    "head, and a long curled tail; distinguish it from the similar "
                    "Pansear and Panpour by its green coloring. "
                    "Cascoon is a floating cocoon-shaped Pokémon with a pale lavender "
                    "segmented shell, several long pointed spikes, and one visible red "
                    "eye; distinguish it from Silcoon, which is green and has no spikes. "
                    "Sewaddle is a small green caterpillar-like Pokémon wearing a "
                    "large leaf hood, with a yellow face, black eyes, orange mouth, and "
                    "a segmented green body with small orange bumps; distinguish it from "
                    "other small Bug-type Pokémon by the leaf covering its head. "
                    "Pyukumuku is a small black, flattened oval sea-cucumber Pokémon "
                    "with several short pink spikes on its back, tiny pink eyes, and a "
                    "distinctive white X-shaped mouth; do not confuse its oval silhouette "
                    "with a fish or spiky sea creature. "
                    "Tadbulb is a tiny floating electric Pokémon with a large bright "
                    "yellow bulb-like head, a dark gray face area with small glowing "
                    "eyes, and a short dangling orange-and-gray tail; distinguish it "
                    "from round yellow Pokémon by this dark face and tapered tail. "
                    "Charcadet is a small humanoid Pokémon with a dark charcoal helmet-like "
                    "head, a glowing orange-red eye, red and orange armor-like body parts, "
                    "and a small flame-like plume on top; distinguish it from other "
                    "fire-themed humanoid Pokémon by its oversized dark head. "
                    "Choose the single most likely Pokémon name. Never "
                    "return multiple candidates, alternate names, aliases, or a list. "
                    "Estimate your confidence in that one guess as a percentage "
                    "from 0 to 100 with up to two decimal places. Return JSON only, "
                    "in the form "
                    '{"name":"one Pokétwo-accepted English name","confidence":85.34}. '
                    "Include a form or "
                    "regional name when needed to identify the shown Pokémon. If the "
                    "image is not recognizable as a Pokémon, set name to an empty "
                    "string and confidence to 0."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{encoded_image}",
                            "detail": "high",
                        },
                    }
                ],
            },
        ],
    )
    content = result.choices[0].message.content
    if not content:
        raise ValueError("Vision model returned an empty response")
    prediction = json.loads(content)
    if not isinstance(prediction, dict):
        raise ValueError("Vision model response must be a JSON object")
    name = prediction.get("name")
    if not isinstance(name, str):
        raise ValueError("Vision model response did not include a Pokémon name")
    confidence = prediction.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 100
    ):
        raise ValueError("Vision model response included an invalid confidence percentage")
    name = unicodedata.normalize("NFC", name.strip())
    if len(name) > 60 or (name and not is_valid_pokemon_name(name)):
        raise ValueError("Vision model returned an invalid Pokémon name")
    return name, float(confidence)


def is_valid_pokemon_name(name: str) -> bool:
    allowed_punctuation = " .'-:♀♂"
    return bool(name) and any(char.isalpha() for char in name) and all(
        unicodedata.category(char)[0] in {"L", "M", "N"}
        or char in allowed_punctuation
        for char in name
    )


def format_guess(name: str, confidence: float) -> str:
    return f"{name}: {confidence:.2f}%"


def format_catch_command(poketwo_bot_id: int, name: str) -> str:
    return f"<@{poketwo_bot_id}> c {name.lower()}"


def format_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
) -> str:
    command = format_catch_command(poketwo_bot_id, name)
    lines = [format_guess(name, confidence)]
    if reserved_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in reserved_user_ids)
        lines.append(f"Reserved: {mentions}")
    elif shinyhunter_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in shinyhunter_user_ids)
        lines.append(f"Shinyhunt: {mentions}")
    lines.append(f"`{command}`")
    return "\n".join(lines)


def reservation_key(guild_id: int, pokemon_name: str) -> str:
    normalized_name = unicodedata.normalize("NFC", pokemon_name).casefold()
    return f"{guild_id}:{normalized_name}"


def parse_shinyhunt_command(content: str) -> str | None:
    match = SHINYHUNT_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None
    pokemon_name = unicodedata.normalize("NFC", match.group(1).strip())
    if (
        not pokemon_name
        or "," in pokemon_name
        or len(pokemon_name) > 60
        or not is_valid_pokemon_name(pokemon_name)
    ):
        return None
    return pokemon_name


def add_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int,
) -> dict[str, list[int]]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    guild_prefix = f"{guild_id}:"
    for key in list(updated_shinyhunters):
        if not key.startswith(guild_prefix):
            continue
        user_ids = updated_shinyhunters[key]
        if user_id in user_ids:
            user_ids.remove(user_id)
            if not user_ids:
                del updated_shinyhunters[key]
    user_ids = updated_shinyhunters.setdefault(reservation_key(guild_id, pokemon_name), [])
    if user_id not in user_ids:
        user_ids.append(user_id)
    return updated_shinyhunters


def format_shinyhunt_status(pokemon_name: str) -> str:
    return f"You are currently shinyhunting {pokemon_name.casefold()}"


def format_shinyhunt_confirmation(pokemon_name: str) -> str:
    return f"You are now shinyhunting {pokemon_name.casefold()}"


def shinyhunt_pokemon_for_user(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    return sorted(
        key.removeprefix(guild_prefix)
        for key, user_ids in shinyhunters.items()
        if key.startswith(guild_prefix) and user_id in user_ids
    )


def parse_reserve_add_command(content: str) -> tuple[list[str], int] | None:
    match = RESERVE_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None

    pokemon_names = [
        unicodedata.normalize("NFC", name.strip())
        for name in match.group(1).split(",")
    ]
    if (
        not pokemon_names
        or any(
            not name or len(name) > 60 or not is_valid_pokemon_name(name)
            for name in pokemon_names
        )
    ):
        return None
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in pokemon_names:
        normalized_name = name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(name)
            seen_names.add(normalized_name)
    return unique_names, int(match.group(2))


def parse_reserve_remove_command(
    content: str,
) -> tuple[list[str], int | None] | None:
    match = RESERVE_REMOVE_PATTERN.fullmatch(content)
    if match is None:
        return None

    pokemon_names = [
        unicodedata.normalize("NFC", name.strip())
        for name in match.group(1).split(",")
    ]
    if any(
        not name or len(name) > 60 or not is_valid_pokemon_name(name)
        for name in pokemon_names
    ):
        return None

    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in pokemon_names:
        normalized_name = name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(name)
            seen_names.add(normalized_name)
    target_id = int(match.group(2)) if match.group(2) else None
    return unique_names, target_id


def reserved_pokemon_for_user(
    reservations: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    names = [
        key.removeprefix(guild_prefix)
        for key, user_ids in reservations.items()
        if key.startswith(guild_prefix) and user_id in user_ids
    ]
    return sorted(names)


def remove_reservation(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int | None = None,
) -> tuple[dict[str, list[int]], bool]:
    updated_reservations = {
        key: list(user_ids) for key, user_ids in reservations.items()
    }
    key = reservation_key(guild_id, pokemon_name)
    reserved_user_ids = updated_reservations.get(key)
    if reserved_user_ids is None:
        return updated_reservations, False

    if user_id is None:
        del updated_reservations[key]
        return updated_reservations, True

    if user_id not in reserved_user_ids:
        return updated_reservations, False

    reserved_user_ids.remove(user_id)
    if not reserved_user_ids:
        del updated_reservations[key]
    return updated_reservations, True


def remove_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int | None = None,
) -> tuple[dict[str, list[int]], list[str], list[str]]:
    updated_reservations = {
        key: list(user_ids) for key, user_ids in reservations.items()
    }
    removed_names: list[str] = []
    missing_names: list[str] = []
    for pokemon_name in pokemon_names:
        updated_reservations, removed = remove_reservation(
            updated_reservations,
            guild_id,
            pokemon_name,
            user_id,
        )
        (removed_names if removed else missing_names).append(pokemon_name)
    return updated_reservations, removed_names, missing_names


def format_remove_confirmation(pokemon_name: str, member_mention: str | None) -> str:
    display_names = ", ".join(
        name[0].upper() + name[1:] for name in pokemon_name.split(", ")
    )
    if member_mention is None:
        return f"{display_names} removed"
    return f"{display_names} removed from {member_mention} Reserves"


def format_reservation_embeds(
    display_name: str,
    pokemon_names: list[str],
) -> list[discord.Embed]:
    heading = f"Pokémon reserved by {display_name}"
    if not pokemon_names:
        return [
            discord.Embed(
                title=heading,
                description="This member has no Pokémon reservations.",
                color=discord.Color.blurple(),
            )
        ]

    pages: list[list[str]] = [[]]
    current_length = 0
    for name in pokemon_names:
        display_pokemon = name[0].upper() + name[1:]
        added_length = len(display_pokemon) + (2 if pages[-1] else 0)
        if current_length + added_length > RESERVATION_EMBED_DESCRIPTION_LIMIT:
            pages.append([])
            current_length = 0
            added_length = len(display_pokemon)
        pages[-1].append(display_pokemon)
        current_length += added_length

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_names in enumerate(pages, start=1):
        embed = discord.Embed(
            title=heading,
            description="\n".join(page_names),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def load_reservations(path: Path) -> dict[str, list[int]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read reserve data from {path}") from error
    if not isinstance(data, dict) or any(
        not isinstance(key, str)
        or not isinstance(user_ids, list)
        or any(
            isinstance(user_id, bool) or not isinstance(user_id, int)
            for user_id in user_ids
        )
        for key, user_ids in data.items()
    ):
        raise ValueError(f"Reserve data in {path} has an invalid format")
    return data


def save_reservations(path: Path, reservations: dict[str, list[int]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(reservations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save reserve data to {path}") from error


class NamingBot(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.openai = AsyncOpenAI(api_key=config.openai_api_key)
        self.image_http: aiohttp.ClientSession | None = None
        self.reserve_path = Path(os.environ.get("RESERVES_FILE", "reserves.json"))
        self.reservations = load_reservations(self.reserve_path)
        self.shinyhunt_path = Path(
            os.environ.get("SHINYHUNTS_FILE", "shinyhunts.json")
        )
        self.shinyhunters = load_reservations(self.shinyhunt_path)

    async def setup_hook(self) -> None:
        self.image_http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "Vivillon-naming/1.0"},
        )

    async def close(self) -> None:
        if self.image_http is not None:
            await self.image_http.close()
        await self.openai.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot and message.author.id != self.config.poketwo_bot_id:
            return
        if (
            self.config.allowed_channel_id is not None
            and message.channel.id != self.config.allowed_channel_id
        ):
            return

        text = message_text(message)
        if message.author.id != self.config.poketwo_bot_id:
            if re.match(r"^v!sh(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_shinyhunt_command(message)
                return
            if re.match(
                r"^v!r\s+(?:add|search|remove|clear)(?:\s|$)",
                message.content,
                re.IGNORECASE,
            ):
                await self.handle_reserve_command(message)
            return

        if SPAWN_PATTERN.search(text):
            await self.handle_spawn(message)

    async def handle_shinyhunt_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Shiny hunts can only be added in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!sh\s*", message.content, re.IGNORECASE):
            pokemon_names = shinyhunt_pokemon_for_user(
                self.shinyhunters,
                message.guild.id,
                message.author.id,
            )
            if pokemon_names:
                response = format_shinyhunt_status(pokemon_names[0])
            else:
                response = "You are not currently Shinyhunting any Pokémon"
            await message.reply(response, mention_author=False)
            return

        pokemon_name = parse_shinyhunt_command(message.content)
        if pokemon_name is None:
            await message.reply(
                "Usage: `v!sh <pokemon>` (one Pokémon per command)",
                mention_author=False,
            )
            return

        updated_shinyhunters = add_shinyhunter(
            self.shinyhunters,
            message.guild.id,
            pokemon_name,
            message.author.id,
        )
        try:
            save_reservations(self.shinyhunt_path, updated_shinyhunters)
        except ValueError:
            logger.exception("Could not save shiny-hunt registrations")
            await message.reply(
                "I couldn't save that shiny hunt. Check the bot logs.",
                mention_author=False,
            )
            return
        self.shinyhunters = updated_shinyhunters
        await message.reply(
            format_shinyhunt_confirmation(pokemon_name),
            mention_author=False,
        )

    async def handle_reserve_command(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            await message.reply(
                "Reserve commands can only be used in a server.",
                mention_author=False,
            )
            return
        if not any(role.id == RESERVE_ROLE_ID for role in message.author.roles):
            await message.reply(
                "You need the designated reserve-manager role to use reserve commands.",
                mention_author=False,
            )
            return

        if re.match(r"^v!r\s+search(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_search(message)
            return
        if re.match(r"^v!r\s+remove(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_remove(message)
            return
        if re.fullmatch(r"v!r\s+clear\s*", message.content, re.IGNORECASE):
            await message.reply(
                "Are you sure you want to clear all reserves?",
                view=ClearReservesView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return
        if re.match(r"^v!r\s+clear(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply(
                "Usage: `v!r clear`",
                mention_author=False,
            )
            return

        parsed_command = parse_reserve_add_command(message.content)
        if parsed_command is None or len(message.mentions) != 1:
            await message.reply(
                "Usage: `v!r add <pokemon>, <pokemon> @member`",
                mention_author=False,
            )
            return

        pokemon_names, target_id = parsed_command
        target = message.mentions[0]
        if target.id != target_id:
            await message.reply(
                "Please mention exactly one server member.",
                mention_author=False,
            )
            return

        updated_reservations = {
            key: list(user_ids) for key, user_ids in self.reservations.items()
        }
        for pokemon_name in pokemon_names:
            key = reservation_key(message.guild.id, pokemon_name)
            user_ids = updated_reservations.setdefault(key, [])
            if target.id not in user_ids:
                user_ids.append(target.id)
        try:
            save_reservations(self.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not save Pokémon reservations")
            await message.reply(
                "I couldn't save that reservation. Check the bot logs.",
                mention_author=False,
            )
            return

        self.reservations = updated_reservations
        display_names = ", ".join(
            name[0].upper() + name[1:] for name in pokemon_names
        )
        await message.reply(
            f"Reserve {display_names} added to {target.mention}",
            mention_author=False,
        )

    async def handle_reserve_remove(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            await message.reply(
                "Reservations can only be removed in a server.",
                mention_author=False,
            )
            return

        parsed_command = parse_reserve_remove_command(message.content)
        if parsed_command is None:
            await message.reply(
                "Usage: `v!r remove <pokemon>[, <pokemon> ...] [@member]`",
                mention_author=False,
            )
            return

        pokemon_names, target_id = parsed_command
        expected_mentions = 1 if target_id is not None else 0
        if len(message.mentions) != expected_mentions:
            await message.reply(
                "Usage: `v!r remove <pokemon>[, <pokemon> ...] [@member]`",
                mention_author=False,
            )
            return
        target = message.mentions[0] if target_id is not None else None
        if target is not None and target.id != target_id:
            await message.reply(
                "Please mention exactly one server member.",
                mention_author=False,
            )
            return

        updated_reservations, removed_names, missing_names = remove_reservations(
            self.reservations,
            message.guild.id,
            pokemon_names,
            target.id if target else None,
        )
        if not removed_names:
            names = ", ".join(pokemon_names)
            await message.reply(
                f"No reservation was found for {names}.",
                mention_author=False,
            )
            return

        try:
            save_reservations(self.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not save Pokémon reservation removal")
            await message.reply(
                "I couldn't save that removal. Check the bot logs.",
                mention_author=False,
            )
            return

        self.reservations = updated_reservations
        response = format_remove_confirmation(
            ", ".join(removed_names),
            target.mention if target else None,
        )
        if missing_names:
            response += f". No reservation was found for {', '.join(missing_names)}"
        await message.reply(response, mention_author=False)

    async def handle_reserve_search(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Reservations can only be searched in a server.",
                mention_author=False,
            )
            return

        match = RESERVE_SEARCH_PATTERN.fullmatch(message.content)
        if match is None or len(message.mentions) != 1:
            await message.reply(
                "Usage: `v!r search @member`",
                mention_author=False,
            )
            return

        target = message.mentions[0]
        if target.id != int(match.group(1)):
            await message.reply(
                "Please mention exactly one server member.",
                mention_author=False,
            )
            return

        pokemon_names = reserved_pokemon_for_user(
            self.reservations,
            message.guild.id,
            target.id,
        )
        embeds = format_reservation_embeds(target.display_name, pokemon_names)
        await message.reply(
            embed=embeds[0],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for embed in embeds[1:]:
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def handle_spawn(self, message: discord.Message) -> None:
        url = image_url(message)
        if not url:
            logger.warning("Pokétwo spawn message %s had no image", message.id)
            return
        if self.image_http is None:
            logger.error("HTTP client was not initialized")
            return

        try:
            name, confidence = await recognize_pokemon(
                url,
                client=self.openai,
                http=self.image_http,
                model=self.config.openai_model,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            logger.exception("Could not recognize spawn in message %s", message.id)
            await message.reply(
                "I couldn't identify that spawn. Check the bot logs for details.",
                mention_author=False,
            )
            return
        except OpenAIError:
            logger.exception("Vision request failed for message %s", message.id)
            await message.reply(
                "I couldn't identify that spawn because the vision request failed.",
                mention_author=False,
            )
            return

        if not name:
            await message.reply(
                "I couldn't confidently identify that Pokémon.",
                mention_author=False,
            )
            return
        reserved_user_ids = (
            self.reservations.get(reservation_key(message.guild.id, name), [])
            if message.guild
            else []
        )
        shinyhunter_user_ids = (
            self.shinyhunters.get(reservation_key(message.guild.id, name), [])
            if message.guild
            else []
        )
        await message.reply(
            format_spawn_reply(
                name,
                confidence,
                self.config.poketwo_bot_id,
                reserved_user_ids,
                shinyhunter_user_ids,
            ),
            mention_author=False,
        )


def clear_guild_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in reservations.items()
        if not key.startswith(guild_prefix)
    }


class ClearReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not any(
                role.id == RESERVE_ROLE_ID for role in interaction.user.roles
            )
        ):
            await interaction.response.send_message(
                "Only the authorized command user can confirm this action.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated_reservations = clear_guild_reservations(
            self.bot.reservations,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not clear Pokémon reservations")
            await interaction.response.send_message(
                "I couldn't clear the reserves. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.reservations = updated_reservations
        await interaction.response.edit_message(
            content="All reserves have been cleared.",
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.edit_message(
            content="Command cancelled",
            view=None,
        )


def main() -> None:
    config = Config.from_environment()
    bot = NamingBot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
