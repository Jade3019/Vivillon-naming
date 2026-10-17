import asyncio
import base64
import json
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

import aiohttp
import discord
from aiohttp import web
from image_match import ImageMatcher
from org_api import OrgReserves, create_app
from openai import AsyncOpenAI, BadRequestError, OpenAIError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vivillon_naming")

SPAWN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bwild\s+(?:pokemon|pok[eé]mon)\b", re.IGNORECASE
)
RESERVE_ROLE_ID: Final[int] = 1532820386511720579
POKETWO_COMMAND_BOT_ID: Final[int] = 716390085896962058
SERVER_ID: Final[int] = 1530949341013868635
SERVER_IDS: Final[frozenset[int]] = frozenset(
    {SERVER_ID, 1543384606630481920}
)
INCENSE_DURATION_SECONDS: Final[int] = 60 * 60
API_STATUS_WINDOW_SECONDS: Final[int] = 5 * 60
API_STATUS_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!api\s*$",
    re.IGNORECASE,
)
SHINYHUNT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!sh\s+(.+?)\s*$",
    re.IGNORECASE,
)
SHINYHUNT_REMOVE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!sh\s+remove\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+add\s+(.+?)\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
RESERVE_SEARCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+search\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+remove\s+(.+?)(?:(?:\s*,\s*|\s+)<@!?(\d+)>)?\s*$",
    re.IGNORECASE,
)
COLLECTION_ADD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!cl\s+add\s+(.+?)\s*$",
    re.IGNORECASE,
)
COLLECTION_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!cl\s+remove\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVATION_EMBED_PAGE_SIZE: Final[int] = 20


def load_pokemon_forms(path: Path) -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load Pokémon form catalog from {path}") from error

    if not isinstance(data, dict) or not isinstance(data.get("forms"), dict):
        raise ValueError(f"Pokémon form catalog at {path} has an invalid format")

    forms: dict[str, list[dict[str, str]]] = {}
    for species_name, entries in data["forms"].items():
        if not isinstance(species_name, str) or not isinstance(entries, list):
            raise ValueError(f"Pokémon form catalog at {path} has an invalid entry")
        validated_entries = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("identifier"), str)
                or not isinstance(entry.get("display_name"), str)
            ):
                raise ValueError(f"Pokémon form catalog at {path} has an invalid form")
            validated_entries.append(
                {
                    "identifier": entry["identifier"],
                    "display_name": entry["display_name"],
                }
            )
        forms[species_name] = validated_entries
    return forms


def normalize_pokemon_alias(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name).casefold()
    return re.sub(r"[\s_-]+", " ", normalized).strip()


def load_single_type_aliases(path: Path, key: str) -> frozenset[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load Pokémon form catalog from {path}") from error

    aliases = data.get(key) if isinstance(data, dict) else None
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) for alias in aliases
    ):
        raise ValueError(f"Pokémon form catalog at {path} has invalid {key} data")
    return frozenset(normalize_pokemon_alias(alias) for alias in aliases)


POKEMON_FORMS: Final[dict[str, list[dict[str, str]]]] = load_pokemon_forms(
    Path(__file__).with_name("pokemon_forms.json")
)
SINGLE_TYPE_FIRE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_fire_aliases",
)
SINGLE_TYPE_NORMAL_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_normal_aliases",
)
SINGLE_TYPE_WATER_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_water_aliases",
)
SINGLE_TYPE_ELECTRIC_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_electric_aliases",
)
SINGLE_TYPE_GRASS_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_grass_aliases",
)
SINGLE_TYPE_ICE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "single_type_ice_aliases",
)
ICE_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "ice_and_fire_type_aliases",
)
ICE_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "ice_and_water_type_aliases",
)
ICE_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "ice_and_electric_type_aliases",
)
NORMAL_AND_ICE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "normal_and_ice_type_aliases",
)
GRASS_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "grass_and_fire_type_aliases",
)
GRASS_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "grass_and_water_type_aliases",
)
GRASS_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "grass_and_normal_type_aliases",
)
GRASS_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "grass_and_electric_type_aliases",
)
NORMAL_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "normal_and_water_type_aliases",
)
WATER_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "water_and_fire_type_aliases",
)
FIRE_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "fire_and_electric_type_aliases",
)
ELECTRIC_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "electric_and_water_type_aliases",
)
ELECTRIC_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "electric_and_normal_type_aliases",
)
FIRE_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    Path(__file__).with_name("pokemon_forms.json"),
    "fire_and_normal_type_aliases",
)

@dataclass(frozen=True)
class Config:
    discord_token: str
    openai_api_key: str | None
    poketwo_bot_id: int
    max_concurrent_vision_requests: int
    openai_model: str
    openai_image_detail: str = "low"

    @classmethod
    def from_environment(cls) -> "Config":
        in_designated_codespace = (
            os.environ.get("CODESPACES") == "true"
            and os.environ.get("CODESPACE_NAME")
            == "bookish-space-xylophone-gx67456vpq4whwpqx"
        )
        # Set ALLOW_EXTERNAL_HOST=true to explicitly authorize another host.
        external_host_allowed = os.environ.get("ALLOW_EXTERNAL_HOST") == "true"
        if not (in_designated_codespace or external_host_allowed):
            raise ValueError(
                "This bot is only authorized in its designated Codespace "
                "(or set ALLOW_EXTERNAL_HOST=true)"
            )

        discord_token = os.environ.get("DISCORD_TOKEN")
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        poketwo_bot_id = os.environ.get("POKETWO_BOT_ID")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN is required")
        openai_api_key = (openai_api_key or "").strip() or None
        if not poketwo_bot_id:
            raise ValueError("POKETWO_BOT_ID is required")

        image_detail = os.environ.get("OPENAI_IMAGE_DETAIL", "low").strip().lower()
        if image_detail not in {"low", "high", "auto"}:
            raise ValueError("OPENAI_IMAGE_DETAIL must be low, high, or auto")
        try:
            poketwo_bot_id = int(poketwo_bot_id)
            max_concurrent_vision_requests = int(
                os.environ.get("MAX_CONCURRENT_VISION_REQUESTS", "200")
            )
            if not 1 <= max_concurrent_vision_requests <= 200:
                raise ValueError
            return cls(
                discord_token=discord_token,
                openai_api_key=openai_api_key,
                poketwo_bot_id=poketwo_bot_id,
                max_concurrent_vision_requests=max_concurrent_vision_requests,
                openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                openai_image_detail=image_detail,
            )
        except ValueError as error:
            raise ValueError(
                "POKETWO_BOT_ID must be a positive numeric Discord ID; "
                "MAX_CONCURRENT_VISION_REQUESTS must be an integer from 1 to 200"
            ) from error


def message_text(message: discord.Message) -> str:
    parts = [message.content]
    for embed in message.embeds:
        parts.extend((embed.title or "", embed.description or ""))
        parts.extend(f"{field.name}: {field.value}" for field in embed.fields)
    return unicodedata.normalize(
        "NFC", "\n".join(part for part in parts if part)
    )


def poketwo_incense_action(content: str, poketwo_bot_id: int) -> str | None:
    mention = rf"<@!?{poketwo_bot_id}>"
    match = re.search(
        rf"(?:^|\s){mention}\s+(buy\s+incense|stopincense)\b",
        content,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return "start" if match.group(1).casefold().startswith("buy") else "stop"


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


def is_image_test_command(content: str) -> bool:
    return re.fullmatch(r"v!test\s*", content, re.IGNORECASE) is not None


class NoMatchError(Exception):
    pass


async def download_image(
    http: aiohttp.ClientSession, url: str
) -> tuple[bytes, str]:
    async with http.get(url) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError(f"Spawn image URL returned non-image content: {content_type}")
        image_bytes = await response.read()
    if not image_bytes:
        raise ValueError("Spawn image was empty")
    return image_bytes, content_type


async def recognize_pokemon(
    url: str,
    *,
    client: AsyncOpenAI | None,
    http: aiohttp.ClientSession,
    model: str,
    detail: str = "low",
    matcher: ImageMatcher | None = None,
) -> tuple[str, float]:
    downloaded: tuple[bytes, str] | None = None
    if matcher is not None and matcher.entries:
        downloaded = await download_image(http, url)
        found = await asyncio.to_thread(matcher.match, downloaded[0])
        if found is not None:
            logger.info("Matched %s from reference images (%d votes)", *found)
            return found[0], 100.0

    if client is None:
        raise NoMatchError("No reference image matched and OpenAI is not configured")

    if downloaded is None:
        # Letting OpenAI fetch the image skips our own download and base64 step.
        try:
            return await request_prediction(
                url, client=client, model=model, detail=detail
            )
        except BadRequestError:
            logger.info("OpenAI could not fetch the image URL; uploading it instead")
            downloaded = await download_image(http, url)

    image_bytes, content_type = downloaded
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    return await request_prediction(
        f"data:{content_type};base64,{encoded_image}",
        client=client,
        model=model,
        detail=detail,
    )


async def request_prediction(
    image_ref: str,
    *,
    client: AsyncOpenAI,
    model: str,
    detail: str,
) -> tuple[str, float]:
    result = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        max_completion_tokens=60,
        messages=[
            {
                "role": "system",
                "content": (
                    "Identify the Pokémon species shown in this Pokétwo wild-spawn "
                    "image. The species may be any Pokémon in the National Pokédex "
                    "through #1026. Inspect the Pokémon itself and compare its overall "
                    "silhouette, body proportions, face, appendages, colors, markings, "
                    "and distinctive accessories. Use multiple visible traits to "
                    "identify it; do not rely on a single color, type, pose, background, "
                    "or habitat. Pay particular attention to features that separate "
                    "similar species and neighboring evolutions. Identify a regional "
                    "variant or alternate forme only when its visible features support "
                    "that specific form; do not infer details hidden by the image. "
                    "Choose the closest match to the visible evidence, and lower the "
                    "confidence when important features are unclear or obscured. "
                    "Return only the single most likely Pokémon's Pokétwo-accepted "
                    "English name. Never return a description, reasoning, multiple "
                    "candidates, alternate names, aliases, or a list. Estimate "
                    "confidence in that exact identification as a percentage from 0 "
                    "to 100 with up to two decimal places; confidence should reflect "
                    "how clearly the visible traits support the chosen species and "
                    "form. Return JSON only, "
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
                            "url": image_ref,
                            "detail": detail,
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
    if len(name) > 60 or (
        name and not is_valid_pokemon_name(name) and not is_missingno_name(name)
    ):
        raise ValueError("Vision model returned an invalid Pokémon name")
    return name, float(confidence)


def is_valid_pokemon_name(name: str) -> bool:
    allowed_punctuation = " .'-:♀♂"
    return bool(name) and any(char.isalpha() for char in name) and all(
        unicodedata.category(char)[0] in {"L", "M", "N"}
        or char in allowed_punctuation
        for char in name
    )


def is_missingno_name(name: str) -> bool:
    return name.strip().casefold().rstrip(".") in {"missingno", "???"}


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
    collection_user_ids: list[int] | None = None,
) -> str:
    command = format_catch_command(poketwo_bot_id, name)
    lines = [format_guess(name, confidence)]
    lines.extend(
        format_spawn_mention_lines(
            reserved_user_ids,
            shinyhunter_user_ids,
            collection_user_ids,
        )
    )
    lines.append(f"**Copy Here >** `{command}`")
    return "\n".join(lines)


def is_fire_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES
        or normalized_name in WATER_AND_FIRE_TYPE_ALIASES
        or normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in GRASS_AND_FIRE_TYPE_ALIASES
        or normalized_name in ICE_AND_FIRE_TYPE_ALIASES
        or is_single_type_fire_pokemon(name)
    )


def is_water_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in NORMAL_AND_WATER_TYPE_ALIASES
        or normalized_name in WATER_AND_FIRE_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES
        or normalized_name in GRASS_AND_WATER_TYPE_ALIASES
        or normalized_name in ICE_AND_WATER_TYPE_ALIASES
        or is_single_type_water_pokemon(name)
    )


def is_normal_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in NORMAL_AND_ICE_TYPE_ALIASES
        or normalized_name in NORMAL_AND_WATER_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES
        or normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES
        or is_single_type_normal_pokemon(name)
    )


def is_electric_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES
        or is_single_type_electric_pokemon(name)
    )


def is_grass_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in GRASS_AND_FIRE_TYPE_ALIASES
        or normalized_name in GRASS_AND_WATER_TYPE_ALIASES
        or normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES
        or is_single_type_grass_pokemon(name)
    )


def is_ice_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in ICE_AND_FIRE_TYPE_ALIASES
        or normalized_name in ICE_AND_WATER_TYPE_ALIASES
        or normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in NORMAL_AND_ICE_TYPE_ALIASES
        or is_single_type_ice_pokemon(name)
    )


def fire_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in WATER_AND_FIRE_TYPE_ALIASES:
        return None
    if normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_FIRE_TYPE_ALIASES:
        return None
    if normalized_name in ICE_AND_FIRE_TYPE_ALIASES:
        return None
    return None


def water_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in ICE_AND_WATER_TYPE_ALIASES:
        return None
    return None


def normal_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in NORMAL_AND_ICE_TYPE_ALIASES:
        return None
    if normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        return "water_type.png"
    if normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        return None
    return None


def electric_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES:
        return None
    return None


def format_custom_type_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    include_fire: bool = False,
    include_water: bool = False,
    include_normal: bool = False,
    include_electric: bool = False,
    include_grass: bool = False,
    include_ice: bool = False,
) -> str:
    lines = format_spawn_mention_lines(
        reserved_user_ids,
        shinyhunter_user_ids,
        collection_user_ids,
    )
    emoji_by_type = {
        "fire": "<:fire:1560301436074729532>",
        "water": "<:water:1560303864094130357>",
        "normal": "<:Normal:1560305235279482930>",
        "electric": "<:Electric:1560306053164572732>",
        "grass": "<:grass:1560307079896502282>",
        "ice": "<:Ice:1560307867200782386>",
    }
    included_types = {
        type_name
        for type_name, included in (
            ("fire", include_fire),
            ("water", include_water),
            ("normal", include_normal),
            ("electric", include_electric),
            ("grass", include_grass),
            ("ice", include_ice),
        )
        if included
    }
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        type_order = ("fire", "normal")
    elif normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        type_order = ("normal", "water")
    elif normalized_name in WATER_AND_FIRE_TYPE_ALIASES:
        type_order = ("water", "fire")
    elif normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("fire", "electric")
    elif normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES:
        type_order = ("electric", "water")
    elif normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES:
        type_order = ("electric", "normal")
    elif normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("grass", "electric")
    elif normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("ice", "electric")
    elif normalized_name in ICE_AND_FIRE_TYPE_ALIASES:
        type_order = ("ice", "fire")
    elif normalized_name in ICE_AND_WATER_TYPE_ALIASES:
        type_order = ("ice", "water")
    elif normalized_name in NORMAL_AND_ICE_TYPE_ALIASES:
        type_order = ("normal", "ice")
    elif normalized_name in GRASS_AND_FIRE_TYPE_ALIASES:
        type_order = ("grass", "fire")
    elif normalized_name in GRASS_AND_WATER_TYPE_ALIASES:
        type_order = ("grass", "water")
    elif normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES:
        type_order = ("grass", "normal")
    else:
        type_order = ("fire", "water", "normal", "electric", "grass", "ice")
    type_emojis = [
        emoji_by_type[type_name]
        for type_name in type_order
        if type_name in included_types
    ]
    lines.append(f"## {' '.join(type_emojis)} {format_guess(name, confidence)}")
    lines.append(
        f"**Copy Here >** `{format_catch_command(poketwo_bot_id, name)}`"
    )
    return "\n".join(lines)


def format_spawn_mention_lines(
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
) -> list[str]:
    if reserved_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in reserved_user_ids)
        return [f"Reserved: {mentions}"]
    lines = []
    if shinyhunter_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in shinyhunter_user_ids)
        lines.append(f"Shinyhunt: {mentions}")
    if collection_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in collection_user_ids)
        lines.append(f"Collection: {mentions}")
    return lines


def is_single_type_pokemon(name: str, type_aliases: frozenset[str]) -> bool:
    return normalize_pokemon_alias(name) in type_aliases


def is_single_type_fire_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_FIRE_ALIASES)


def is_single_type_normal_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_NORMAL_ALIASES)


def is_single_type_water_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_WATER_ALIASES)


def is_single_type_electric_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_ELECTRIC_ALIASES)


def is_single_type_grass_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_GRASS_ALIASES)


def is_single_type_ice_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_ICE_ALIASES)


def type_icon_filename_for_pokemon(name: str) -> str | None:
    if normalize_pokemon_alias(name) in ICE_AND_WATER_TYPE_ALIASES:
        return "ice_water_type_icons.png"
    if is_single_type_water_pokemon(name):
        return "water_type.png"
    if is_single_type_ice_pokemon(name):
        return "ice_type.png"
    return None


def format_type_spawn_embed(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    icon_filename: str,
) -> discord.Embed:
    embed = discord.Embed(
        description=f"`{format_catch_command(poketwo_bot_id, name)}`"
    )
    embed.set_author(
        name=format_guess(name, confidence),
        icon_url=f"attachment://{icon_filename}",
    )
    return embed


SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/{}.png"
)


@lru_cache(maxsize=1)
def load_sprite_ids() -> dict[str, int]:
    path = Path(__file__).with_name("pokemon_sprites.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sprite_url_for_pokemon(name: str) -> str | None:
    sprite_id = load_sprite_ids().get(name)
    return SPRITE_URL.format(sprite_id) if sprite_id else None


def format_pc_catch_embed(name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Catch {name}",
        description=(
            f"Copy Below\n"
            f"```\n{format_catch_command(POKETWO_COMMAND_BOT_ID, name)}\n```"
        ),
    )
    sprite_url = sprite_url_for_pokemon(name)
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)
    return embed


def reservation_key(guild_id: int, pokemon_name: str) -> str:
    normalized_name = unicodedata.normalize("NFC", pokemon_name).casefold()
    return f"{guild_id}:{normalized_name}"


def all_forms_reservation_key(guild_id: int, pokemon_name: str) -> str:
    normalized_name = unicodedata.normalize("NFC", pokemon_name).casefold()
    return f"{guild_id}:*:{normalized_name}"


def reservation_key_for_command(guild_id: int, pokemon_name: str) -> str:
    all_forms_prefix = "all "
    if pokemon_name.casefold().startswith(all_forms_prefix):
        base_name = pokemon_name[len(all_forms_prefix) :].strip()
        return all_forms_reservation_key(guild_id, base_name)
    return reservation_key(guild_id, pokemon_name)


def pokemon_matches_all_forms_reservation(
    pokemon_name: str,
    reserved_name: str,
) -> bool:
    pokemon_name = unicodedata.normalize("NFC", pokemon_name).casefold()
    reserved_name = unicodedata.normalize("NFC", reserved_name).casefold()
    if is_regional_form_name(pokemon_name):
        return False
    if pokemon_name == reserved_name:
        return True
    for form_index, form in enumerate(POKEMON_FORMS.get(reserved_name, [])):
        aliases = pokemon_form_reservation_aliases(
            reserved_name,
            form,
            is_default=form_index == 0,
        )
        if pokemon_name in {
            unicodedata.normalize("NFC", alias).casefold()
            for alias in aliases
        }:
            return True
    if pokemon_name.startswith(
        tuple(f"{reserved_name}{separator}" for separator in (" ", "-", "(", ":", "["))
    ):
        return True
    # Forms named with a prefix, such as "Mega Marshadow" or "Zenith Marshadow".
    return " " not in reserved_name and reserved_name in re.split(
        r"[\s()\-:\[\]]+", pokemon_name
    )


def reserved_user_ids_for_pokemon(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[int]:
    user_ids = set(reservations.get(reservation_key(guild_id, pokemon_name), []))
    wildcard_prefix = f"{guild_id}:*:"
    for key, reserved_user_ids in reservations.items():
        if not key.startswith(wildcard_prefix):
            continue
        reserved_name = key.removeprefix(wildcard_prefix)
        if pokemon_matches_all_forms_reservation(pokemon_name, reserved_name):
            user_ids.update(reserved_user_ids)
    return sorted(user_ids)


def parse_shinyhunt_command(content: str) -> str | None:
    match = SHINYHUNT_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None
    return parse_shinyhunt_name(match.group(1))


def parse_shinyhunt_remove_command(content: str) -> str | None:
    match = SHINYHUNT_REMOVE_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None
    return parse_shinyhunt_name(match.group(1))


def parse_shinyhunt_name(value: str) -> str | None:
    pokemon_name = unicodedata.normalize("NFC", value.strip())
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
    user_ids = updated_shinyhunters.setdefault(
        reservation_key_for_command(guild_id, pokemon_name),
        [],
    )
    if user_id not in user_ids:
        user_ids.append(user_id)
    return updated_shinyhunters


def remove_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int,
) -> tuple[dict[str, list[int]], bool]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    key = reservation_key_for_command(guild_id, pokemon_name)
    user_ids = updated_shinyhunters.get(key)
    if user_ids is None or user_id not in user_ids:
        return updated_shinyhunters, False

    user_ids.remove(user_id)
    if not user_ids:
        del updated_shinyhunters[key]
    return updated_shinyhunters, True


def format_shinyhunt_status(pokemon_name: str) -> str:
    return f"You are currently shinyhunting {format_shinyhunt_name(pokemon_name)}"


def format_shinyhunt_confirmation(pokemon_name: str) -> str:
    return f"You are now shinyhunting {format_shinyhunt_name(pokemon_name)}"


def format_shinyhunt_name(pokemon_name: str) -> str:
    normalized_name = pokemon_name.casefold()
    if normalized_name.startswith("all "):
        return f"all forms of {normalized_name[4:].strip()}"
    if normalized_name.startswith("*:"):
        return f"all forms of {normalized_name[2:]}"
    return normalized_name


def shinyhunt_pokemon_for_user(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    pokemon_names = []
    for key, user_ids in shinyhunters.items():
        if not key.startswith(guild_prefix) or user_id not in user_ids:
            continue
        name = key.removeprefix(guild_prefix)
        pokemon_names.append(f"all {name[2:]}" if name.startswith("*:") else name)
    return sorted(pokemon_names)


def shinyhunter_user_ids_for_pokemon(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[int]:
    return reserved_user_ids_for_pokemon(shinyhunters, guild_id, pokemon_name)


def parse_collection_add_command(content: str) -> list[str] | None:
    return parse_collection_pokemon_command(content, COLLECTION_ADD_PATTERN)


def parse_collection_pokemon_command(
    content: str,
    pattern: re.Pattern[str],
) -> list[str] | None:
    match = pattern.fullmatch(content)
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
    for pokemon_name in pokemon_names:
        normalized_name = pokemon_name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(pokemon_name)
            seen_names.add(normalized_name)
    return unique_names


def add_collection_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> dict[str, list[int]]:
    updated_collections = {
        key: list(user_ids) for key, user_ids in collections.items()
    }
    for pokemon_name in pokemon_names:
        user_ids = updated_collections.setdefault(
            reservation_key(guild_id, pokemon_name),
            [],
        )
        if user_id not in user_ids:
            user_ids.append(user_id)
    return updated_collections


def collection_pokemon_for_user(
    collections: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    return sorted(
        key.removeprefix(guild_prefix)
        for key, user_ids in collections.items()
        if key.startswith(guild_prefix) and user_id in user_ids
    )


def split_collection_add_names(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> tuple[list[str], list[str]]:
    existing_names = {
        name.casefold()
        for name in collection_pokemon_for_user(collections, guild_id, user_id)
    }
    already_added = [
        name for name in pokemon_names if name.casefold() in existing_names
    ]
    new_names = [
        name for name in pokemon_names if name.casefold() not in existing_names
    ]
    return new_names, already_added


def format_collection_add_confirmation(
    added_names: list[str],
    already_added_names: list[str],
) -> str:
    lines = []
    if added_names:
        display_names = ", ".join(
            name[0].upper() + name[1:] for name in added_names
        )
        lines.append(f"Added {display_names} to your collection.")
    if already_added_names:
        display_names = ", ".join(
            name[0].upper() + name[1:] for name in already_added_names
        )
        lines.append(f"{display_names} already added to your collection.")
    return " ".join(lines)


def collection_user_ids_for_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[int]:
    return sorted(set(collections.get(reservation_key(guild_id, pokemon_name), [])))


def remove_collection_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> tuple[dict[str, list[int]], list[str], list[str]]:
    updated_collections = {
        key: list(user_ids) for key, user_ids in collections.items()
    }
    removed_names: list[str] = []
    missing_names: list[str] = []
    for pokemon_name in pokemon_names:
        key = reservation_key(guild_id, pokemon_name)
        user_ids = updated_collections.get(key)
        if user_ids is None or user_id not in user_ids:
            missing_names.append(pokemon_name)
            continue
        user_ids.remove(user_id)
        removed_names.append(pokemon_name)
        if not user_ids:
            del updated_collections[key]
    return updated_collections, removed_names, missing_names


def clear_user_collection(
    collections: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    updated_collections: dict[str, list[int]] = {}
    for key, user_ids in collections.items():
        remaining_user_ids = list(user_ids)
        if key.startswith(guild_prefix) and user_id in remaining_user_ids:
            remaining_user_ids.remove(user_id)
        if remaining_user_ids:
            updated_collections[key] = remaining_user_ids
    return updated_collections


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
    names = []
    for key, user_ids in reservations.items():
        if not key.startswith(guild_prefix) or user_id not in user_ids:
            continue
        name = key.removeprefix(guild_prefix)
        names.extend(format_reserved_pokemon_names(name))
    return sorted(set(names))


def remove_reservation(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int | None = None,
) -> tuple[dict[str, list[int]], bool]:
    updated_reservations = {
        key: list(user_ids) for key, user_ids in reservations.items()
    }
    key = reservation_key_for_command(guild_id, pokemon_name)
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


EXCHANGE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+(?:e|exchange)\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
EXCHANGE_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"<@!?(\d+)>\s*[-–—:]\s*(.+)"
)


def parse_exchange_list(text: str) -> list[tuple[int, list[str]]]:
    transfers: list[tuple[int, list[str]]] = []
    for line in text.splitlines():
        match = EXCHANGE_LINE_PATTERN.search(line)
        if match is None:
            continue
        names: list[str] = []
        for raw_name in match.group(2).split(","):
            name = unicodedata.normalize("NFC", raw_name.strip())
            if (
                name
                and len(name) <= 60
                and is_valid_pokemon_name(name)
                and name.casefold() not in {n.casefold() for n in names}
            ):
                names.append(name)
        if names:
            transfers.append((int(match.group(1)), names))
    return transfers


REGIONAL_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:alola|alolan|galar|galarian|hisui|hisuian|paldea|paldean)\b",
    re.IGNORECASE,
)


def pokemon_matches_exchange_all_forms(pokemon_name: str, base_name: str) -> bool:
    # Exchanges treat "all <pokemon>" as every form, regional forms included.
    if pokemon_matches_all_forms_reservation(pokemon_name, base_name):
        return True
    stripped_name = " ".join(REGIONAL_MARKER_PATTERN.sub(" ", pokemon_name).split())
    return bool(stripped_name) and pokemon_matches_all_forms_reservation(
        stripped_name, base_name
    )


def exchange_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
    source_id: int,
    transfers: list[tuple[int, list[str]]],
) -> tuple[dict[str, list[int]], list[tuple[int, str]], list[tuple[int, str]]]:
    updated = {key: list(user_ids) for key, user_ids in reservations.items()}
    moved: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    for recipient_id, names in transfers:
        for name in names:
            keys = [reservation_key_for_command(guild_id, name)]
            if name.casefold().startswith("all "):
                base_name = name[4:].strip()
                prefix = f"{guild_id}:"
                keys.extend(
                    key
                    for key in updated
                    if key.startswith(prefix)
                    and not key.startswith(f"{prefix}*:")
                    and key not in keys
                    and pokemon_matches_exchange_all_forms(
                        key.removeprefix(prefix), base_name
                    )
                )
            held_keys = [
                key for key in keys if source_id in updated.get(key, [])
            ]
            if recipient_id == source_id or not held_keys:
                skipped.append((recipient_id, name))
                continue
            for key in held_keys:
                user_ids = updated[key]
                user_ids.remove(source_id)
                if recipient_id not in user_ids:
                    user_ids.append(recipient_id)
            moved.append((recipient_id, name))
    return updated, moved, skipped


def format_exchange_embed(
    reservations: dict[str, list[int]],
    guild_id: int,
    source_id: int,
    transfers: list[tuple[int, list[str]]],
    skipped: list[tuple[int, str]],
) -> discord.Embed:
    lines = [
        f"You want to exchange from <@{source_id}> to those users:",
        "",
        *(
            f"<@{recipient_id}> - "
            + ", ".join(
                form_name
                for name in names
                for form_name in (
                    all_forms_display_names(name[4:].strip())
                    if name.casefold().startswith("all ")
                    else []
                )
                or [name]
            )
            for recipient_id, names in transfers
        ),
    ]
    if skipped:
        missing = list(dict.fromkeys(name for _, name in skipped))
        holders: list[int] = []
        for name in missing:
            key = reservation_key_for_command(guild_id, name)
            for user_id in reservations.get(key, []):
                if user_id != source_id and user_id not in holders:
                    holders.append(user_id)
        lines.append("")
        lines.append(
            f"-# <@{source_id}> doesn't have reserved: {', '.join(missing)}"
        )
        if holders:
            lines.append(
                "-# Do you mean " + ", ".join(f"<@{user_id}>" for user_id in holders) + "?"
            )
    return discord.Embed(
        title="Exchange reserves",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )


def format_remove_confirmation(pokemon_name: str, member_mention: str | None) -> str:
    display_names = ", ".join(
        (
            f"All forms of {name[len('all '):]}"
            if name.casefold().startswith("all ")
            else name[0].upper() + name[1:]
        )
        for name in pokemon_name.split(", ")
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

    display_names = [name[0].upper() + name[1:] for name in pokemon_names]
    pages = [
        display_names[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(display_names), RESERVATION_EMBED_PAGE_SIZE)
    ]

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


def format_collection_embeds(pokemon_names: list[str]) -> list[discord.Embed]:
    title = "Your Pokémon Collection"
    if not pokemon_names:
        return [
            discord.Embed(
                title=title,
                description="You have no Pokémon in your collection yet.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        pokemon_names[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(pokemon_names), RESERVATION_EMBED_PAGE_SIZE)
    ]
    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_names in enumerate(pages, start=1):
        embed = discord.Embed(
            title=title,
            description="\n".join(page_names),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def format_server_reservation_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
) -> list[discord.Embed]:
    guild_prefix = f"{guild_id}:"
    entries = sorted(
        (
            f"{pokemon_name} <@{user_id}>"
            for key, user_ids in reservations.items()
            if key.startswith(guild_prefix)
            for pokemon_name in format_reserved_pokemon_names(
                key.removeprefix(guild_prefix)
            )
            for user_id in set(user_ids)
        ),
        key=str.casefold,
    )
    if not entries:
        return [
            discord.Embed(
                title="Server Pokémon Reserves",
                description="There are no Pokémon reservations in this server.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title="Server Pokémon Reserves",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def all_forms_display_names(species_name: str) -> list[str]:
    species_name = unicodedata.normalize("NFC", species_name).casefold()
    forms = POKEMON_FORMS.get(species_name, [])
    display_names = [form["display_name"] for form in forms]
    names: list[str] = []
    for form, display_name in zip(forms, display_names):
        name = display_name
        if display_names.count(display_name) > 1:
            suffix = form["identifier"].removeprefix(f"{species_name}-")
            name = f"{suffix.replace('-', ' ')} {species_name}"
        if name not in names:
            names.append(name)
    return names


def format_reserved_pokemon_names(stored_name: str) -> list[str]:
    if stored_name.startswith("*:"):
        species_name = stored_name.removeprefix("*:")
        return all_forms_display_names(species_name) or [
            f"all forms of {species_name}"
        ]
    return [stored_name]


def format_reserved_pokemon_name(stored_name: str) -> str:
    return ", ".join(format_reserved_pokemon_names(stored_name))


def format_pokemon_reserver_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[discord.Embed]:
    user_ids = reserved_user_ids_for_pokemon(
        reservations,
        guild_id,
        pokemon_name,
    )
    if not user_ids:
        return [
            discord.Embed(
                title=f"Reserve search: {pokemon_name}",
                description=f"No one has {pokemon_name} reserved.",
                color=discord.Color.blurple(),
            )
        ]

    entries = [f"{pokemon_name} <@{user_id}>" for user_id in user_ids]
    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title=f"Reserve search: {pokemon_name}",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def format_all_forms_reservation_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[discord.Embed]:
    base_name = unicodedata.normalize("NFC", pokemon_name).casefold()
    guild_prefix = f"{guild_id}:"
    wildcard_key = all_forms_reservation_key(guild_id, base_name)
    wildcard_user_ids = set(reservations.get(wildcard_key, []))
    form_definitions = POKEMON_FORMS.get(base_name, [])
    known_alias_keys: set[str] = set()
    entries: list[str] = []
    for form_index, form in enumerate(form_definitions):
        aliases = pokemon_form_reservation_aliases(
            base_name,
            form,
            is_default=form_index == 0,
        )
        alias_keys = {
            reservation_key(guild_id, alias)
            for alias in aliases
        }
        known_alias_keys.update(alias_keys)
        form_user_ids = set(wildcard_user_ids)
        for alias_key in alias_keys:
            form_user_ids.update(reservations.get(alias_key, []))
        if form_user_ids:
            entries.extend(
                f"{form['display_name']} <@{user_id}>"
                for user_id in sorted(form_user_ids)
            )
        else:
            entries.append(form["display_name"])

    for key, user_ids in reservations.items():
        if (
            not key.startswith(guild_prefix)
            or key.startswith(f"{guild_id}:*:")
            or key in known_alias_keys
        ):
            continue
        reserved_name = key.removeprefix(guild_prefix)
        if (
            pokemon_matches_all_forms_reservation(reserved_name, base_name)
            and not is_regional_form_name(reserved_name)
        ):
            entries.extend(
                f"{reserved_name} <@{user_id}>"
                for user_id in sorted(set(user_ids) | wildcard_user_ids)
            )

    if not form_definitions and not entries and wildcard_user_ids:
        entries = [
            f"{format_reserved_pokemon_name(f'*:{base_name}')} <@{user_id}>"
            for user_id in sorted(wildcard_user_ids)
        ]
    elif not entries:
        return [
            discord.Embed(
                title=f"Reserve search: all forms of {pokemon_name}",
                description=f"No forms of {pokemon_name} are reserved.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]
    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title=f"Reserve search: all forms of {pokemon_name}",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def pokemon_form_reservation_aliases(
    species_name: str,
    form: dict[str, str],
    *,
    is_default: bool,
) -> set[str]:
    identifier = form["identifier"]
    display_name = form["display_name"]
    aliases = {identifier, identifier.replace("-", " "), display_name}
    if identifier.startswith(f"{species_name}-"):
        suffix = identifier.removeprefix(f"{species_name}-")
        aliases.update(
            {
                f"{species_name} {suffix}",
                f"{species_name} ({suffix})",
                f"{suffix} {species_name}",
            }
        )
    if is_default:
        aliases.add(species_name)
    return aliases


def is_regional_form_name(name: str) -> bool:
    normalized_name = unicodedata.normalize("NFC", name).casefold()
    name_parts = set(re.split(r"[\s()\-]+", normalized_name))
    if "cap" in name_parts:
        name_parts.discard("alola")
    regional_markers = {
        "alola",
        "alolan",
        "galar",
        "galarian",
        "hisui",
        "hisuian",
        "paldea",
        "paldean",
    }
    return bool(regional_markers.intersection(name_parts))


class ReservationPagesView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], guild_id: int) -> None:
        super().__init__(timeout=300)
        self.embeds = embeds
        self.guild_id = guild_id
        self.current_page = 0
        self.message: discord.Message | None = None
        self.update_buttons()

    def update_buttons(self) -> None:
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if child.custom_id == "reserve_pages:previous":
                child.disabled = self.current_page == 0
            elif child.custom_id == "reserve_pages:next":
                child.disabled = self.current_page == len(self.embeds) - 1

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable expired reserve-page buttons")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These reserve pages can only be used in their original server.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        custom_id="reserve_pages:previous",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page],
            view=self,
        )

    @discord.ui.button(
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="reserve_pages:next",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page],
            view=self,
        )


RESERVE_LIST_CACHE: Final[OrderedDict[int, list[str]]] = OrderedDict()
MENTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"<@!?(\d+)>")
GRAB_PAGE_CHARS: Final[int] = 3800


def remember_reserve_list(message_id: int, embeds: list[discord.Embed]) -> None:
    RESERVE_LIST_CACHE[message_id] = [
        embed.description for embed in embeds if embed.description
    ]
    while len(RESERVE_LIST_CACHE) > 300:
        RESERVE_LIST_CACHE.popitem(last=False)


def load_known_pokemon_names() -> list[str]:
    names: set[str] = {"Missingno"}
    try:
        data = json.loads(
            Path(__file__).with_name("pokemon_names.json").read_text(encoding="utf-8")
        )
        names.update(name for name in data if isinstance(name, str))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load pokemon_names.json; v!grab will be limited")
    for forms in POKEMON_FORMS.values():
        names.update(form["display_name"] for form in forms)
    names.update(POKEMON_FORMS)
    return sorted(
        (name.replace("’", "'") for name in names), key=len, reverse=True
    )


GRAB_NAME_PREFIXES: Final[str] = (
    r"(?:(?:all\s+forms\s+of|all|mega|alolan|galarian|hisuian|paldean|gmax|"
    r"gigantamax|primal)\s+)*"
)
GRAB_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w'])"
    + GRAB_NAME_PREFIXES
    + "(?:"
    + "|".join(re.escape(name) for name in load_known_pokemon_names())
    + r")(?![\w'])",
    re.IGNORECASE,
)


def parse_grab_entries(texts: list[str]) -> list[tuple[str, list[int]]]:
    entries: list[tuple[str, list[int]]] = []
    for text in texts:
        for line in text.replace("’", "'").splitlines():
            user_ids = list(
                dict.fromkeys(int(user_id) for user_id in MENTION_PATTERN.findall(line))
            )
            for match in GRAB_NAME_PATTERN.finditer(MENTION_PATTERN.sub(" ", line)):
                name = " ".join(unicodedata.normalize("NFC", match.group()).split())
                if name.casefold().startswith("all forms of "):
                    name = "all " + name[len("all forms of ") :]
                entries.append((name, list(user_ids)))
    return entries


def grab_entry_name(name: str, all_forms: bool) -> str:
    if (
        all_forms
        and not name.casefold().startswith("all ")
        and len(POKEMON_FORMS.get(name.casefold(), [])) > 1
    ):
        return f"all {name}"
    return name


def build_grab_lines(
    entries: list[tuple[str, list[int]]],
    *,
    ordered: bool,
    all_forms: bool,
    emojis: list[str],
) -> list[str]:
    rows = [(grab_entry_name(name, all_forms), ids) for name, ids in entries]
    if ordered:
        rows.sort(key=lambda row: row[0].casefold().removeprefix("all "))
    lines: list[str] = []
    for index, (name, user_ids) in enumerate(rows):
        line = name[0].upper() + name[1:]
        if emojis:
            line = f"{emojis[index % len(emojis)]} {line}"
        lines.append(line)
    return lines


def paginate_grab_lines(
    lines: list[str], limit: int = GRAB_PAGE_CHARS
) -> list[str]:
    pages: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        if current and length + len(line) + 1 > limit:
            pages.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        pages.append("\n".join(current))
    return pages or ["No Pokémon."]


def grab_reserve_pairs(
    entries: list[tuple[str, list[int]]],
    all_forms: bool,
) -> list[tuple[str, int]]:
    return [
        (grab_entry_name(name, all_forms), user_id)
        for name, user_ids in entries
        for user_id in user_ids
    ]


def grab_display_name(name: str) -> str:
    if name.casefold().startswith("all "):
        return f"all forms of {name[4:]}".capitalize()
    return name[0].upper() + name[1:]


def add_reservations_bulk(
    reservations: dict[str, list[int]],
    guild_id: int,
    pairs: list[tuple[str, int]],
) -> dict[str, list[int]]:
    updated = {key: list(user_ids) for key, user_ids in reservations.items()}
    for name, user_id in pairs:
        user_ids = updated.setdefault(reservation_key_for_command(guild_id, name), [])
        if user_id not in user_ids:
            user_ids.append(user_id)
    return updated


async def reply_with_reservation_embeds(
    message: discord.Message,
    embeds: list[discord.Embed],
) -> None:
    view = (
        ReservationPagesView(embeds, message.guild.id)
        if len(embeds) > 1 and message.guild is not None
        else None
    )
    response = await message.reply(
        embed=embeds[0],
        view=view,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    if view is not None:
        view.message = response
    remember_reserve_list(response.id, embeds)


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
        self.openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=config.openai_api_key, max_retries=1, timeout=10.0)
            if config.openai_api_key
            else None
        )
        self.vision_semaphore = asyncio.Semaphore(
            config.max_concurrent_vision_requests
        )
        self.image_http: aiohttp.ClientSession | None = None
        self.image_matcher = ImageMatcher(
            Path(os.environ.get("IMAGE_BANK_FILE", "image_bank.npz"))
        )
        self.handled_spawn_ids: dict[int, None] = {}
        self.muted_poketwo_channels: set[int] = set()
        self.incense_path = Path(
            os.environ.get("INCENSE_TRACKING_FILE", "incenses.json")
        )
        self.active_incenses = self.load_active_incenses()
        self.pokemon_named_count = 0
        self.failed_recognition_count = 0
        self.active_vision_requests = 0
        self.pending_vision_requests = 0
        self.recognition_durations: deque[tuple[float, float, float]] = deque(
            maxlen=1000
        )
        self.org_runner: web.AppRunner | None = None
        self.reserve_path = Path(os.environ.get("RESERVES_FILE", "reserves.json"))
        self.reservations = load_reservations(self.reserve_path)
        self.shinyhunt_path = Path(
            os.environ.get("SHINYHUNTS_FILE", "shinyhunts.json")
        )
        self.shinyhunters = load_reservations(self.shinyhunt_path)
        self.collection_path = Path(
            os.environ.get("COLLECTIONS_FILE", "collections.json")
        )
        self.collections = load_reservations(self.collection_path)

    def org_add_reserve(self, name: str, user_id: int) -> None:
        guild_id = int(os.environ["ORG_GUILD_ID"])
        updated = add_reservations_bulk(
            self.reservations, guild_id, [(name, user_id)]
        )
        save_reservations(self.reserve_path, updated)
        self.reservations = updated

    def org_remove_reserve(self, name: str, user_id: int) -> bool:
        guild_id = int(os.environ["ORG_GUILD_ID"])
        updated, removed = remove_reservation(
            self.reservations, guild_id, name, user_id
        )
        if removed:
            save_reservations(self.reserve_path, updated)
            self.reservations = updated
        return removed

    async def start_org_api(self) -> None:
        api_key = os.environ.get("ORG_BOT_API_KEY", "").strip()
        if not api_key:
            return
        try:
            guild_id = int(os.environ["ORG_GUILD_ID"])
        except (KeyError, ValueError):
            logger.error("ORG_GUILD_ID is required for the org API; API disabled")
            return
        org = OrgReserves(
            Path(os.environ.get("ORG_RESERVES_FILE", "org_reserves.json")),
            Path(os.environ.get("ORG_RESTRICTIONS_FILE", "org_restrictions.json")),
            load_known_pokemon_names(),
        )
        app = create_app(
            api_key,
            org,
            guild_id,
            self.org_add_reserve,
            self.org_remove_reserve,
        )
        self.org_runner = web.AppRunner(app)
        await self.org_runner.setup()
        port = int(os.environ.get("ORG_API_PORT") or os.environ.get("PORT") or 8080)
        await web.TCPSite(self.org_runner, "0.0.0.0", port).start()
        logger.info("Org API listening on port %s", port)

    async def setup_hook(self) -> None:
        await self.start_org_api()
        self.image_http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            connector=aiohttp.TCPConnector(limit=0),
            headers={"User-Agent": "Vivillon-naming/1.0"},
        )

    async def close(self) -> None:
        if self.org_runner is not None:
            await self.org_runner.cleanup()
        if self.image_http is not None:
            await self.image_http.close()
        if self.openai is not None:
            await self.openai.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def set_poketwo_blocked(self, channel, blocked: bool) -> None:
        """Deny (or restore) Pokétwo's Send Messages permission in a channel."""
        try:
            guild = channel.guild
            target = guild.get_member(self.config.poketwo_bot_id)
            if target is None:
                target = await guild.fetch_member(self.config.poketwo_bot_id)
            if blocked:
                await channel.set_permissions(
                    target,
                    send_messages=False,
                    reason="Missingno spawned; blocking Pokétwo until v!r",
                )
            else:
                await channel.set_permissions(
                    target, overwrite=None, reason="v!r: restoring Pokétwo"
                )
        except Exception as error:
            logger.warning("Could not change Pokétwo permissions: %s", error)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot and message.author.id != self.config.poketwo_bot_id:
            return
        self.track_incense_command(message)
        if not self.is_allowed_channel(message.channel):
            return
        channel_id = getattr(message.channel, "id", None)

        text = message_text(message)
        if message.author.id != self.config.poketwo_bot_id:
            if re.match(r"^v!r(?:\s|$)", message.content, re.IGNORECASE):
                was_paused = channel_id in self.muted_poketwo_channels
                if was_paused:
                    self.muted_poketwo_channels.discard(channel_id)
                    await self.set_poketwo_blocked(message.channel, False)
                if re.match(
                    r"^v!r\s+(?:add|list|search|remove|clear|e|exchange)(?:\s|$)",
                    message.content,
                    re.IGNORECASE,
                ):
                    if was_paused:
                        await message.reply("Channel unpaused.", mention_author=False)
                    await self.handle_reserve_command(message)
                else:
                    await message.reply("Channel unpaused.", mention_author=False)
                return
            if is_image_test_command(message.content):
                if image_url(message) is None:
                    await message.reply(
                        "Attach an image to `v!test` to test spawn recognition.",
                        mention_author=False,
                    )
                    return
                await self.handle_spawn(message, test_mode=True)
                return
            if re.fullmatch(r"v!grab\s*", message.content, re.IGNORECASE):
                await self.handle_grab_command(message)
                return
            if re.fullmatch(r"v!ping\s*", message.content, re.IGNORECASE):
                await self.handle_ping_command(message)
                return
            if API_STATUS_COMMAND_PATTERN.fullmatch(message.content):
                await self.handle_api_status(message)
                return
            if re.match(r"^v!sh(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_shinyhunt_command(message)
                return
            if re.match(r"^v!cl(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_collection_command(message)
                return
            if re.match(
                r"^v!r\s+(?:add|list|search|remove|clear|e|exchange)(?:\s|$)",
                message.content,
                re.IGNORECASE,
            ):
                await self.handle_reserve_command(message)
            return

        if SPAWN_PATTERN.search(text):
            await self.handle_spawn(message)

    def is_allowed_channel(self, channel: discord.abc.Messageable) -> bool:
        guild = getattr(channel, "guild", None)
        return getattr(guild, "id", None) in SERVER_IDS

    def load_active_incenses(self) -> dict[str, dict[str, int | str]]:
        if not self.incense_path.is_file():
            return {}
        try:
            data = json.loads(self.incense_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning(
                "Could not load incense tracking from %s: %s",
                self.incense_path,
                error,
            )
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "Incense tracking file %s has an invalid format", self.incense_path
            )
            return {}
        now = int(time.time())
        records: dict[str, dict[str, int | str]] = {}
        for channel_id, record in data.items():
            if (
                not isinstance(channel_id, str)
                or not isinstance(record, dict)
                or not isinstance(record.get("guild"), str)
                or not isinstance(record.get("channel"), str)
                or isinstance(record.get("expires_at"), bool)
                or not isinstance(record.get("expires_at"), int)
                or isinstance(record.get("guild_id"), bool)
                or not isinstance(record.get("guild_id"), int)
            ):
                logger.warning(
                    "Incense tracking file %s has an invalid entry",
                    self.incense_path,
                )
                return {}
            if record["expires_at"] > now:
                records[channel_id] = {
                    "guild": record["guild"],
                    "channel": record["channel"],
                    "guild_id": record["guild_id"],
                    "expires_at": record["expires_at"],
                }
        return records

    def save_active_incenses(self) -> None:
        try:
            self.incense_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.incense_path.with_name(
                f"{self.incense_path.name}.tmp"
            )
            temporary_path.write_text(
                json.dumps(self.active_incenses, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.incense_path)
        except OSError:
            logger.exception("Could not save incense tracking to %s", self.incense_path)

    def track_incense_command(self, message: discord.Message) -> None:
        guild = message.guild
        channel = message.channel
        if guild is None or message.author.id == self.config.poketwo_bot_id:
            return
        action = poketwo_incense_action(message.content, self.config.poketwo_bot_id)
        if action is None:
            return
        channel_id = str(channel.id)
        if action == "stop":
            self.active_incenses.pop(channel_id, None)
        else:
            self.active_incenses[channel_id] = {
                "guild": guild.name,
                "channel": getattr(channel, "name", f"channel-{channel.id}"),
                "guild_id": guild.id,
                "expires_at": int(time.time()) + INCENSE_DURATION_SECONDS,
            }
        self.save_active_incenses()

    def current_active_incenses(self) -> list[dict[str, int | str]]:
        now = int(time.time())
        expired = [
            channel_id
            for channel_id, record in self.active_incenses.items()
            if record["expires_at"] <= now
        ]
        if expired:
            for channel_id in expired:
                del self.active_incenses[channel_id]
            self.save_active_incenses()
        return sorted(
            self.active_incenses.values(),
            key=lambda record: (
                str(record["guild"]).casefold(),
                str(record["channel"]).casefold(),
            ),
        )

    async def handle_api_status(self, message: discord.Message) -> None:
        now = time.monotonic()
        recent = [
            record
            for record in self.recognition_durations
            if now - record[0] <= API_STATUS_WINDOW_SECONDS
        ]
        self.recognition_durations = deque(
            (
                record
                for record in self.recognition_durations
                if now - record[0] <= API_STATUS_WINDOW_SECONDS
            ),
            maxlen=1000,
        )
        active_incenses = self.current_active_incenses()
        max_requests = self.config.max_concurrent_vision_requests
        if self.pending_vision_requests:
            activity = "🟠 Busy"
        elif self.active_vision_requests >= max_requests:
            activity = "🟠 At capacity"
        elif not recent:
            activity = "🟢 Low Activity"
        else:
            activity = "🟢 Active"
        inference = [record[1] for record in recent]
        response = [record[2] for record in recent]

        def format_duration(seconds: float | None) -> str:
            return f"{seconds * 1000:.0f} ms" if seconds is not None else "—"

        inference_fastest = format_duration(min(inference)) if inference else "—"
        inference_slowest = format_duration(max(inference)) if inference else "—"
        inference_average = (
            format_duration(sum(inference) / len(inference)) if inference else "—"
        )
        inference_latest = format_duration(inference[-1]) if inference else "—"
        response_fastest = format_duration(min(response)) if response else "—"
        response_slowest = format_duration(max(response)) if response else "—"
        response_average = (
            format_duration(sum(response) / len(response)) if response else "—"
        )
        response_latest = format_duration(response[-1]) if response else "—"
        openai_backend = self.openai is not None
        model = self.config.openai_model if openai_backend else "SIFT reference matching"
        backend = "SIFT + OpenAI fallback" if openai_backend else "SIFT only"

        embed = discord.Embed(title="API Status", color=discord.Color.blurple())
        fields = (
            ("Activity", activity),
            ("Active Incense", str(len(active_incenses))),
            ("Store (latest)", "—"),
            ("Store (avg)", "—"),
            ("JSON load", "—"),
            ("CSV load", "Not used"),
            ("Inference Fastest", inference_fastest),
            ("Inference Slowest", inference_slowest),
            ("Inference Avg", inference_average),
            ("Inference Latest", inference_latest),
            ("Response Fastest", response_fastest),
            ("Response Slowest", response_slowest),
            ("Response Avg", response_average),
            ("Response Latest", response_latest),
            ("Pokémons Named", str(self.pokemon_named_count)),
        )
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        embed.set_footer(
            text=(
                f"Model: {model} | Backend: {backend} | "
                f"Threads: {threading.active_count()} | Window: 5 min rolling | "
                f"Load: {self.active_vision_requests}/{max_requests} "
                f"(+{self.pending_vision_requests} waiting) | "
                f"Failed: {self.failed_recognition_count} | "
                "Incense is estimated"
            )
        )
        await message.reply(embed=embed, mention_author=False)

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        # Pokétwo sometimes adds the spawn image or text by editing the message.
        if after.author.id != self.config.poketwo_bot_id:
            return
        if not self.is_allowed_channel(after.channel):
            return
        if SPAWN_PATTERN.search(message_text(after)):
            await self.handle_spawn(after)

    async def handle_grab_command(self, message: discord.Message) -> None:
        usage = "Reply to a Pokémon list (like a `v!r search` result) with `v!grab`."
        if message.guild is None or message.reference is None:
            await message.reply(usage, mention_author=False)
            return
        referenced = message.reference.resolved
        if not isinstance(referenced, discord.Message):
            try:
                referenced = await message.channel.fetch_message(
                    message.reference.message_id
                )
            except discord.HTTPException:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return
        texts = RESERVE_LIST_CACHE.get(referenced.id)
        if texts is None:
            texts = [referenced.content] + [
                embed.description for embed in referenced.embeds if embed.description
            ]
        entries = parse_grab_entries(texts)
        if not entries:
            await message.reply(usage, mention_author=False)
            return
        view = GrabListView(self, message.guild.id, message.author.id, entries)
        response = await message.reply(
            embeds=view.current_embeds(),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
            mention_author=False,
        )
        view.message = response

    async def handle_ping_command(self, message: discord.Message) -> None:
        started_at = time.perf_counter()
        response = await message.reply("....loading", mention_author=False)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        await response.edit(content=f"{elapsed_ms}ms")

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

        remove_match = re.match(
            r"^v!sh\s+remove(?:\s|$)",
            message.content,
            re.IGNORECASE,
        )
        if remove_match is not None:
            pokemon_name = parse_shinyhunt_remove_command(message.content)
            if pokemon_name is None:
                await message.reply(
                    "Usage: `v!sh remove <pokemon>`",
                    mention_author=False,
                )
                return

            updated_shinyhunters, removed = remove_shinyhunter(
                self.shinyhunters,
                message.guild.id,
                pokemon_name,
                message.author.id,
            )
            if not removed:
                await message.reply(
                    f"You are not currently shinyhunting {pokemon_name}.",
                    mention_author=False,
                )
                return
            try:
                save_reservations(self.shinyhunt_path, updated_shinyhunters)
            except ValueError:
                logger.exception("Could not save shiny-hunt removal")
                await message.reply(
                    "I couldn't remove that shiny hunt. Check the bot logs.",
                    mention_author=False,
                )
                return

            self.shinyhunters = updated_shinyhunters
            await message.reply(
                f"You are no longer shinyhunting {format_shinyhunt_name(pokemon_name)}.",
                mention_author=False,
            )
            return

        pokemon_name = parse_shinyhunt_command(message.content)
        if pokemon_name is None:
            await message.reply(
                "Usage: `v!sh <pokemon>` or `v!sh remove <pokemon>` "
                "(one Pokémon per command)",
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

    async def handle_collection_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Collections can only be used in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!cl\s+list\s*", message.content, re.IGNORECASE):
            pokemon_names = collection_pokemon_for_user(
                self.collections,
                message.guild.id,
                message.author.id,
            )
            await reply_with_reservation_embeds(
                message,
                format_collection_embeds(pokemon_names),
            )
            return
        if re.match(r"^v!cl\s+list(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply("Usage: `v!cl list`", mention_author=False)
            return

        if re.fullmatch(r"v!cl\s+clear\s*", message.content, re.IGNORECASE):
            updated_collections = clear_user_collection(
                self.collections,
                message.guild.id,
                message.author.id,
            )
            try:
                save_reservations(self.collection_path, updated_collections)
            except ValueError:
                logger.exception("Could not clear Pokémon collection")
                await message.reply(
                    "I couldn't clear your collection. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.collections = updated_collections
            await message.reply(
                "Your Pokémon collection has been cleared.",
                mention_author=False,
            )
            return
        if re.match(r"^v!cl\s+clear(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply("Usage: `v!cl clear`", mention_author=False)
            return

        if re.match(r"^v!cl\s+remove(?:\s|$)", message.content, re.IGNORECASE):
            pokemon_names = parse_collection_pokemon_command(
                message.content,
                COLLECTION_REMOVE_PATTERN,
            )
            if pokemon_names is None:
                await message.reply(
                    "Usage: `v!cl remove <pokemon>, <pokemon>`",
                    mention_author=False,
                )
                return

            updated_collections, removed_names, missing_names = (
                remove_collection_pokemon(
                    self.collections,
                    message.guild.id,
                    pokemon_names,
                    message.author.id,
                )
            )
            if not removed_names:
                await message.reply(
                    f"Those Pokémon were not found in your collection: "
                    f"{', '.join(missing_names)}.",
                    mention_author=False,
                )
                return

            try:
                save_reservations(self.collection_path, updated_collections)
            except ValueError:
                logger.exception("Could not remove Pokémon from collection")
                await message.reply(
                    "I couldn't update your collection. Check the bot logs.",
                    mention_author=False,
                )
                return

            self.collections = updated_collections
            response = f"Removed {', '.join(removed_names)} from your collection."
            if missing_names:
                response += f" Not found: {', '.join(missing_names)}."
            await message.reply(response, mention_author=False)
            return

        pokemon_names = parse_collection_add_command(message.content)
        if pokemon_names is None:
            await message.reply(
                "Usage: `v!cl add <pokemon>, <pokemon>`, "
                "`v!cl remove <pokemon>, <pokemon>`, `v!cl list`, or `v!cl clear`",
                mention_author=False,
            )
            return

        new_names, already_added_names = split_collection_add_names(
            self.collections,
            message.guild.id,
            pokemon_names,
            message.author.id,
        )
        if not new_names:
            await message.reply(
                format_collection_add_confirmation([], already_added_names),
                mention_author=False,
            )
            return

        updated_collections = add_collection_pokemon(
            self.collections,
            message.guild.id,
            new_names,
            message.author.id,
        )
        try:
            save_reservations(self.collection_path, updated_collections)
        except ValueError:
            logger.exception("Could not save Pokémon collection")
            await message.reply(
                "I couldn't save your collection. Check the bot logs.",
                mention_author=False,
            )
            return

        self.collections = updated_collections
        await message.reply(
            format_collection_add_confirmation(new_names, already_added_names),
            mention_author=False,
        )

    async def handle_reserve_command(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            await message.reply(
                "Reserve commands can only be used in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!r\s+list\s*", message.content, re.IGNORECASE):
            embeds = format_server_reservation_embeds(
                self.reservations,
                message.guild.id,
            )
            await reply_with_reservation_embeds(message, embeds)
            return
        if re.match(r"^v!r\s+list(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply("Usage: `v!r list`", mention_author=False)
            return

        if re.match(r"^v!r\s+search(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_search(message)
            return

        if not any(role.id == RESERVE_ROLE_ID for role in message.author.roles):
            await message.reply(
                "Only reserve managers can add, remove, or clear reservations.",
                mention_author=False,
            )
            return

        if re.match(r"^v!r\s+(?:e|exchange)(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_exchange(message)
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
                "Usage: `v!r add <pokemon>, <pokemon> @member` "
                "or `v!r add all <pokemon> @member`",
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
            key = reservation_key_for_command(message.guild.id, pokemon_name)
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
            (
                f"all forms of {name[len('all '):]}".capitalize()
                if name.casefold().startswith("all ")
                else name[0].upper() + name[1:]
            )
            for name in pokemon_names
        )
        await message.reply(
            f"Reserve {display_names} added to {target.mention}",
            mention_author=False,
        )

    async def handle_reserve_exchange(self, message: discord.Message) -> None:
        usage = (
            "Reply to a list like `@member - pikachu, eevee` (one member per line) "
            "with `v!r e @owner`."
        )
        match = EXCHANGE_COMMAND_PATTERN.fullmatch(message.content.strip())
        if match is None or message.reference is None or message.guild is None:
            await message.reply(usage, mention_author=False)
            return
        source_id = int(match.group(1))

        referenced = message.reference.resolved
        if not isinstance(referenced, discord.Message):
            try:
                referenced = await message.channel.fetch_message(
                    message.reference.message_id
                )
            except discord.HTTPException:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return

        transfers = parse_exchange_list(referenced.content)
        if not transfers:
            await message.reply(usage, mention_author=False)
            return

        _, _, skipped = exchange_reservations(
            self.reservations, message.guild.id, source_id, transfers
        )
        embed = format_exchange_embed(
            self.reservations, message.guild.id, source_id, transfers, skipped
        )
        await message.reply(
            embed=embed,
            view=ExchangeReservesView(
                self, message.guild.id, message.author.id, source_id, transfers
            ),
            allowed_mentions=discord.AllowedMentions.none(),
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
        if match is None:
            await message.reply(
                "Usage: `v!r search <pokemon|@member>`",
                mention_author=False,
            )
            return

        query = match.group(1).strip()
        if message.mentions:
            member_match = re.fullmatch(r"<@!?(\d+)>", query)
            if (
                len(message.mentions) != 1
                or member_match is None
                or int(member_match.group(1)) != message.mentions[0].id
                or not isinstance(message.mentions[0], discord.Member)
            ):
                await message.reply(
                    "Usage: `v!r search <pokemon|@member>`",
                    mention_author=False,
                )
                return

            member = message.mentions[0]
            embeds = format_reservation_embeds(
                member.display_name,
                reserved_pokemon_for_user(
                    self.reservations,
                    message.guild.id,
                    member.id,
                ),
            )
            await reply_with_reservation_embeds(message, embeds)
            return

        pokemon_name = unicodedata.normalize("NFC", query)
        if len(pokemon_name) > 60 or not is_valid_pokemon_name(pokemon_name):
            await message.reply(
                "Usage: `v!r search <pokemon|@member>`",
                mention_author=False,
            )
            return

        if pokemon_name.casefold().startswith("all "):
            embeds = format_all_forms_reservation_embeds(
                self.reservations,
                message.guild.id,
                pokemon_name[4:].strip(),
            )
        else:
            embeds = format_pokemon_reserver_embeds(
                self.reservations,
                message.guild.id,
                pokemon_name,
            )
        await reply_with_reservation_embeds(message, embeds)

    async def handle_spawn(
        self, message: discord.Message, *, test_mode: bool = False
    ) -> None:
        url = image_url(message)
        if not url:
            logger.warning("Image test or spawn message %s had no image", message.id)
            return
        if self.image_http is None:
            logger.error("HTTP client was not initialized")
            return
        if message.id in self.handled_spawn_ids:
            return
        self.handled_spawn_ids[message.id] = None
        while len(self.handled_spawn_ids) > 5000:
            del self.handled_spawn_ids[next(iter(self.handled_spawn_ids))]

        started = time.monotonic()
        self.pending_vision_requests += 1
        waiting_for_vision_slot = True
        try:
            try:
                async with self.vision_semaphore:
                    self.pending_vision_requests -= 1
                    waiting_for_vision_slot = False
                    self.active_vision_requests += 1
                    try:
                        inference_started = time.monotonic()
                        for attempt in range(3):
                            try:
                                name, confidence = await recognize_pokemon(
                                    url,
                                    client=self.openai,
                                    http=self.image_http,
                                    model=self.config.openai_model,
                                    detail=self.config.openai_image_detail,
                                    matcher=self.image_matcher,
                                )
                                break
                            except NoMatchError:
                                raise
                            except (
                                aiohttp.ClientError,
                                asyncio.TimeoutError,
                                ValueError,
                                OpenAIError,
                            ):
                                if attempt == 2:
                                    raise
                                await asyncio.sleep(0.1)
                        inference_seconds = time.monotonic() - inference_started
                    finally:
                        self.active_vision_requests -= 1
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                self.failed_recognition_count += 1
                logger.exception("Could not recognize spawn in message %s", message.id)
                await message.reply(
                    "I couldn't identify that spawn. Check the bot logs for details.",
                    mention_author=False,
                )
                return
            except NoMatchError:
                self.failed_recognition_count += 1
                logger.info("No reference image matched spawn %s", message.id)
                if test_mode:
                    await message.reply(
                        "I couldn't match that test image to a reference Pokémon.",
                        mention_author=False,
                    )
                return
            except OpenAIError:
                self.failed_recognition_count += 1
                logger.exception("Vision request failed for message %s", message.id)
                await message.reply(
                    "I couldn't identify that spawn because the vision request failed.",
                    mention_author=False,
                )
                return
        finally:
            if waiting_for_vision_slot:
                self.pending_vision_requests -= 1

        completed = time.monotonic()
        response_seconds = completed - started
        if name and not test_mode:
            self.pokemon_named_count += 1
            self.recognition_durations.append(
                (completed, inference_seconds, response_seconds)
            )
        elif not name and not test_mode:
            self.failed_recognition_count += 1
        logger.info(
            "Recognized %s in %.2fs (message %s)",
            name or "nothing",
            response_seconds,
            message.id,
        )
        if not name:
            await message.reply(
                "I couldn't confidently identify that Pokémon.",
                mention_author=False,
            )
            return
        if test_mode and not is_missingno_name(name):
            await message.reply(
                f"Test image recognized as {name}; Missingno action was not triggered.",
                mention_author=False,
            )
            return
        if is_missingno_name(name):
            channel_id = getattr(message.channel, "id", None)
            if channel_id is not None:
                self.muted_poketwo_channels.add(channel_id)
            await message.reply(
                "Ping a staff member. Dont catch the pokemon.",
                mention_author=False,
            )
            if channel_id is not None:
                await self.set_poketwo_blocked(message.channel, True)
            return

        reserved_user_ids = (
            reserved_user_ids_for_pokemon(
                self.reservations,
                message.guild.id,
                name,
            )
            if message.guild
            else []
        )
        shinyhunter_user_ids = (
            shinyhunter_user_ids_for_pokemon(
                self.shinyhunters,
                message.guild.id,
                name,
            )
            if message.guild
            else []
        )
        collection_user_ids = (
            collection_user_ids_for_pokemon(
                self.collections,
                message.guild.id,
                name,
            )
            if message.guild
            else []
        )
        is_fire_spawn = is_fire_icon_pokemon(name)
        is_water_spawn = is_water_icon_pokemon(name)
        is_normal_spawn = is_normal_icon_pokemon(name)
        is_electric_spawn = is_electric_icon_pokemon(name)
        is_grass_spawn = is_grass_icon_pokemon(name)
        is_ice_spawn = is_ice_icon_pokemon(name)
        if (
            is_fire_spawn
            or is_water_spawn
            or is_normal_spawn
            or is_electric_spawn
            or is_grass_spawn
            or is_ice_spawn
        ):
            reply = format_custom_type_spawn_reply(
                name,
                confidence,
                POKETWO_COMMAND_BOT_ID,
                reserved_user_ids,
                shinyhunter_user_ids,
                collection_user_ids,
                include_fire=is_fire_spawn,
                include_water=is_water_spawn,
                include_normal=is_normal_spawn,
                include_electric=is_electric_spawn,
                include_grass=is_grass_spawn,
                include_ice=is_ice_spawn,
            )
            companion_icon_filename = (
                fire_companion_icon_filename_for_pokemon(name)
                or water_companion_icon_filename_for_pokemon(name)
                or normal_companion_icon_filename_for_pokemon(name)
                or electric_companion_icon_filename_for_pokemon(name)
            )
            if companion_icon_filename:
                await message.reply(
                    reply,
                    embed=format_pc_catch_embed(name),
                    file=discord.File(
                        Path(__file__).with_name("assets") / companion_icon_filename,
                        filename=companion_icon_filename,
                    ),
                    mention_author=False,
                )
            else:
                await message.reply(
                    reply,
                    embed=format_pc_catch_embed(name),
                    mention_author=False,
                )
            return

        icon_filename = type_icon_filename_for_pokemon(name)
        if icon_filename:
            type_embed = format_type_spawn_embed(
                name, confidence, POKETWO_COMMAND_BOT_ID, icon_filename
            )
            content_lines = format_spawn_mention_lines(
                reserved_user_ids,
                shinyhunter_user_ids,
                collection_user_ids,
            )
            await message.reply(
                content="\n".join(content_lines),
                embeds=[type_embed, format_pc_catch_embed(name)],
                file=discord.File(
                    Path(__file__).with_name("assets") / icon_filename,
                    filename=icon_filename,
                ),
                mention_author=False,
            )
        else:
            await message.reply(
                format_spawn_reply(
                    name,
                    confidence,
                    POKETWO_COMMAND_BOT_ID,
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                ),
                embed=format_pc_catch_embed(name),
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


class ExchangeReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        source_id: int,
        transfers: list[tuple[int, list[str]]],
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.source_id = source_id
        self.transfers = transfers

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

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_exchange(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated, _, _ = exchange_reservations(
            self.bot.reservations, self.guild_id, self.source_id, self.transfers
        )
        try:
            save_reservations(self.bot.reserve_path, updated)
        except ValueError:
            logger.exception("Could not save Pokémon reservation exchange")
            await interaction.response.send_message(
                "I couldn't save that exchange. Check the bot logs.",
                ephemeral=True,
            )
            return
        self.bot.reservations = updated
        self.stop()
        await interaction.response.edit_message(
            content="Reserves exchanged.", embed=None, view=None
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel_exchange(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.stop()
        await interaction.response.edit_message(
            content="Exchange cancelled.", embed=None, view=None
        )


class GrabEmojiModal(discord.ui.Modal, title="Custom emoji"):
    emojis = discord.ui.TextInput(
        label="Emojis (separate with commas)",
        placeholder="🔥, 💧, <:custom:123456789012345678>",
        required=False,
        max_length=500,
    )

    def __init__(self, view: "GrabListView") -> None:
        super().__init__()
        self.grab_view = view
        self.emojis.default = ", ".join(view.emojis) or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.grab_view.emojis = [
            emoji.strip() for emoji in str(self.emojis).split(",") if emoji.strip()
        ][:50]
        await self.grab_view.refresh(interaction)


class GrabAddReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        pairs: list[tuple[str, int]],
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.pairs = pairs

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who clicked Add reserves can confirm this.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        updated = add_reservations_bulk(
            self.bot.reservations, self.guild_id, self.pairs
        )
        try:
            save_reservations(self.bot.reserve_path, updated)
        except ValueError:
            logger.exception("Could not save grabbed reservations")
            await interaction.response.send_message(
                "I couldn't save those reserves. Check the bot logs.",
                ephemeral=True,
            )
            return
        self.bot.reservations = updated
        self.stop()
        await interaction.response.edit_message(content="Adding reserves...", view=None)

        channel = interaction.channel
        if channel is None:
            return
        no_pings = discord.AllowedMentions.none()
        try:
            for name, user_id in self.pairs:
                await channel.send(
                    f"v!r add {name} <@{user_id}>", allowed_mentions=no_pings
                )
                await asyncio.sleep(0.5)
                await channel.send(
                    f"{grab_display_name(name)} added to <@{user_id}>",
                    allowed_mentions=no_pings,
                )
                await asyncio.sleep(0.5)
            await interaction.edit_original_response(content="Reserves added.")
        except discord.HTTPException:
            logger.exception("Could not post grabbed reserve confirmations")

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.stop()
        await interaction.response.edit_message(
            content="Add reserves cancelled.", view=None
        )


class GrabListView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        entries: list[tuple[str, list[int]]],
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.entries = entries
        self.ordered = False
        self.all_forms = False
        self.emojis: list[str] = []
        self.message: discord.Message | None = None
        self.sync_buttons()

    def current_embeds(self) -> list[discord.Embed]:
        lines = build_grab_lines(
            self.entries,
            ordered=self.ordered,
            all_forms=self.all_forms,
            emojis=self.emojis,
        )
        # One message can hold 6000 embed characters in total, so the list is
        # spread over as many embeds as needed instead of being paged.
        pages = paginate_grab_lines(lines, 2900)
        embeds = [
            discord.Embed(description=page, color=discord.Color.blurple())
            for page in pages[:2]
        ]
        embeds[-1].set_footer(text=f"{len(self.entries)} Pokémon")
        return embeds

    def sync_buttons(self) -> None:
        self.order_button.style = (
            discord.ButtonStyle.success if self.ordered else discord.ButtonStyle.secondary
        )
        self.all_forms_button.style = (
            discord.ButtonStyle.success
            if self.all_forms
            else discord.ButtonStyle.secondary
        )
        self.all_forms_button.label = "All forms on" if self.all_forms else "All forms off"
        self.emoji_button.style = (
            discord.ButtonStyle.success if self.emojis else discord.ButtonStyle.secondary
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        embeds = self.current_embeds()
        self.sync_buttons()
        await interaction.response.edit_message(embeds=embeds, view=self)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable expired grab-list buttons")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran `v!grab` can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Order", style=discord.ButtonStyle.secondary, row=0)
    async def order_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.ordered = not self.ordered
        await self.refresh(interaction)

    @discord.ui.button(label="All forms off", style=discord.ButtonStyle.secondary, row=0)
    async def all_forms_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.all_forms = not self.all_forms
        await self.refresh(interaction)

    @discord.ui.button(label="Custom emoji", style=discord.ButtonStyle.secondary, row=0)
    async def emoji_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await interaction.response.send_modal(GrabEmojiModal(self))

    @discord.ui.button(label="Add reserves", style=discord.ButtonStyle.primary, row=0)
    async def add_reserves_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        if not isinstance(interaction.user, discord.Member) or not any(
            role.id == RESERVE_ROLE_ID for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "Only reserve managers can add reserves.", ephemeral=True
            )
            return
        pairs = grab_reserve_pairs(self.entries, self.all_forms)
        if not pairs:
            await interaction.response.send_message(
                "Add reserves only works when the list has an @user behind each Pokémon.",
                ephemeral=True,
            )
            return
        assignments = "\n".join(
            f"{grab_display_name(name)} → <@{user_id}>" for name, user_id in pairs
        )
        if len(assignments) > 3800:
            assignments = assignments[:3800].rsplit("\n", 1)[0] + "\n…"
        await interaction.response.send_message(
            "Are you sure you want to add all reserves?",
            embed=discord.Embed(
                title="Reserves to add",
                description=assignments,
                color=discord.Color.blurple(),
            ),
            view=GrabAddReservesView(
                self.bot, self.guild_id, interaction.user.id, pairs
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Copy", style=discord.ButtonStyle.secondary, row=1)
    async def copy_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        lines = build_grab_lines(
            self.entries,
            ordered=self.ordered,
            all_forms=self.all_forms,
            emojis=self.emojis,
        )
        chunks = paginate_grab_lines(lines, 2000)
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


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
