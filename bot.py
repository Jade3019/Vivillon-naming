import asyncio
import base64
from io import BytesIO
import json
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Final

import aiohttp
import discord
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
from image_match import (
    FORM_DISPLAY_NAMES,
    ARCEUS_FORM_SET,
    SILVALLY_FORMS,
    VIVILLON_FORM_SET,
    ImageMatcher,
    species_display_name,
)
from org_api import OrgReserves, create_app
import org_rpc
from daycare import DaycareFeature
from help_menu import HELP_COMMAND_PATTERN, build_help_menu_embed
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
PROFILE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!profile(?:\s+<@!?(\d+)>)?\s*$",
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
CHAT_EVENT_EMOJI: Final[str] = "⏲️"
CHAT_EVENT_SIGNUP_SECONDS: Final[int] = 60
CHAT_EVENT_MIN_PARTICIPANTS: Final[int] = 2
PROFILE_DEFAULTS: Final[dict[str, int | str]] = {
    "text_color": "white",
    "background": "default",
    "middle_background": "white",
    "frame": "none",
}
PROFILE_STAT_DEFAULTS: Final[dict[str, int]] = {
    "total": 0,
    "shiny": 0,
    "low_iv": 0,
    "high_iv": 0,
    "gmax": 0,
    "missingno": 0,
}
PROFILE_TEXT_COLORS: Final[dict[str, tuple[str, str]]] = {
    "white": ("White", "#FFFFFF"),
    "black": ("Black", "#171717"),
    "pink": ("Pink", "#F3A6C8"),
    "blue": ("Blue", "#9BD8F2"),
    "gold": ("Gold", "#F4D06F"),
}
PROFILE_BACKGROUNDS: Final[dict[str, tuple[str, str]]] = {
    "default": ("Default", "#292A2F"),
}
PROFILE_MIDDLE_BACKGROUNDS: Final[dict[str, tuple[str, str]]] = {
    "white": ("White", "#FFFFFF"),
}
PROFILE_LEGACY_CHOICES: Final[dict[str, frozenset[str]]] = {
    "background": frozenset({"rose", "blue", "purple", "mint"}),
    "middle_background": frozenset({"light_gray", "soft_pink", "soft_blue"}),
}
PROFILE_FRAMES: Final[dict[str, tuple[str, str]]] = {
    "none": ("No frame", "No frame selected"),
}
PROFILE_SETTING_CHOICES: Final[dict[str, dict[str, tuple[str, str]]]] = {
    "text_color": PROFILE_TEXT_COLORS,
    "background": PROFILE_BACKGROUNDS,
    "middle_background": PROFILE_MIDDLE_BACKGROUNDS,
    "frame": PROFILE_FRAMES,
}
PROFILE_SETTING_LABELS: Final[dict[str, str]] = {
    "text_color": "Text color",
    "background": "Background",
    "middle_background": "Middle background",
    "frame": "Frame",
}
PROFILE_EMOJI_URLS: Final[dict[str, str]] = {
    "low_iv": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4c9.png",
    "high_iv": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4c8.png",
    "shiny": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/2728.png",
    "gmax": "https://cdn.discordapp.com/emojis/1504098787658961028.png?size=64",
    "missingno": "https://cdn.discordapp.com/emojis/1563908280445575300.png?size=64",
}


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
        parts.extend((embed.author.name or "", embed.footer.text or ""))
        parts.extend(f"{field.name}: {field.value}" for field in embed.fields)
    return unicodedata.normalize(
        "NFC", "\n".join(part for part in parts if part)
    )


def poketwo_incense_action(content: str, poketwo_bot_id: int) -> str | None:
    mention = rf"<@!?{poketwo_bot_id}>"
    match = re.search(
        rf"(?:^|\s)(?:{mention}\s+|p!\s*)"
        rf"(?P<start>buy\s+incense)\b|"
        rf"(?:^|\s)(?:{mention}\s+|p!\s*)"
        rf"(?P<stop>stopincense)\b",
        content,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return "start" if match.group("start") else "stop"


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


LOW_ACCURACY_THRESHOLD = 90


def load_low_accuracy_channels(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value
        for key, value in data.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def save_low_accuracy_channels(path: Path, channels: dict[str, int]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(channels), encoding="utf-8")
    temporary.replace(path)


def is_image_test_command(content: str) -> bool:
    return (
        re.fullmatch(r"v!test(?:\s+shiny)?\s*", content, re.IGNORECASE)
        is not None
    )


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


def display_pokemon_name(name: str) -> str:
    if name.casefold() == "male meowstic":
        return "Meowstic"
    return FORM_DISPLAY_NAMES.get(name, name)


def format_guess(
    name: str, confidence: float, guess_name: str | None = None
) -> str:
    return f"{display_pokemon_name(guess_name or name)}: {confidence:.2f}%"


def shown_form_name(name: str, form_name: str | None) -> str:
    """Silvally types, Vivillon patterns and Arceus types are shown by form, but caught and reserved as the species."""
    if (
        form_name in SILVALLY_FORMS
        or form_name in VIVILLON_FORM_SET
        or form_name in ARCEUS_FORM_SET
    ):
        return form_name
    return name


def format_catch_command(poketwo_bot_id: int, name: str) -> str:
    del poketwo_bot_id
    return f"@Pokétwo#8236 c {display_pokemon_name(name).lower()}"


def format_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> str:
    command = format_catch_command(poketwo_bot_id, name)
    lines = [format_guess(name, confidence, guess_name)]
    lines.extend(
        format_spawn_mention_lines(
            reserved_user_ids,
            shinyhunter_user_ids,
            collection_user_ids,
        )
    )
    if assisted:
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
        return None
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
    assisted: bool = True,
    guess_name: str | None = None,
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
    lines.append(f"{' '.join(type_emojis)} {format_guess(name, confidence, guess_name)}")
    if assisted:
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


TYPE_EMOJIS: Final[dict[str, str]] = {
    "normal": "<:Normal:1560305235279482930>",
    "fire": "<:fire:1560301436074729532>",
    "water": "<:water:1560303864094130357>",
    "electric": "<:Electric:1560306053164572732>",
    "grass": "<:grass:1560307079896502282>",
    "ice": "<:Ice:1560307867200782386>",
    "bug": "<:bug:1564785932496797757>",
    "dark": "<:dark:1564786204699005129>",
    "dragon": "<:Dragon:1564786673840160818>",
    "fairy": "<:Fairy:1564786928631677068>",
    "fighting": "<:Fighting:1564787413547483156>",
    "flying": "<:Flying:1564787610143162489>",
    "ghost": "<:Ghost:1564787837306540213>",
    "ground": "<:Ground:1564789353648230441>",
    "poison": "<:Poison:1564788700687114310>",
    "psychic": "<:Psychic:1564788957437366342>",
    "rock": "<:rock:1564789532384174100>",
    "steel": "<:Steel:1564789710440898610>",
}


def _type_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold())
    return re.sub(
        r"[^a-z0-9]", "", "".join(c for c in folded if not unicodedata.combining(c))
    )


def load_pokemon_types(path: Path) -> dict[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load Pokémon types from %s", path)
        return {}
    return {
        _type_key(name): [t for t in types if t in TYPE_EMOJIS]
        for name, types in data.items()
        if isinstance(name, str) and isinstance(types, list)
    }


POKEMON_TYPES: Final[dict[str, list[str]]] = load_pokemon_types(
    Path(__file__).with_name("pokemon_types.json")
)


def pokemon_types_for(*names: str | None) -> list[str]:
    """Types of a Pokémon, trying the most specific name first."""
    for name in names:
        if not name:
            continue
        for kind in ("Silvally", "Arceus"):
            prefix = name.removesuffix(f" {kind}")
            if prefix != name and _type_key(prefix) in TYPE_EMOJIS:
                return [_type_key(prefix)]
        if name in VIVILLON_FORM_SET:
            return ["bug", "flying"]
        types = POKEMON_TYPES.get(_type_key(name))
        if types:
            return types
    return []


def type_emoji_text(*names: str | None) -> str:
    return "".join(TYPE_EMOJIS[t] for t in pokemon_types_for(*names))


def format_typed_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    type_emojis: str,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> str:
    lines = format_spawn_mention_lines(
        reserved_user_ids, shinyhunter_user_ids, collection_user_ids
    )
    lines.append(f"{type_emojis} {format_guess(name, confidence, guess_name)}")
    if assisted:
        lines.append(f"**Copy Here >** `{format_catch_command(poketwo_bot_id, name)}`")
    return "\n".join(lines)


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
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        description=(
            f"`{format_catch_command(poketwo_bot_id, name)}`" if assisted else None
        )
    )
    embed.set_author(
        name=format_guess(name, confidence, guess_name),
        icon_url=f"attachment://{icon_filename}",
    )
    return embed


SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/{}.png"
)
SHINY_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/shiny/{}.png"
)
STARBOARD_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/home/{}.png"
)
STARBOARD_SHINY_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/home/shiny/{}.png"
)
PROJECT_POKEMON_SHINY_MODEL_URL = (
    "https://projectpokemon.org/images/shiny-sprite/{}.gif"
)
SHOWDOWN_ANIMATED_SHINY_SPRITE_URL = (
    "https://play.pokemonshowdown.com/sprites/ani-shiny/{}.gif"
)
SWSH_FORM_MODEL_SLUGS: Final[dict[str, str]] = {
    "Galarian Articuno": "articuno-galar",
    "Galarian Moltres": "moltres-galar",
    "Galarian Zapdos": "zapdos-galar",
}


@lru_cache(maxsize=1)
def load_sprite_ids() -> dict[str, int]:
    path = Path(__file__).with_name("pokemon_sprites.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sprite_url_for_pokemon(name: str, *, shiny: bool = False) -> str | None:
    sprite_id = load_sprite_ids().get(name)
    if not sprite_id:
        return None
    return (SHINY_SPRITE_URL if shiny else SPRITE_URL).format(sprite_id)


def starboard_sprite_url_for_pokemon(
    name: str,
    *,
    shiny: bool = False,
) -> str | None:
    sprite_id = load_sprite_ids().get(name)
    if not sprite_id:
        return None
    url = STARBOARD_SHINY_SPRITE_URL if shiny else STARBOARD_SPRITE_URL
    return url.format(sprite_id)


def pokemon_sprite_slug(name: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
        .replace("'", "")
        .replace("’", "")
    )
    for prefix, suffix in (
        ("alolan ", "alola"),
        ("galarian ", "galar"),
        ("hisuian ", "hisui"),
        ("paldean ", "paldea"),
    ):
        if normalized.startswith(prefix):
            normalized = f"{normalized[len(prefix):]} {suffix}"
            break
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


THUMBNAIL_ASSETS_DIR: Final[Path] = Path(__file__).with_name("assets") / "thumbnails"


def custom_thumbnail_path(name: str) -> Path | None:
    """Bundled thumbnail for Pokémon that PokeAPI has no artwork for."""
    filename = re.sub(r"[^a-z0-9]", "", normalize_pokemon_alias(name)) + ".png"
    path = THUMBNAIL_ASSETS_DIR / filename
    return path if path.is_file() else None


def catch_card_files(name: str, thumbnail_name: str | None = None) -> list[discord.File]:
    path = custom_thumbnail_path(thumbnail_name or name)
    return [discord.File(path, filename=path.name)] if path else []


def format_pc_catch_embed(
    name: str, thumbnail_name: str | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Catch {display_pokemon_name(shown_form_name(name, thumbnail_name))}",
        description=(
            f"Copy Below\n"
            f"```\n{format_catch_command(POKETWO_COMMAND_BOT_ID, name)}\n```"
        ),
    )
    custom_path = custom_thumbnail_path(thumbnail_name or name)
    sprite_url = sprite_url_for_pokemon(name)
    if custom_path:
        embed.set_thumbnail(url=f"attachment://{custom_path.name}")
    elif sprite_url:
        embed.set_thumbnail(url=sprite_url)
    return embed


@dataclass(frozen=True)
class CatchDetails:
    user_id: int | None
    pokemon: str
    level: str
    iv: str
    iv_value: float | None
    gender: str | None
    shiny: bool
    chain: int | None
    gigantamax: bool
    missingno: bool
    trainer: str | None = None


def parse_catch_details(text: str) -> CatchDetails | None:
    catch_match = re.search(r"\byou caught\b(?P<body>[^\n]*)", text, re.IGNORECASE)
    if catch_match is None:
        return None

    user_match = re.search(
        r"\bcongratulations\s+<@!?(\d+)>",
        text[: catch_match.start()],
        re.IGNORECASE,
    )
    if user_match is None:
        return None

    body = catch_match.group("body").strip()
    level_match = re.search(
        r"\b(?:level|lv\.?)\s*(\d+|\?{2,})",
        body,
        re.IGNORECASE,
    )
    if level_match is None:
        level = "???"
        pokemon_text = body.split("!", 1)[0].strip()
        pokemon_text = re.sub(r"^a\s+", "", pokemon_text, flags=re.IGNORECASE)
        pokemon_text = re.sub(
            r"\s*\(\s*(?:\d+(?:\.\d+)?|\?{2,})\s*%?\s*\)\s*$",
            "",
            pokemon_text,
        ).strip()
        if not is_missingno_name(pokemon_text):
            return None
    else:
        level = level_match.group(1)
        pokemon_text = body[level_match.end() :].strip()
        pokemon_text = re.sub(r"^[.!,:;]+\s*", "", pokemon_text)
        pokemon_text = pokemon_text.split("!", 1)[0].strip()
        pokemon_text = re.sub(
            r"\s*\(\s*(?:\d+(?:\.\d+)?|\?{2,})\s*%?\s*\)\s*$",
            "",
            pokemon_text,
        ).strip()

    gender = None
    if re.search(r"(?:♀|\bfemale\b)", pokemon_text, re.IGNORECASE):
        gender = "Female"
        pokemon_text = re.sub(r"(?:♀|\bfemale\b)", "", pokemon_text, flags=re.IGNORECASE)
    elif re.search(r"(?:♂|\bmale\b)", pokemon_text, re.IGNORECASE):
        gender = "Male"
        pokemon_text = re.sub(r"(?:♂|\bmale\b)", "", pokemon_text, flags=re.IGNORECASE)
    pokemon_text = pokemon_text.replace("’", "'").replace("‘", "'")
    pokemon_text = pokemon_text.strip(" .,:;")
    missingno = is_missingno_name(pokemon_text)
    if missingno:
        pokemon_text = "Missingno"
    elif not pokemon_text or not is_valid_pokemon_name(pokemon_text):
        return None

    iv_match = re.search(
        r"\(\s*(\d+(?:\.\d+)?|\?{2,})\s*%\s*\)"
        r"|\bIV\s*[:=]\s*(\d+(?:\.\d+)?|\?{2,})\s*%?",
        text,
        re.IGNORECASE,
    )
    iv_text = next((value for value in iv_match.groups() if value), None) if iv_match else None
    if missingno and iv_text is None:
        iv_text = "???"
    iv_value = None
    if iv_text and not iv_text.startswith("?"):
        numeric_iv = float(iv_text)
        if 0 <= numeric_iv <= 100:
            iv_value = numeric_iv
        else:
            iv_text = None
    iv = f"{iv_text}%" if iv_text and not iv_text.startswith("?") else (iv_text or "Unknown")

    shiny = bool(re.search(r"colors seem unusual|✨", text, re.IGNORECASE))
    chain_match = re.search(
        r"\b(?:shiny\s*(?:chain|streak)|chain|streak)\b[^\d]{0,30}(\d+)",
        text,
        re.IGNORECASE,
    )
    chain = int(chain_match.group(1)) if chain_match and shiny else None
    gigantamax = bool(
        re.search(r"\b(?:gigantamax|gmax)\b|gigantamax factor", text, re.IGNORECASE)
    )
    if gigantamax and not re.match(r"^(?:gigantamax|gmax)\b", pokemon_text, re.IGNORECASE):
        pokemon_text = f"Gigantamax {pokemon_text}"

    return CatchDetails(
        user_id=int(user_match.group(1)),
        pokemon=display_pokemon_name(pokemon_text),
        level=level,
        iv=iv,
        iv_value=iv_value,
        gender=gender,
        shiny=shiny,
        chain=chain,
        gigantamax=gigantamax,
        missingno=missingno,
    )


def is_catch_detection_embed(embed: discord.Embed) -> bool:
    title = embed.title or ""
    footer = embed.footer.text or ""
    return footer == "Catch Detection System" and re.search(
        r"\bCatch Detected!\s*$",
        title,
        re.IGNORECASE,
    ) is not None


def has_catch_detection_embed(message: discord.Message) -> bool:
    return any(is_catch_detection_embed(embed) for embed in message.embeds)


def is_automated_message(message: discord.Message) -> bool:
    return bool(
        getattr(message.author, "bot", False)
        or getattr(message, "webhook_id", None) is not None
        or getattr(message, "application_id", None) is not None
    )


def parse_catch_detection_details(message: discord.Message) -> CatchDetails | None:
    for embed in message.embeds:
        if not is_catch_detection_embed(embed):
            continue
        fields = {
            field.name.strip().rstrip(":").strip().casefold(): field.value.strip()
            for field in embed.fields
        }
        for line in (embed.description or "").splitlines():
            description_field = re.fullmatch(
                r"\s*`{0,3}\s*(trainer|pokemon|level|ivs?)\s*:\s*(.*?)\s*`{0,3}\s*",
                line,
                re.IGNORECASE,
            )
            if description_field is not None:
                name, value = description_field.groups()
                fields.setdefault(name.casefold(), value.strip())
        trainer = fields.get("trainer", "").strip()
        trainer_match = re.search(r"<@!?(\d+)>", trainer)
        pokemon_text = fields.get("pokemon", "").replace("’", "'").replace("‘", "'")
        level = fields.get("level", "???")
        iv_text = fields.get("ivs", fields.get("iv", ""))
        iv_match = re.search(r"(\d+(?:\.\d+)?)\s*%?", iv_text)
        missingno = is_missingno_name(pokemon_text)
        gender = None
        if re.search(r"(?:♀|\bfemale\b)", pokemon_text, re.IGNORECASE):
            gender = "Female"
            pokemon_text = re.sub(
                r"(?:♀|\bfemale\b)", "", pokemon_text, flags=re.IGNORECASE
            )
        elif re.search(r"(?:♂|\bmale\b)", pokemon_text, re.IGNORECASE):
            gender = "Male"
            pokemon_text = re.sub(
                r"(?:♂|\bmale\b)", "", pokemon_text, flags=re.IGNORECASE
            )
        pokemon_text = pokemon_text.strip(" .,:;")
        if missingno:
            pokemon_text = "Missingno"
        report_text = "\n".join(
            [embed.title or "", embed.description or ""]
            + [f"{field.name}: {field.value}" for field in embed.fields]
        )
        shiny = re.search(
            r"\bshiny\b|colors seem unusual|✨", report_text, re.IGNORECASE
        ) is not None
        gigantamax = re.search(
            r"\b(?:gigantamax|gmax)\b|gigantamax factor",
            report_text,
            re.IGNORECASE,
        ) is not None
        chain_match = re.search(
            r"\b(?:shiny\s*(?:chain|streak)|chain|streak)\b[^\d]{0,30}(\d+)",
            report_text,
            re.IGNORECASE,
        )
        if (
            (not missingno and not is_valid_pokemon_name(pokemon_text))
            or re.fullmatch(r"\d+|\?{2,}", level) is None
        ):
            continue
        iv_value = float(iv_match.group(1)) if iv_match else None
        if iv_value is not None and not 0 <= iv_value <= 100:
            continue
        if missingno and iv_value is None:
            iv_text = "???"
        iv = (
            f"{iv_value:g}%"
            if iv_value is not None
            else (iv_text if missingno and re.search(r"\?{2,}", iv_text) else "Unknown")
        )
        if gigantamax and not re.match(
            r"^(?:gigantamax|gmax)\b", pokemon_text, re.IGNORECASE
        ):
            pokemon_text = f"Gigantamax {pokemon_text}"
        return CatchDetails(
            user_id=int(trainer_match.group(1)) if trainer_match else None,
            pokemon=display_pokemon_name(pokemon_text),
            level=level,
            iv=iv,
            iv_value=iv_value,
            gender=gender,
            shiny=shiny,
            chain=int(chain_match.group(1)) if chain_match and shiny else None,
            gigantamax=gigantamax,
            missingno=missingno,
            trainer=trainer if trainer_match is None else None,
        )
    return None


def starboard_category(details: CatchDetails) -> str | None:
    if details.missingno:
        return "missingno"
    if details.gigantamax:
        return "gigantamax"
    if details.shiny:
        return "shiny"
    if details.iv_value is not None and details.iv_value >= 90:
        return "high_iv"
    if details.iv_value is not None and details.iv_value < 10:
        return "low_iv"
    return None


NORMAL_STARBOARD_POKEMON_NAMES: Final[frozenset[str]] = frozenset(
    normalize_pokemon_alias(name).replace("’", "'")
    for name in """
Alolan Ninetales
Alolan Vulpix
Alolan Geodude
Alolan Graveler
Alolan Raticate
Alolan Rattata
Alolan Persian
Alolan Meowth
Alolan Exeggutor
Alolan Dugtrio
Alolan Diglett
Alolan Grimer
Alolan Golem
Alolan Sandshrew
Alolan Sandslash
Alolan Marowak
Alolan Raichu
Alolan Muk
Galarian Linoone
Galarian Yamask
Galarian Slowpoke
Galarian Slowbro
Galarian Slowking
Galarian Farfetch'd
Galarian Rapidash
Galarian Ponyta
Galarian Mr. Mime
Galarian Weezing
Galarian Zigzagoon
Galarian Corsola
Galarian Meowth
Galarian Darumaka
Galarian Stunfisk
Galarian Darmanitan
Galarian Zen Darmanitan
Darmanitan Galar Zen
Obstagoon
Sirfetch'd
Cursola
Runerigus
Mr. Rime
Perrserker
Hisuian Growlithe
Hisuian Arcanine
Hisuian Electrode
Hisuian Voltorb
Hisuian Typhlosion
Hisuian Lilligant
Hisuian Samurott
Hisuian Sneasel
Hisuian Decidueye
Hisuian Qwilfish
Hisuian Braviary
Hisuian Avalugg
Hisuian Zoroark
Hisuian Zorua
Hisuian Sliggoo
Hisuian Goodra
Basculegion
Sneasler
Overqwil
Paldean Wooper
Combat Breed Tauros
Tauros Combat Breed
Blaze Breed Tauros
Tauros Blaze Breed
Aqua Breed Tauros
Tauros Aqua Breed
Articuno
Zapdos
Moltres
Mewtwo
Mew
Raikou
Entei
Suicune
Lugia
Ho-oh
Celebi
Regirock
Regice
Registeel
Latias
Latios
Kyogre
Groudon
Rayquaza
Jirachi
Deoxys
Attack Deoxys
Defense Deoxys
Speed Deoxys
Uxie
Mesprit
Azelf
Dialga
Palkia
Heatran
Regigigas
Giratina
Cresselia
Phione
Manaphy
Darkrai
Shaymin
Victini
Cobalion
Terrakion
Virizion
Tornadus
Thundurus
Reshiram
Zekrom
Landorus
Kyurem
Keldeo
Meloetta
Pirouette Meloetta
Yveltal
Diancie
Hoopa
Volcanion
Type: Null
Type Null
Tapu Koko
Tapu Lele
Tapu Bulu
Tapu Fini
Cosmog
Cosmoem
Solgaleo
Lunala
Nihilego
Buzzwole
Pheromosa
Xurkitree
Celesteela
Kartana
Guzzlord
Necrozma
Magearna
Marshadow
Zenith Marshadow
Poipole
Naganadel
Stakataka
Blacephalon
Zeraora
Meltan
Kubfu
Zarude
Dada Zarude
Regieleki
Regidrago
Glastrier
Spectrier
Calyrex
Enamorus
Wo-Chien
Chien-Pao
Ting-Lu
Chi-Yu
Okidogi
Munkidori
Fezandipiti
Terapagos
Pecharunt
Zacian
Zamazenta
Eternatus
Melmetal
Galarian Articuno
Galarian Moltres
Galarian Zapdos
""".splitlines()
    if name.strip()
)
NORMAL_STARBOARD_ALL_FORMS: Final[tuple[str, ...]] = (
    "Arceus",
    "Genesect",
    "Xerneas",
    "Zygarde",
    "Silvally",
    "Ogerpon",
    "Urshifu",
    "Koraidon",
    "Miraidon",
)


def is_normal_starboard_pokemon(pokemon_name: str) -> bool:
    pokemon_name = re.sub(
        r"^(?:gigantamax|gmax)\s+",
        "",
        pokemon_name,
        flags=re.IGNORECASE,
    )
    normalized_name = normalize_pokemon_alias(pokemon_name).replace("’", "'")
    if normalized_name in NORMAL_STARBOARD_POKEMON_NAMES:
        return True
    return any(
        pokemon_matches_all_forms_reservation(pokemon_name, species_name)
        for species_name in NORMAL_STARBOARD_ALL_FORMS
    )


def catch_starboard_destinations(
    details: CatchDetails,
    settings: dict[str, int | str | None],
) -> dict[int, str]:
    channel_ids: dict[str, int | None] = {}
    for key in ("normal_channel", "shiny_channel", "normal_pokemon_channel"):
        value = settings[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError(f"Invalid starboard channel ID in {key}")
        channel_ids[key] = value

    category = starboard_category(details)
    normal_pokemon_catch = is_normal_starboard_pokemon(details.pokemon)
    posts: dict[int, str] = {}
    normal_channel_id = channel_ids["normal_channel"]
    shiny_channel_id = channel_ids["shiny_channel"]
    normal_pokemon_channel_id = channel_ids["normal_pokemon_channel"]
    if category is not None and normal_channel_id is not None:
        posts[normal_channel_id] = category
    if details.shiny and shiny_channel_id is not None:
        posts.setdefault(shiny_channel_id, "shiny")
    if (
        normal_pokemon_catch
        and not details.shiny
        and normal_pokemon_channel_id is not None
    ):
        posts.setdefault(normal_pokemon_channel_id, "normal_pokemon")
    return posts


def starboard_art_url(
    details: CatchDetails,
    *,
    use_3d_shiny_model: bool = False,
) -> str | None:
    base_name = re.sub(
        r"^(?:gigantamax|gmax)\s+",
        "",
        details.pokemon,
        flags=re.IGNORECASE,
    )
    sprite_ids = load_sprite_ids()
    if base_name not in sprite_ids:
        base_name = next(
            (
                species_name
                for species_name in NORMAL_STARBOARD_ALL_FORMS
                if pokemon_matches_all_forms_reservation(base_name, species_name)
            ),
            base_name,
        )
    sprite_name = f"Gmax {base_name}" if details.gigantamax else base_name
    if sprite_name not in sprite_ids:
        sprite_name = base_name
    sprite_id = sprite_ids.get(sprite_name)
    regional_form = re.match(
        r"^(?:Alolan|Galarian|Hisuian|Paldean)\s+(.+)$",
        base_name,
        flags=re.IGNORECASE,
    )
    species_name = regional_form.group(1) if regional_form else base_name
    base_sprite_id = sprite_ids.get(species_name)
    regional_form_prefix = (
        base_name.split(maxsplit=1)[0].casefold() if regional_form else None
    )

    if use_3d_shiny_model and details.shiny:
        form_model_slug = SWSH_FORM_MODEL_SLUGS.get(base_name)
        if form_model_slug is not None:
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{form_model_slug}.gif"
            )
        if (
            details.gigantamax
            and sprite_id is not None
            and base_sprite_id is not None
            and 810 <= base_sprite_id <= 905
        ):
            slug = pokemon_sprite_slug(base_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}-gigantamax.gif"
            )
        if (
            sprite_id is not None
            and 810 <= sprite_id <= 905
            and not regional_form
        ):
            slug = pokemon_sprite_slug(sprite_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}.gif"
            )
        if (
            base_sprite_id is not None
            and 810 <= base_sprite_id <= 905
            and regional_form_prefix == "galarian"
        ):
            slug = pokemon_sprite_slug(base_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}.gif"
            )
        if (
            base_sprite_id is not None
            and base_sprite_id <= 809
            and regional_form_prefix not in {"hisuian", "paldean"}
        ):
            return PROJECT_POKEMON_SHINY_MODEL_URL.format(
                pokemon_sprite_slug(base_name)
            )
        return SHOWDOWN_ANIMATED_SHINY_SPRITE_URL.format(
            pokemon_sprite_slug(base_name)
        )
    return starboard_sprite_url_for_pokemon(sprite_name, shiny=details.shiny)


def format_starboard_embed(
    details: CatchDetails,
    category: str,
    caught_at: datetime,
    *,
    use_3d_shiny_model: bool = False,
    test_preview: bool = False,
) -> discord.Embed:
    titles = {
        "shiny": "✨ Shiny Capture ✨",
        "high_iv": "📈 High-IV Capture",
        "low_iv": "📉 Low-IV Capture",
        "missingno": "❔ MissingNo. Capture",
        "gigantamax": "🌟 Gigantamax Capture",
        "normal_pokemon": "⭐ Pokémon Spotlight",
    }
    caught_by = details.trainer or (
        f"<@{details.user_id}>" if details.user_id is not None else "Unknown"
    )
    description_lines = [
        f"**Caught by:** {caught_by}",
        f"**Pokémon:** {details.pokemon}",
    ]
    if category in {"high_iv", "low_iv"}:
        description_lines.extend(
            (f"**IV:** {details.iv}", f"**Level:** {details.level}")
        )
    else:
        description_lines.append(f"**Level:** {details.level}")
        if category != "gigantamax":
            description_lines.append(f"**IV:** {details.iv}")
    if category == "shiny":
        if details.gender:
            description_lines.append(f"**Gender:** {details.gender}")
        if details.chain is not None:
            description_lines.append(f"**Shiny chain:** {details.chain}")

    embed = discord.Embed(
        title=(
            f"🧪 TEST — {titles[category]}"
            if test_preview
            else titles[category]
        ),
        description="\n".join(description_lines),
        color=discord.Color(DEFAULT_EMBED_COLOR),
        timestamp=caught_at,
    )
    image_url = starboard_art_url(
        details,
        use_3d_shiny_model=use_3d_shiny_model,
    )
    footer_text = (
        "Test preview — not an actual catch" if test_preview else "Caught at"
    )
    if test_preview and image_url and image_url.startswith(
        "https://projectpokemon.org/images/sprites-models/"
    ):
        footer_text += " · 3D animation by PKParaiso via Project Pokémon"
    elif test_preview and image_url and image_url.startswith(
        "https://projectpokemon.org/images/shiny-sprite/"
    ):
        footer_text += " · 3D animation via Project Pokémon"
    elif test_preview and image_url and image_url.startswith(
        "https://play.pokemonshowdown.com/sprites/ani-shiny/"
    ):
        footer_text += " · Animated sprite via Pokémon Showdown"
    embed.set_footer(text=footer_text)
    if image_url:
        embed.set_thumbnail(url=image_url)
    return embed


def starboard_jump_view(jump_url: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Jump to message",
            emoji="🔗",
            style=discord.ButtonStyle.link,
            url=jump_url,
        )
    )
    return view


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


def clear_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> tuple[dict[str, list[int]], bool]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    guild_prefix = f"{guild_id}:"
    cleared = False
    for key in list(updated_shinyhunters):
        if not key.startswith(guild_prefix):
            continue
        user_ids = updated_shinyhunters[key]
        if user_id not in user_ids:
            continue
        user_ids.remove(user_id)
        cleared = True
        if not user_ids:
            del updated_shinyhunters[key]
    return updated_shinyhunters, cleared


def clear_guild_shinyhunts(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in shinyhunters.items()
        if not key.startswith(guild_prefix)
    }


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
            reservation_key_for_command(guild_id, pokemon_name),
            [],
        )
        if user_id not in user_ids:
            user_ids.append(user_id)
    return updated_collections


def migrate_legacy_all_keys(
    collections: dict[str, list[int]],
) -> dict[str, list[int]]:
    """Convert old literal "all <pokemon>" collection keys to all-forms keys."""
    migrated: dict[str, list[int]] = {}
    for key, user_ids in collections.items():
        guild_id, separator, name = key.partition(":")
        if separator and name.casefold().startswith("all "):
            key = f"{guild_id}:*:{name[4:].strip().casefold()}"
        merged = migrated.setdefault(key, [])
        merged.extend(user_id for user_id in user_ids if user_id not in merged)
    return migrated


def collection_pokemon_for_user(
    collections: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    return sorted(
        {
            name
            for key, user_ids in collections.items()
            if key.startswith(guild_prefix) and user_id in user_ids
            for name in format_reserved_pokemon_names(key.removeprefix(guild_prefix))
        }
    )


def split_collection_add_names(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> tuple[list[str], list[str]]:
    def is_added(name: str) -> bool:
        return user_id in collections.get(
            reservation_key_for_command(guild_id, name), []
        )

    already_added = [name for name in pokemon_names if is_added(name)]
    new_names = [name for name in pokemon_names if not is_added(name)]
    return new_names, already_added


def format_collection_add_confirmation(
    added_names: list[str],
    already_added_names: list[str],
) -> str:
    def display(name: str) -> str:
        if name.casefold().startswith("all "):
            return f"All forms of {name[4:].strip()}"
        return name[0].upper() + name[1:]

    lines = []
    if added_names:
        display_names = ", ".join(display(name) for name in added_names)
        lines.append(f"Added {display_names} to your collection.")
    if already_added_names:
        display_names = ", ".join(display(name) for name in already_added_names)
        lines.append(f"{display_names} already added to your collection.")
    return " ".join(lines)


def collection_user_ids_for_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[int]:
    return reserved_user_ids_for_pokemon(collections, guild_id, pokemon_name)


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
        key = reservation_key_for_command(guild_id, pokemon_name)
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


def clear_guild_collection(
    collections: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in collections.items()
        if not key.startswith(guild_prefix)
    }


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
    if stored_name.casefold().startswith("all "):
        stored_name = "*:" + stored_name[4:].strip()
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


@dataclass
class ChatEventSession:
    host_id: int
    channel: discord.abc.Messageable
    message: discord.Message | None = None
    participant_ids: set[int] = field(default_factory=set)
    sentence_counts: dict[int, int] = field(default_factory=dict)
    duration_seconds: float | None = None
    duration_label: str | None = None
    duration_selected: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    collecting: bool = False


def count_qualifying_sentences(content: str) -> int:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", content.strip())
    return sum(
        len(re.findall(r"\b[\w’'-]+\b", sentence)) >= 4
        for sentence in sentences
        if sentence
    )


def parse_chat_event_duration(value: str) -> tuple[float, str] | None:
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h)?\s*",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    amount = float(match.group(1))
    if not math.isfinite(amount) or amount <= 0:
        return None
    unit = (match.group(2) or "minutes").casefold()
    is_hours = unit.startswith("h")
    seconds = amount * (3600 if is_hours else 60)
    if not math.isfinite(seconds):
        return None
    normalized_unit = "hour" if is_hours else "minute"
    label = f"{amount:g} {normalized_unit}{'' if amount == 1 else 's'}"
    return seconds, label


class EventMenuView(discord.ui.View):
    def __init__(self, bot: "NamingBot", host_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.host_id = host_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "Only the person who started `v!event` can choose an event.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Chat event",
        style=discord.ButtonStyle.primary,
        custom_id="event_menu:chat",
    )
    async def chat_event(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.bot.start_chat_event(interaction, self.host_id)


class ChatEventDurationView(discord.ui.View):
    def __init__(self, session: ChatEventSession) -> None:
        super().__init__(timeout=300)
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "Only the event host can choose the duration.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.session.cancelled = True
        self.session.duration_selected.set()

    @discord.ui.button(
        label="Enter duration",
        style=discord.ButtonStyle.primary,
        custom_id="chat_event:enter_duration",
    )
    async def enter_duration(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(ChatEventDurationModal(self.session))


class ChatEventDurationModal(discord.ui.Modal):
    def __init__(self, session: ChatEventSession) -> None:
        super().__init__(title="Chat event duration")
        self.session = session
        self.duration_input = discord.ui.TextInput(
            label="How long should the event last?",
            placeholder="For example: 7 minutes or 2 hours",
            required=True,
            max_length=32,
        )
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "Only the event host can choose the duration.",
                ephemeral=True,
            )
            return
        parsed_duration = parse_chat_event_duration(self.duration_input.value)
        if parsed_duration is None:
            await interaction.response.send_message(
                "Enter a positive duration in minutes or hours, such as `7 minutes` "
                "or `2 hours`. A number by itself is treated as minutes.",
                ephemeral=True,
            )
            return
        self.session.duration_seconds, self.session.duration_label = parsed_duration
        self.session.duration_selected.set()
        await interaction.response.send_message(
            f"Chat event duration set to {self.session.duration_label}.",
            ephemeral=True,
        )


class InertSettingsButton(discord.ui.Button):
    def __init__(self, section: str) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id=f"server_settings:open:{section}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class NamingSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:naming",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=NamingSettingsView(self.bot, self.guild_id)
        )


class NamingSettingToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        setting: str,
        enabled: bool,
    ) -> None:
        if setting == "assisted":
            label = "Assisted" if enabled else "Name only"
        else:
            label = "On" if enabled else "Off"
        super().__init__(
            label=label,
            style=(
                discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.secondary
            ),
            custom_id=f"server_settings:naming:{setting}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.setting = setting

    async def callback(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild_id != self.guild_id
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                "Only members with Manage Server permission can change these settings.",
                ephemeral=True,
            )
            return
        try:
            self.bot.toggle_naming_setting(self.guild_id, self.setting)
        except ValueError:
            logger.exception("Could not save naming settings for guild %s", self.guild_id)
            await interaction.response.send_message(
                "I couldn't save these settings. Check the bot logs.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=NamingSettingsView(self.bot, self.guild_id)
        )


class AFKSettingToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        user_id: int,
        setting: str,
        enabled: bool,
    ) -> None:
        super().__init__(
            label="On" if enabled else "Off",
            style=(
                discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.danger
            ),
            custom_id=f"afk_settings:{setting}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.setting = setting

    async def callback(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild_id != self.guild_id
            or interaction.user.id != self.user_id
        ):
            await interaction.response.send_message(
                "Only the member who opened these AFK settings can change them.",
                ephemeral=True,
            )
            return
        try:
            self.bot.toggle_afk_setting(
                self.guild_id, self.user_id, self.setting
            )
        except ValueError:
            logger.exception(
                "Could not save AFK settings for guild %s user %s",
                self.guild_id,
                self.user_id,
            )
            await interaction.response.send_message(
                "I couldn't save your AFK settings. Check the bot logs.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=AFKSettingsView(self.bot, self.guild_id, self.user_id)
        )


class AFKSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int, user_id: int) -> None:
        super().__init__(timeout=300)
        settings = bot.afk_settings_for_user(guild_id, user_id)
        status = (
            "🟢 Receiving pings"
            if all(settings.values())
            else "🔴 AFK (muted)"
        )
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# AFK Settings\n"
                f"{status}\n"
                "Choose which Pokémon notifications you want to receive."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Shiny Hunt\n"
                    f"{'Receiving pings' if settings['shinyhunt'] else 'AFK (muted)'}"
                ),
                accessory=AFKSettingToggleButton(
                    bot, guild_id, user_id, "shinyhunt", settings["shinyhunt"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Collection\n"
                    f"{'Receiving pings' if settings['collection'] else 'AFK (muted)'}"
                ),
                accessory=AFKSettingToggleButton(
                    bot, guild_id, user_id, "collection", settings["collection"]
                ),
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


class NamingSettingsBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:naming:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class StarboardSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:starboard",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class ServerSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        settings = bot.naming_settings_for_guild(guild_id)
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# ⚙️ Vivillon Control Panel\n"
                "Choose a section below. Changes save instantly."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🏷️ Naming\n"
                    f"{'🟢 On' if settings['enabled'] else '🔴 Off'}  •  "
                    f"{'Assisted' if settings['assisted'] else 'Name only'}"
                ),
                accessory=NamingSectionButton(bot, guild_id),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🔔 Roles & Pings\n"
                    "Ping roles plus rare, regional, hunt, collection, "
                    "reserve and quest output."
                ),
                accessory=InertSettingsButton("roles"),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### ⭐ Starboard\n"
                    "Vivillon, Shiny, and Normal Starboard channels."
                ),
                accessory=StarboardSectionButton(bot, guild_id),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🎨 Appearance\n"
                    "Server profile, banner and embed color."
                ),
                accessory=AppearanceSectionButton(bot, guild_id),
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "-# Settings are stored for this server. To have them removed, "
                "open a ticket in the support server:\n"
                "-# https://discord.gg/5XurUaW8"
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


async def starboard_settings_guard(
    interaction: discord.Interaction, guild_id: int
) -> bool:
    if interaction.guild_id != guild_id:
        await interaction.response.send_message(
            "These settings can only be used in their original server.",
            ephemeral=True,
        )
        return False
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions is None or not permissions.manage_guild:
        await interaction.response.send_message(
            "You need the Manage Server permission to change starboards.",
            ephemeral=True,
        )
        return False
    return True


class StarboardChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot: "NamingBot", guild_id: int, board: str) -> None:
        placeholders = {
            "normal": "Choose the Vivillon Starboard channel",
            "shiny": "Choose the shinyboard channel",
            "normal_pokemon": "Choose the Normal Starboard channel",
        }
        super().__init__(
            channel_types=[discord.ChannelType.text],
            placeholder=placeholders[board],
            custom_id=f"server_settings:starboard:select:{board}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.board = board

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await starboard_settings_guard(interaction, self.guild_id):
            return
        channel = self.values[0]
        if getattr(getattr(channel, "guild", None), "id", None) != self.guild_id:
            await interaction.response.send_message(
                "Choose a channel from this server.",
                ephemeral=True,
            )
            return
        try:
            self.bot.set_starboard_channel(
                self.guild_id,
                self.board,
                channel.id,
                getattr(channel, "name", None),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class StarboardClearButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int, board: str) -> None:
        labels = {
            "normal": "Clear Vivillon",
            "shiny": "Clear Shiny",
            "normal_pokemon": "Clear Normal",
        }
        super().__init__(
            label=labels[board],
            style=discord.ButtonStyle.secondary,
            custom_id=f"server_settings:starboard:clear:{board}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.board = board

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await starboard_settings_guard(interaction, self.guild_id):
            return
        try:
            self.bot.set_starboard_channel(self.guild_id, self.board, None)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class StarboardBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:starboard:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class StarboardSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        settings = bot.starboard_settings_for_guild(guild_id)
        vivillon_channel = settings["normal_channel"]
        shiny_channel = settings["shiny_channel"]
        normal_channel = settings["normal_pokemon_channel"]
        shiny_count = settings["shiny_count"]
        vivillon_text = (
            f"<#{vivillon_channel}>" if vivillon_channel else "`Not set`"
        )
        shiny_text = f"<#{shiny_channel}>" if shiny_channel else "`Not set`"
        normal_text = f"<#{normal_channel}>" if normal_channel else "`Not set`"
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# ⭐ Catch Starboards\n"
                "Choose where special catches are posted. Changes save instantly."
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "### Vivillon Starboard\n"
                f"Current channel: {vivillon_text}\n"
                "Receives shiny, high-IV (90%+), low-IV (under 10%), "
                "MissingNo., and Gigantamax catches."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "normal")
            ),
            discord.ui.TextDisplay(
                "### Shinyboard\n"
                f"Current channel: {shiny_text} · Caught shinies: {shiny_count}\n"
                "Receives shiny catches and increments the channel suffix "
                "(for example, `shiny-board-1`). The bot needs Manage Channels "
                "permission to rename it. A shiny catch is also posted to the "
                "Vivillon Starboard."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "shiny")
            ),
            discord.ui.TextDisplay(
                "### Normal Starboard\n"
                f"Current channel: {normal_text}\n"
                "Receives catches for the configured regional forms and "
                "featured Pokémon."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "normal_pokemon")
            ),
            discord.ui.ActionRow(
                StarboardClearButton(bot, guild_id, "normal"),
                StarboardClearButton(bot, guild_id, "shiny"),
                StarboardClearButton(bot, guild_id, "normal_pokemon"),
            ),
            discord.ui.Separator(),
            discord.ui.ActionRow(StarboardBackButton(bot, guild_id)),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


DEFAULT_EMBED_COLOR: Final[int] = 0x5865F2
APPEARANCE_MAX_BYTES: Final[int] = 10 * 1024 * 1024
APPEARANCE_IMAGE_TYPES: Final[tuple[str, ...]] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)


def load_appearance(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_appearance(path: Path, data: dict[str, dict]) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save appearance to {path}") from error


def parse_hex_color(text: str) -> int | None:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", text.strip())
    return int(match.group(1), 16) if match else None


async def appearance_guard(
    interaction: discord.Interaction, guild_id: int
) -> bool:
    if interaction.guild_id != guild_id:
        await interaction.response.send_message(
            "These settings can only be used in their original server.",
            ephemeral=True,
        )
        return False
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions is None or not permissions.manage_guild:
        await interaction.response.send_message(
            "You need the Manage Server permission to change appearance.",
            ephemeral=True,
        )
        return False
    return True


class AppearanceSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:appearance",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self.bot, self.guild_id)
        )


class AppearanceActionButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        action: str,
        label: str,
        style: discord.ButtonStyle,
    ) -> None:
        super().__init__(
            label=label,
            style=style,
            custom_id=f"server_settings:appearance:{action}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id):
            return
        if self.action == "color":
            await interaction.response.send_modal(
                AppearanceTextModal(self.bot, self.guild_id, "color")
            )
        elif self.action == "name":
            await interaction.response.send_modal(
                AppearanceTextModal(self.bot, self.guild_id, "name")
            )
        elif self.action in ("avatar", "banner"):
            await interaction.response.send_modal(
                AppearanceUploadModal(self.bot, self.guild_id, self.action)
            )
        else:
            await self.bot.reset_appearance(
                interaction, self.guild_id, self.action
            )


class AppearanceTextModal(discord.ui.Modal):
    def __init__(self, bot: "NamingBot", guild_id: int, field: str) -> None:
        super().__init__(
            title="Set Embed Color" if field == "color" else "Set Bot Name"
        )
        self.bot = bot
        self.guild_id = guild_id
        self.field = field
        self.value = discord.ui.TextInput(
            label="Hex color (e.g. #FCE5E7)" if field == "color" else "Bot name",
            placeholder="#FCE5E7" if field == "color" else "Leave empty to reset",
            required=field == "color",
            max_length=7 if field == "color" else 32,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id):
            return
        text = self.value.value.strip()
        if self.field == "color":
            color = parse_hex_color(text)
            if color is None:
                await interaction.response.send_message(
                    "That isn't a valid hex color. Use six digits like `#FCE5E7`.",
                    ephemeral=True,
                )
                return
            self.bot.update_appearance(self.guild_id, color=color)
        else:
            try:
                await interaction.guild.me.edit(nick=text or None)
            except discord.HTTPException as error:
                await interaction.response.send_message(
                    f"I couldn't change my name: {error}", ephemeral=True
                )
                return
            self.bot.update_appearance(self.guild_id, name=text or None)
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self.bot, self.guild_id)
        )


class AppearanceUploadModal(discord.ui.Modal):
    def __init__(self, bot: "NamingBot", guild_id: int, field: str) -> None:
        label = "Bot Profile Image" if field == "avatar" else "Bot Server Banner"
        super().__init__(title=f"Upload {label}")
        self.bot = bot
        self.guild_id = guild_id
        self.field = field
        self.upload = discord.ui.FileUpload(min_values=1, max_values=1)
        self.add_item(
            discord.ui.Label(
                text="Profile Image" if field == "avatar" else "Server Banner",
                description="PNG, JPEG, GIF, or WEBP; maximum 10 MB.",
                component=self.upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id):
            return
        if not self.upload.values:
            await interaction.response.send_message(
                "No file was uploaded.", ephemeral=True
            )
            return
        await self.bot.apply_appearance_image(
            interaction, self.guild_id, self.field, self.upload.values[0]
        )


class AppearanceBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:appearance:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class AppearanceSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        data = bot.appearance.get(str(guild_id), {})
        color = data.get("color")
        primary = discord.ButtonStyle.primary
        danger = discord.ButtonStyle.danger

        def action(name: str, label: str, style: discord.ButtonStyle):
            return AppearanceActionButton(bot, guild_id, name, label, style)

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# Server Settings · Appearance\n"
                "-# Configure this section, then use Back to choose another."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Profile Image**\n"
                    f"`{'Custom' if data.get('avatar') else 'Default'}`\n"
                    "Upload a PNG, JPEG, GIF, or WEBP image up to 10 MB."
                ),
                accessory=action("avatar", "Upload", primary),
            ),
            discord.ui.ActionRow(action("avatar_reset", "Reset Profile Image", danger)),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Server Banner**\n"
                    f"`{'Custom' if data.get('banner') else 'Default'}`\n"
                    "The banner appears only on Vivillon's profile in this server."
                ),
                accessory=action("banner", "Upload", primary),
            ),
            discord.ui.ActionRow(action("banner_reset", "Reset Server Banner", danger)),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Embed Color**\n"
                    f"`#{(color if color is not None else DEFAULT_EMBED_COLOR):06X}`"
                    f" · {'Custom' if color is not None else 'Default'}\n"
                    "Replaces Vivillon's default blue on embeds in this server."
                ),
                accessory=action("color", "Set Color", primary),
            ),
            discord.ui.ActionRow(action("color_reset", "Reset Embed Color", danger)),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Bot Name**\n"
                    f"`{data.get('name') or 'Default'}`\n"
                    "Changes Vivillon's nickname in this server."
                ),
                accessory=action("name", "Set Name", primary),
            ),
            discord.ui.ActionRow(action("name_reset", "Reset Bot Name", danger)),
            discord.ui.Separator(),
            discord.ui.ActionRow(AppearanceBackButton(bot, guild_id)),
            accent_color=discord.Color(
                color if color is not None else DEFAULT_EMBED_COLOR
            ),
        )
        self.add_item(container)


class NamingSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        settings = bot.naming_settings_for_guild(guild_id)
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# 🏷️ Naming Settings\n"
                "Tap a button to switch a setting. Use Back when you're done."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Naming\n"
                    f"{'🟢 On' if settings['enabled'] else '🔴 Off'}\n"
                    "Allow Vivillon to send Pokémon predictions."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "enabled", settings["enabled"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Naming Mode\n"
                    f"{'🟢 Assisted' if settings['assisted'] else '⚪ Name only'}\n"
                    "Assisted mode adds copy-ready catch commands."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "assisted", settings["assisted"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Pings\n"
                    f"{'🟢 On' if settings['pings'] else '🔴 Off'}\n"
                    "Only name Pokémon when a collection, shinyhunt, or reserve "
                    "member should be pinged."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "pings", settings["pings"]
                ),
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay("↩️ Back to the Control Panel."),
                accessory=NamingSettingsBackButton(bot, guild_id),
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


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


NAME_SUGGESTION_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "all", "normal", "mega", "alolan", "galarian", "hisuian", "paldean",
        "gmax", "gigantamax", "primal",
    }
)
NAME_SUGGESTION_CUTOFF: Final[float] = 0.6
NAME_SUGGESTION_TIMEOUT_SECONDS: Final[int] = 60


@lru_cache(maxsize=1)
def known_name_lookup() -> dict[str, str]:
    return {
        normalize_pokemon_alias(name): name for name in load_known_pokemon_names()
    }


def strip_name_prefixes(name: str) -> tuple[list[str], list[str]]:
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    prefix_count = 0
    while (
        prefix_count < len(words) - 1
        and words[prefix_count] in NAME_SUGGESTION_PREFIXES
    ):
        prefix_count += 1
    return words[:prefix_count], words[prefix_count:]


def is_known_pokemon_name(name: str) -> bool:
    lookup = known_name_lookup()
    if normalize_pokemon_alias(name.replace("’", "'")) in lookup:
        return True
    _, base = strip_name_prefixes(name)
    base_name = " ".join(base)
    return base_name in lookup or is_missingno_name(base_name)


@lru_cache(maxsize=1)
def known_name_word_sets() -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(sorted(name.split(" "))) for name in known_name_lookup())


def is_known_pokemon_name(name: str) -> bool:
    lookup = known_name_lookup()
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    if " ".join(words) in lookup or tuple(sorted(words)) in known_name_word_sets():
        return True
    prefix_count = 0
    while prefix_count < len(words) - 1 and words[prefix_count] in NAME_SUGGESTION_PREFIXES:
        prefix_count += 1
    base = " ".join(words[prefix_count:])
    return base in lookup or is_missingno_name(base)


def suggest_pokemon_name(name: str) -> str | None:
    """Return a corrected name when `name` looks like a misspelled Pokémon."""
    import difflib

    lookup = known_name_lookup()
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    prefix_count = 0
    while prefix_count < len(words) - 1 and words[prefix_count] in NAME_SUGGESTION_PREFIXES:
        prefix_count += 1
    base = " ".join(words[prefix_count:])
    if not base or base in lookup or is_missingno_name(base):
        return None
    matches = difflib.get_close_matches(
        base, list(lookup), n=1, cutoff=NAME_SUGGESTION_CUTOFF
    )
    if not matches:
        return None
    suggestion = lookup[matches[0]]
    prefix = " ".join(words[:prefix_count])
    original_prefix = " ".join(name.split()[:prefix_count])
    return f"{original_prefix} {suggestion}".strip() if prefix else suggestion


def _org_api_port_from_environment() -> int:
    for variable in ("ORG_API_PORT", "SERVER_PORT", "PORT"):
        value = os.environ.get(variable)
        if value:
            try:
                return int(value)
            except ValueError as error:
                raise ValueError(f"{variable} must be a valid port number") from error
    return 8080


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


SERVER_NAMING_DEFAULTS: Final[dict[str, bool]] = {
    "enabled": True,
    "assisted": True,
    "pings": False,
}
SERVER_NAMING_SETTING_KEYS: Final[frozenset[str]] = frozenset(
    SERVER_NAMING_DEFAULTS
)


def load_server_settings(path: Path) -> dict[str, dict[str, bool]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read server settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Server settings in {path} have an invalid format")

    settings: dict[str, dict[str, bool]] = {}
    for guild_id, guild_settings in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(guild_settings, dict)
            or any(
                key not in SERVER_NAMING_SETTING_KEYS
                or not isinstance(value, bool)
                for key, value in guild_settings.items()
            )
        ):
            raise ValueError(f"Server settings in {path} have an invalid entry")
        settings[guild_id] = {
            **SERVER_NAMING_DEFAULTS,
            **guild_settings,
        }
    return settings


def save_server_settings(
    path: Path,
    settings: dict[str, dict[str, bool]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save server settings to {path}") from error


STARBOARD_DEFAULTS: Final[dict[str, int | str | None]] = {
    "normal_channel": None,
    "shiny_channel": None,
    "normal_pokemon_channel": None,
    "shiny_base_name": None,
    "shiny_count": 0,
}
STARBOARD_SETTING_KEYS: Final[frozenset[str]] = frozenset(STARBOARD_DEFAULTS)
STARBOARD_CHANNEL_SETTING_KEYS: Final[dict[str, str]] = {
    "normal": "normal_channel",
    "shiny": "shiny_channel",
    "normal_pokemon": "normal_pokemon_channel",
}


def split_channel_counter(channel_name: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)-(\d+)", channel_name.strip())
    if match is None:
        return channel_name.strip(), 0
    return match.group(1), int(match.group(2))


def load_starboard_settings(
    path: Path,
) -> dict[str, dict[str, int | str | None]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read starboard settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Starboard settings in {path} have an invalid format")

    settings: dict[str, dict[str, int | str | None]] = {}
    for guild_id, guild_settings in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(guild_settings, dict)
            or any(
                key not in STARBOARD_SETTING_KEYS or not valid_starboard_setting(key, value)
                for key, value in guild_settings.items()
            )
        ):
            raise ValueError(f"Starboard settings in {path} have an invalid entry")
        settings[guild_id] = {
            **STARBOARD_DEFAULTS,
            **guild_settings,
        }
    return settings


def save_starboard_settings(
    path: Path,
    settings: dict[str, dict[str, int | str | None]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save starboard settings to {path}") from error


def valid_starboard_setting(key: str, value: object) -> bool:
    if key in STARBOARD_CHANNEL_SETTING_KEYS.values():
        return value is None or (
            isinstance(value, int) and not isinstance(value, bool) and value > 0
        )
    if key == "shiny_base_name":
        return value is None or (
            isinstance(value, str) and bool(value.strip()) and len(value) <= 100
        )
    if key == "shiny_count":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return False


AFK_DEFAULTS: Final[dict[str, bool]] = {
    "shinyhunt": True,
    "collection": True,
}
AFK_SETTING_KEYS: Final[frozenset[str]] = frozenset(AFK_DEFAULTS)


def load_afk_settings(path: Path) -> dict[str, dict[str, bool]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read AFK settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"AFK settings in {path} have an invalid format")

    settings: dict[str, dict[str, bool]] = {}
    for user_key, user_settings in data.items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(user_settings, dict)
            or any(
                key not in AFK_SETTING_KEYS or not isinstance(value, bool)
                for key, value in user_settings.items()
            )
        ):
            raise ValueError(f"AFK settings in {path} have an invalid entry")
        settings[user_key] = {**AFK_DEFAULTS, **user_settings}
    return settings


def save_afk_settings(
    path: Path,
    settings: dict[str, dict[str, bool]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save AFK settings to {path}") from error


def valid_profile_setting(setting: str, value: object) -> bool:
    if setting == "catches":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    choices = PROFILE_SETTING_CHOICES.get(setting)
    legacy_choices = PROFILE_LEGACY_CHOICES.get(setting, frozenset())
    return (
        isinstance(value, str)
        and choices is not None
        and (value in choices or value in legacy_choices)
    )


def load_profile_data(
    path: Path,
) -> tuple[
    dict[str, dict[str, int | str]],
    dict[str, dict[str, int]],
    list[int],
]:
    if not path.exists():
        return {}, {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read profile data from {path}") from error
    legacy_keys = {"users", "seen_catch_message_ids"}
    current_keys = legacy_keys | {"server_stats"}
    if (
        not isinstance(data, dict)
        or set(data) not in (legacy_keys, current_keys)
        or not isinstance(data["users"], dict)
        or not isinstance(data["seen_catch_message_ids"], list)
        or (
            "server_stats" in data
            and not isinstance(data["server_stats"], dict)
        )
    ):
        raise ValueError(f"Profile data in {path} has an invalid format")

    profiles: dict[str, dict[str, int | str]] = {}
    for user_id, stored_settings in data["users"].items():
        if (
            not isinstance(user_id, str)
            or not user_id.isdecimal()
            or not isinstance(stored_settings, dict)
            or any(
                setting not in PROFILE_DEFAULTS and setting != "catches"
                or not valid_profile_setting(setting, value)
                for setting, value in stored_settings.items()
            )
        ):
            raise ValueError(f"Profile data in {path} has an invalid user entry")
        profile = {
            **PROFILE_DEFAULTS,
            **{
                setting: value
                for setting, value in stored_settings.items()
                if setting != "catches"
            },
        }
        for setting, legacy_choices in PROFILE_LEGACY_CHOICES.items():
            if profile[setting] in legacy_choices:
                profile[setting] = PROFILE_DEFAULTS[setting]
        profiles[user_id] = profile

    profile_stats: dict[str, dict[str, int]] = {}
    for user_key, stored_stats in data.get("server_stats", {}).items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(stored_stats, dict)
            or any(
                stat not in PROFILE_STAT_DEFAULTS
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for stat, value in stored_stats.items()
            )
        ):
            raise ValueError(f"Profile data in {path} has an invalid server stat")
        profile_stats[user_key] = {
            **PROFILE_STAT_DEFAULTS,
            **stored_stats,
        }

    seen_catch_ids = data["seen_catch_message_ids"]
    if any(
        isinstance(message_id, bool)
        or not isinstance(message_id, int)
        or message_id <= 0
        for message_id in seen_catch_ids
    ):
        raise ValueError(f"Profile data in {path} has invalid catch message IDs")
    return profiles, profile_stats, seen_catch_ids[-10000:]


def save_profile_data(
    path: Path,
    profiles: dict[str, dict[str, int | str]],
    profile_stats: dict[str, dict[str, int]],
    seen_catch_ids: list[int],
) -> None:
    data = {
        "users": profiles,
        "server_stats": profile_stats,
        "seen_catch_message_ids": seen_catch_ids[-10000:],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save profile data to {path}") from error


def profile_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    font_path = Path("/usr/share/fonts/truetype/dejavu") / filename
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        return ImageFont.load_default(size=size)


def draw_profile_stat_icon(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    name: str,
    position: tuple[int, int],
    emoji_assets: dict[str, bytes],
) -> None:
    x, y = position
    asset = emoji_assets.get(name)
    if asset is not None:
        try:
            with Image.open(BytesIO(asset)) as emoji:
                emoji_image = emoji.convert("RGBA")
            emoji_image.thumbnail((36, 36), Image.Resampling.LANCZOS)
            image.paste(emoji_image, (x, y), emoji_image)
            return
        except OSError as error:
            logger.warning("Could not render profile emoji %s: %s", name, error)

    if name == "shiny":
        draw.polygon(
            [
                (x + 17, y),
                (x + 22, y + 12),
                (x + 35, y + 17),
                (x + 22, y + 22),
                (x + 17, y + 35),
                (x + 12, y + 22),
                (x, y + 17),
                (x + 12, y + 12),
            ],
            fill="#F4D06F",
        )
    elif name in {"low_iv", "high_iv"}:
        color = "#F05B63" if name == "low_iv" else "#52C788"
        points = (
            [(x + 3, y + 5), (x + 12, y + 13), (x + 21, y + 18), (x + 32, y + 29)]
            if name == "low_iv"
            else [(x + 3, y + 29), (x + 12, y + 21), (x + 21, y + 15), (x + 32, y + 4)]
        )
        draw.line(points, fill=color, width=4)
        end_x, end_y = points[-1]
        direction = 1 if name == "low_iv" else -1
        draw.polygon(
            [
                (end_x, end_y),
                (end_x - 10, end_y - 2 * direction),
                (end_x - 3, end_y - 10 * direction),
            ],
            fill=color,
        )
    elif name == "gmax":
        draw.ellipse((x + 2, y + 2, x + 34, y + 34), fill="#E84B4B")
        draw.rectangle((x + 3, y + 15, x + 33, y + 21), fill="#FFFFFF")
        draw.ellipse((x + 12, y + 12, x + 24, y + 24), fill="#FFFFFF")
        draw.ellipse((x + 15, y + 15, x + 21, y + 21), fill="#303036")
    else:
        draw.rectangle((x + 3, y + 3, x + 33, y + 33), fill="#9A72B8")
        draw.text((x + 8, y + 3), "?", font=profile_font(27, bold=True), fill="#FFFFFF")


def render_profile_image(
    settings: dict[str, int | str],
    stats: dict[str, int],
    emoji_assets: dict[str, bytes] | None = None,
) -> BytesIO:
    width, height = 1400, 825
    background_key = str(settings["background"])
    middle_key = str(settings["middle_background"])
    text_color_key = str(settings["text_color"])
    background = PROFILE_BACKGROUNDS[background_key][1]
    middle_background = PROFILE_MIDDLE_BACKGROUNDS[middle_key][1]
    text_color = PROFILE_TEXT_COLORS[text_color_key][1]

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((430, 0, 949, height - 1), fill=middle_background)
    heading_font = profile_font(36, bold=True)
    stat_font = profile_font(30)
    draw.text((64, 245), "Pokemon Catches", font=heading_font, fill=text_color)
    rows = (
        ("Total", "total", None),
        ("Shiny", "shiny", "shiny"),
        ("Low IV", "low_iv", "low_iv"),
        ("High IV", "high_iv", "high_iv"),
        ("Gmax", "gmax", "gmax"),
        ("Missingno", "missingno", "missingno"),
    )
    for index, (label, stat, icon) in enumerate(rows):
        y = 310 + index * 50
        draw.text(
            (64, y),
            f"{label}: {stats[stat]:,}",
            font=stat_font,
            fill=text_color,
        )
        if icon is not None:
            draw_profile_stat_icon(
                image,
                draw,
                icon,
                (370, y - 2),
                emoji_assets or {},
            )

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


class ProfileEditSelect(discord.ui.Select):
    def __init__(
        self,
        profile_view: "ProfileView",
        setting: str,
        row: int,
    ) -> None:
        self.profile_view = profile_view
        self.setting = setting
        current_value = profile_view.bot.profile_settings_for_user(
            profile_view.user_id
        )[setting]
        choices = PROFILE_SETTING_CHOICES[setting]
        super().__init__(
            placeholder=PROFILE_SETTING_LABELS[setting],
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                    default=value == current_value,
                )
                for value, (label, description) in choices.items()
            ],
            min_values=1,
            max_values=1,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.profile_view.user_id:
            await interaction.response.send_message(
                "Only the member who opened this profile can edit it.",
                ephemeral=True,
            )
            return
        try:
            self.profile_view.bot.set_profile_setting(
                self.profile_view.user_id,
                self.setting,
                self.values[0],
            )
        except ValueError:
            logger.exception(
                "Could not save profile settings for user %s",
                self.profile_view.user_id,
            )
            await interaction.response.send_message(
                "I couldn't save your profile settings. Check the bot logs.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            await self.profile_view.refresh()
            await interaction.message.edit(
                view=ProfileEditView(self.profile_view)
            )
        except discord.HTTPException:
            logger.exception(
                "Could not update profile display for user %s",
                self.profile_view.user_id,
            )
            await interaction.followup.send(
                "Your setting was saved, but I couldn't refresh the profile image.",
                ephemeral=True,
            )


class ProfileEditView(discord.ui.View):
    def __init__(self, profile_view: "ProfileView") -> None:
        super().__init__(timeout=300)
        for row, setting in enumerate(PROFILE_SETTING_LABELS):
            self.add_item(ProfileEditSelect(profile_view, setting, row))


class ProfileEditButton(discord.ui.Button):
    def __init__(self, profile_view: "ProfileView") -> None:
        super().__init__(
            label="Edit",
            style=discord.ButtonStyle.secondary,
            custom_id="profile:edit",
        )
        self.profile_view = profile_view

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.profile_view.user_id:
            await interaction.response.send_message(
                "Only the member who opened this profile can edit it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Choose your profile colors and appearance.",
            view=ProfileEditView(self.profile_view),
            ephemeral=False,
        )


class ProfileView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        user_id: int,
        guild_id: int,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.message: discord.Message | None = None
        self.add_item(ProfileEditButton(self))

    async def refresh(self) -> None:
        if self.message is None:
            return
        settings = self.bot.profile_settings_for_user(self.user_id)
        stats = self.bot.profile_stats_for_user(self.guild_id, self.user_id)
        emoji_assets = await self.bot.load_profile_emoji_assets()
        await self.message.edit(
            attachments=[
                discord.File(
                    render_profile_image(settings, stats, emoji_assets),
                    filename="profile.png",
                )
            ],
            view=self,
        )


class NamingBot(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.time_tasks: dict[int, asyncio.Task] = {}
        self.openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=config.openai_api_key, max_retries=1, timeout=10.0)
            if config.openai_api_key
            else None
        )
        self.vision_semaphore = asyncio.Semaphore(
            config.max_concurrent_vision_requests
        )
        self.image_http: aiohttp.ClientSession | None = None
        image_bank_file = os.environ.get("IMAGE_BANK_FILE")
        self.image_matcher = ImageMatcher(
            Path(image_bank_file)
            if image_bank_file
            else Path(__file__).with_name("image_bank.npz")
        )
        self.handled_spawn_ids: dict[int, None] = {}
        self.handled_catch_ids: dict[int, None] = {}
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
        self.org_reserves: OrgReserves | None = None
        self.org_rpc: org_rpc.OrgRpc | None = None
        self.reserve_path = Path(os.environ.get("RESERVES_FILE", "reserves.json"))
        self.reservations = load_reservations(self.reserve_path)
        self.shinyhunt_path = Path(
            os.environ.get("SHINYHUNTS_FILE", "shinyhunts.json")
        )
        self.shinyhunters = load_reservations(self.shinyhunt_path)
        self.collection_path = Path(
            os.environ.get("COLLECTIONS_FILE", "collections.json")
        )
        self.collections = migrate_legacy_all_keys(
            load_reservations(self.collection_path)
        )
        self.server_settings_path = Path(
            os.environ.get("SERVER_SETTINGS_FILE", "server_settings.json")
        )
        self.server_settings = load_server_settings(self.server_settings_path)
        self.starboard_settings_path = Path(
            os.environ.get("STARBOARD_SETTINGS_FILE", "starboard_settings.json")
        )
        self.starboard_settings = load_starboard_settings(
            self.starboard_settings_path
        )
        self.afk_settings_path = Path(
            os.environ.get("AFK_SETTINGS_FILE", "afk_settings.json")
        )
        self.afk_settings = load_afk_settings(self.afk_settings_path)
        self.profile_data_path = Path(
            os.environ.get("PROFILE_DATA_FILE", "profile_data.json")
        )
        (
            self.profiles,
            self.profile_stats,
            self.profile_seen_catch_ids,
        ) = load_profile_data(
            self.profile_data_path
        )
        self.profile_emoji_cache: dict[str, bytes] | None = None
        self.appearance_path = Path(
            os.environ.get("APPEARANCE_FILE", "appearance.json")
        )
        self.appearance = load_appearance(self.appearance_path)
        self.low_accuracy_path = Path(
            os.environ.get("LOW_ACCURACY_FILE", "low_accuracy.json")
        )
        self.low_accuracy_channels = load_low_accuracy_channels(
            self.low_accuracy_path
        )
        self.chat_events: dict[int, ChatEventSession] = {}
        self.daycare = DaycareFeature(
            Path(os.environ.get("BOXES_FILE", "boxes.json")),
            config.poketwo_bot_id,
        )

    def profile_settings_for_user(self, user_id: int) -> dict[str, int | str]:
        return {
            **PROFILE_DEFAULTS,
            **self.profiles.get(str(user_id), {}),
        }

    def profile_stats_for_user(
        self,
        guild_id: int,
        user_id: int,
    ) -> dict[str, int]:
        return {
            **PROFILE_STAT_DEFAULTS,
            **self.profile_stats.get(f"{guild_id}:{user_id}", {}),
        }

    async def load_profile_emoji_assets(self) -> dict[str, bytes]:
        if self.profile_emoji_cache is not None:
            return self.profile_emoji_cache
        emoji_assets: dict[str, bytes] = {}
        if self.image_http is not None:
            for name, url in PROFILE_EMOJI_URLS.items():
                try:
                    async with self.image_http.get(url) as response:
                        if response.status != 200:
                            logger.warning(
                                "Could not load profile emoji %s (HTTP %s)",
                                name,
                                response.status,
                            )
                            continue
                        asset = await response.read()
                    with Image.open(BytesIO(asset)) as emoji:
                        emoji.verify()
                    emoji_assets[name] = asset
                except (aiohttp.ClientError, OSError) as error:
                    logger.warning(
                        "Could not load profile emoji %s: %s",
                        name,
                        error,
                    )
        self.profile_emoji_cache = emoji_assets
        return emoji_assets

    def set_profile_setting(self, user_id: int, setting: str, value: str) -> None:
        choices = PROFILE_SETTING_CHOICES.get(setting)
        if choices is None or value not in choices:
            raise ValueError(f"Invalid profile setting: {setting}")
        profiles = {key: dict(profile) for key, profile in self.profiles.items()}
        updated = profiles.setdefault(str(user_id), dict(PROFILE_DEFAULTS))
        updated[setting] = value
        save_profile_data(
            self.profile_data_path,
            profiles,
            self.profile_stats,
            self.profile_seen_catch_ids,
        )
        self.profiles = profiles

    def track_profile_catch(self, message: discord.Message) -> None:
        guild = getattr(message, "guild", None)
        message_id = getattr(message, "id", None)
        if (
            guild is None
            or getattr(guild, "id", None) != SERVER_ID
            or isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or message_id <= 0
            or message_id in self.profile_seen_catch_ids
        ):
            return
        details = parse_catch_details(message_text(message))
        if details is None:
            details = parse_catch_detection_details(message)
        if details is None or details.user_id is None:
            return

        profile_stats = {
            key: dict(stats) for key, stats in self.profile_stats.items()
        }
        user_stats = profile_stats.setdefault(
            f"{SERVER_ID}:{details.user_id}",
            dict(PROFILE_STAT_DEFAULTS),
        )
        user_stats["total"] += 1
        if details.shiny:
            user_stats["shiny"] += 1
        if details.iv_value is not None and details.iv_value < 10:
            user_stats["low_iv"] += 1
        if details.iv_value is not None and details.iv_value >= 90:
            user_stats["high_iv"] += 1
        if details.gigantamax:
            user_stats["gmax"] += 1
        if details.missingno:
            user_stats["missingno"] += 1
        seen_catch_ids = [*self.profile_seen_catch_ids, message_id][-10000:]
        try:
            save_profile_data(
                self.profile_data_path,
                self.profiles,
                profile_stats,
                seen_catch_ids,
            )
        except ValueError:
            logger.exception(
                "Could not record catch %s for profile user %s",
                message_id,
                details.user_id,
            )
            return
        self.profile_stats = profile_stats
        self.profile_seen_catch_ids = seen_catch_ids

    def update_appearance(self, guild_id: int, **changes) -> None:
        updated = {key: dict(value) for key, value in self.appearance.items()}
        guild = updated.setdefault(str(guild_id), {})
        for key, value in changes.items():
            if value is None:
                guild.pop(key, None)
            else:
                guild[key] = value
        save_appearance(self.appearance_path, updated)
        self.appearance = updated

    async def reset_appearance(
        self, interaction: discord.Interaction, guild_id: int, action: str
    ) -> None:
        field = action.removesuffix("_reset")
        try:
            if field == "avatar":
                await interaction.guild.me.edit(avatar=None)
            elif field == "banner":
                await interaction.guild.me.edit(banner=None)
            elif field == "name":
                await interaction.guild.me.edit(nick=None)
            self.update_appearance(guild_id, **{field: None})
        except (discord.HTTPException, ValueError) as error:
            await interaction.response.send_message(
                f"I couldn't reset that: {error}", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self, guild_id)
        )

    async def apply_appearance_image(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        field: str,
        attachment: discord.Attachment,
    ) -> None:
        content_type = (attachment.content_type or "").split(";")[0]
        if (
            content_type not in APPEARANCE_IMAGE_TYPES
            or attachment.size > APPEARANCE_MAX_BYTES
        ):
            await interaction.response.send_message(
                "That file must be a PNG, JPEG, GIF or WEBP image up to 10 MB.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            image = await attachment.read()
            member = await interaction.guild.me.edit(**{field: image})
        except (discord.HTTPException, ValueError) as error:
            if "too fast" in str(error):
                message = (
                    "Discord limits how often an avatar or banner can change. "
                    "Wait 10-15 minutes, then upload once more."
                )
            else:
                message = f"Discord rejected the image: {error}"
            await interaction.followup.send(message, ephemeral=True)
            return
        label = "profile image" if field == "avatar" else "server banner"
        applied = member is not None and (
            member.guild_avatar if field == "avatar" else member.guild_banner
        )
        logger.info(
            "Appearance %s edit in guild %s applied=%s", field, guild_id, bool(applied)
        )
        if not applied:
            await interaction.followup.send(
                f"Discord accepted the request but did not apply the {label}. "
                "Make sure the bot is on the latest code and try a different image.",
                ephemeral=True,
            )
            return
        self.update_appearance(guild_id, **{field: True})
        await interaction.followup.send(
            f"Updated the {label}. Reopen Appearance to see it.", ephemeral=True
        )

    def tint_embeds(self, guild: discord.Guild | None, kwargs: dict) -> None:
        if guild is None:
            return
        color = self.appearance.get(str(guild.id), {}).get("color")
        if color is None:
            return
        embeds = list(kwargs.get("embeds") or [])
        if kwargs.get("embed") is not None:
            embeds.append(kwargs["embed"])
        for embed in embeds:
            if embed.color is None or embed.color.value == DEFAULT_EMBED_COLOR:
                embed.color = discord.Color(color)

    def naming_settings_for_guild(self, guild_id: int) -> dict[str, bool]:
        return {
            **SERVER_NAMING_DEFAULTS,
            **self.server_settings.get(str(guild_id), {}),
        }

    def starboard_settings_for_guild(
        self, guild_id: int
    ) -> dict[str, int | str | None]:
        return {
            **STARBOARD_DEFAULTS,
            **self.starboard_settings.get(str(guild_id), {}),
        }

    def set_starboard_channel(
        self,
        guild_id: int,
        board: str,
        channel_id: int | None,
        channel_name: str | None = None,
    ) -> dict[str, int | str | None]:
        setting_key = STARBOARD_CHANNEL_SETTING_KEYS.get(board)
        if setting_key is None:
            raise ValueError(f"Unknown starboard: {board}")
        if channel_id is not None and (
            isinstance(channel_id, bool)
            or not isinstance(channel_id, int)
            or channel_id <= 0
        ):
            raise ValueError("A starboard channel ID must be a positive integer.")
        updated_settings = {
            key: dict(settings) for key, settings in self.starboard_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.starboard_settings_for_guild(guild_id)
        previous_channel_id = guild_settings[setting_key]
        guild_settings[setting_key] = channel_id
        if board == "shiny":
            if channel_id is None:
                guild_settings["shiny_base_name"] = None
                guild_settings["shiny_count"] = 0
            elif channel_id != previous_channel_id:
                base_name, initial_count = (
                    split_channel_counter(channel_name)
                    if channel_name
                    else (None, 0)
                )
                guild_settings["shiny_base_name"] = base_name
                guild_settings["shiny_count"] = initial_count
            elif (
                guild_settings["shiny_base_name"] is None
                and channel_name
            ):
                base_name, initial_count = split_channel_counter(channel_name)
                guild_settings["shiny_base_name"] = base_name
                guild_settings["shiny_count"] = max(
                    int(guild_settings["shiny_count"]),
                    initial_count,
                )
        updated_settings[guild_key] = guild_settings
        save_starboard_settings(self.starboard_settings_path, updated_settings)
        self.starboard_settings = updated_settings
        return guild_settings

    def increment_shinyboard_count(
        self,
        guild_id: int,
        channel_name: str | None,
    ) -> str | None:
        updated_settings = {
            key: dict(settings) for key, settings in self.starboard_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.starboard_settings_for_guild(guild_id)
        base_name = guild_settings["shiny_base_name"]
        count = int(guild_settings["shiny_count"])
        if base_name is None and channel_name:
            base_name, current_name_count = split_channel_counter(channel_name)
            count = max(count, current_name_count)
        count += 1
        guild_settings["shiny_base_name"] = base_name
        guild_settings["shiny_count"] = count
        updated_settings[guild_key] = guild_settings
        save_starboard_settings(self.starboard_settings_path, updated_settings)
        self.starboard_settings = updated_settings
        if base_name is None:
            return None
        suffix = f"-{count}"
        return f"{base_name[: 100 - len(suffix)]}{suffix}"

    def toggle_naming_setting(self, guild_id: int, setting: str) -> dict[str, bool]:
        if setting not in SERVER_NAMING_SETTING_KEYS:
            raise ValueError(f"Unknown server naming setting: {setting}")
        updated_settings = {
            guild_id: dict(settings)
            for guild_id, settings in self.server_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.naming_settings_for_guild(guild_id)
        guild_settings[setting] = not guild_settings[setting]
        updated_settings[guild_key] = guild_settings
        save_server_settings(self.server_settings_path, updated_settings)
        self.server_settings = updated_settings
        return guild_settings

    def afk_settings_for_user(
        self, guild_id: int, user_id: int
    ) -> dict[str, bool]:
        return {
            **AFK_DEFAULTS,
            **self.afk_settings.get(f"{guild_id}:{user_id}", {}),
        }

    def has_active_ping_targets(self, guild_id: int) -> bool:
        guild_prefix = f"{guild_id}:"
        if any(
            key.startswith(guild_prefix) and user_ids
            for key, user_ids in self.reservations.items()
        ):
            return True

        for registrations, setting in (
            (self.shinyhunters, "shinyhunt"),
            (self.collections, "collection"),
        ):
            if any(
                key.startswith(guild_prefix)
                and any(
                    self.afk_settings_for_user(guild_id, user_id)[setting]
                    for user_id in user_ids
                )
                for key, user_ids in registrations.items()
            ):
                return True
        return False

    def toggle_afk_setting(
        self, guild_id: int, user_id: int, setting: str
    ) -> dict[str, bool]:
        if setting not in AFK_SETTING_KEYS:
            raise ValueError(f"Unknown AFK setting: {setting}")
        updated_settings = {
            key: dict(settings) for key, settings in self.afk_settings.items()
        }
        user_key = f"{guild_id}:{user_id}"
        user_settings = self.afk_settings_for_user(guild_id, user_id)
        user_settings[setting] = not user_settings[setting]
        updated_settings[user_key] = user_settings
        save_afk_settings(self.afk_settings_path, updated_settings)
        self.afk_settings = updated_settings
        return user_settings

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

    def org_store(self, restrictions_path: Path | None = None) -> OrgReserves:
        """The one shared org store, built once and reused by every transport.

        org_api.create_app and the Discord transport both read and write this
        same in-memory list, so org_reserves.json never drifts into two caches.
        """
        if self.org_reserves is None:
            if restrictions_path is None:
                restrictions_path = Path(
                    os.environ.get(
                        "ORG_RESTRICTIONS_FILE",
                        str(Path(__file__).with_name("org_restrictions.json")),
                    )
                )
            self.org_reserves = OrgReserves(
                Path(os.environ.get("ORG_RESERVES_FILE", "org_reserves.json")),
                restrictions_path,
                load_known_pokemon_names(),
            )
        return self.org_reserves

    async def start_org_rpc(self) -> None:
        """Start the Discord org transport, or leave it off when unconfigured.

        from_environment returns None when neither ORG_DISCORD_RPC_CHANNEL_ID
        nor ORG_DISCORD_RPC_GUILD_ID is set, so the feature flag is the scope
        itself: on_message stays exactly as it was and nothing is listened for.
        """
        self.org_rpc = org_rpc.from_environment(
            self.org_store(),
            self.org_add_reserve,
            self.org_remove_reserve,
        )

    async def start_org_api(self) -> None:
        api_key = os.environ.get("ORG_BOT_API_KEY", "").strip()
        if not api_key:
            logger.info("Org API is disabled because ORG_BOT_API_KEY is not set")
            return
        try:
            guild_id = int(os.environ["ORG_GUILD_ID"])
        except (KeyError, ValueError):
            logger.error("ORG_GUILD_ID is required for the org API; API disabled")
            return
        restrictions_path = Path(
            os.environ.get(
                "ORG_RESTRICTIONS_FILE",
                str(Path(__file__).with_name("org_restrictions.json")),
            )
        )
        if not restrictions_path.is_file():
            logger.warning(
                "Org restrictions file not found at %s; slots will have no restrictions",
                restrictions_path.resolve(),
            )
        org = self.org_store(restrictions_path)
        allowed_lists = [
            rule["allowed"]
            for rule in org.restrictions.values()
            if "allowed" in rule
        ]
        allowed_count = len(allowed_lists[0]) if allowed_lists else 0
        logger.info(
            "Loaded org restrictions from %s (%d slots, %d allowed names)",
            restrictions_path.resolve(),
            len(org.restrictions),
            allowed_count,
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
        port = _org_api_port_from_environment()
        try:
            await web.TCPSite(self.org_runner, "0.0.0.0", port).start()
        except OSError:
            logger.exception("Could not bind Org API on 0.0.0.0:%s", port)
            raise
        logger.info("Org API listening on port %s", port)

    async def setup_hook(self) -> None:
        await self.start_org_api()
        await self.start_org_rpc()
        self.image_http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            connector=aiohttp.TCPConnector(limit=0),
            headers={"User-Agent": "Vivillon-naming/1.0"},
        )

    async def close(self) -> None:
        for task in self.time_tasks.values():
            task.cancel()
        self.time_tasks.clear()
        if self.org_runner is not None:
            await self.org_runner.cleanup()
        if self.image_http is not None:
            await self.image_http.close()
        if self.openai is not None:
            await self.openai.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def _ping_loop(self, channel, mentions: str, allowed) -> None:
        try:
            while True:
                await asyncio.sleep(180)
                try:
                    await channel.send(mentions, allowed_mentions=allowed)
                except discord.HTTPException as error:
                    logger.warning("v!settime ping failed: %s", error)
        except asyncio.CancelledError:
            pass

    async def handle_settime_command(self, message: discord.Message) -> None:
        roles = message.role_mentions
        users = [user for user in message.mentions if not user.bot]
        if not roles and not users:
            await message.reply(
                "Usage: `v!settime @role [@role ...]`", mention_author=False
            )
            return
        mentions = " ".join([role.mention for role in roles] + [u.mention for u in users])
        allowed = discord.AllowedMentions(roles=list(roles), users=users, everyone=False)
        channel_id = message.channel.id
        old = self.time_tasks.pop(channel_id, None)
        if old is not None:
            old.cancel()
        self.time_tasks[channel_id] = asyncio.create_task(
            self._ping_loop(message.channel, mentions, allowed)
        )
        await message.reply(
            f"✅ Timer set! I'll ping {mentions} every 3 minutes "
            "(first ping in 3 minutes). Use `v!timereset` to stop.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def handle_timereset_command(self, message: discord.Message) -> None:
        task = self.time_tasks.pop(message.channel.id, None)
        if task is None:
            await message.reply("No timer is running.", mention_author=False)
            return
        task.cancel()
        await message.reply(
            "Timer stopped. Use `v!settime` with roles to start again.",
            mention_author=False,
        )

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
        # The org transport runs first, before the bot-author guard below would
        # drop the org bot's own JSON requests, and before channel filtering.
        if self.org_rpc is not None and await self.org_rpc.handle_message(message):
            return
        poketwo_catch = message.author.id == self.config.poketwo_bot_id
        catch_detection_report = has_catch_detection_embed(message)
        parsed_catch_report = (
            is_automated_message(message)
            and not poketwo_catch
            and parse_catch_details(message_text(message)) is not None
        )
        if (
            message.author.bot
            and not poketwo_catch
            and not catch_detection_report
            and not parsed_catch_report
        ):
            return
        if poketwo_catch or catch_detection_report or parsed_catch_report:
            self.track_profile_catch(message)
            await self.handle_catch_starboard(message)
        self.track_incense_command(message)
        if not self.is_allowed_channel(message.channel):
            return
        channel_id = getattr(message.channel, "id", None)
        self.track_chat_event_message(message)

        text = message_text(message)
        if message.author.id != self.config.poketwo_bot_id:
            if PROFILE_COMMAND_PATTERN.fullmatch(message.content):
                await self.handle_profile_command(message)
                return
            if re.fullmatch(r"v!event\s*", message.content, re.IGNORECASE):
                await self.handle_event_command(message)
                return
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
                        "Attach an image to `v!test` or `v!test shiny` "
                        "to test spawn recognition.",
                        mention_author=False,
                    )
                    return
                shiny_test_mode = (
                    re.fullmatch(
                        r"v!test\s+shiny\s*",
                        message.content,
                        re.IGNORECASE,
                    )
                    is not None
                )
                await self.handle_spawn(
                    message,
                    test_mode=True,
                    shiny_test_mode=shiny_test_mode,
                )
                return
            if re.fullmatch(HELP_COMMAND_PATTERN, message.content, re.IGNORECASE):
                await message.reply(embed=build_help_menu_embed(), mention_author=False)
                return
            if await self.daycare.handle_message(message):
                return
            if re.match(r"^v!settime(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_settime_command(message)
                return
            if re.fullmatch(r"v!timereset\s*", message.content, re.IGNORECASE):
                await self.handle_timereset_command(message)
                return
            if re.fullmatch(r"v!grab\s*", message.content, re.IGNORECASE):
                await self.handle_grab_command(message)
                return
            if re.fullmatch(r"v!ping\s*", message.content, re.IGNORECASE):
                await self.handle_ping_command(message)
                return
            if re.fullmatch(r"v!settings\s*", message.content, re.IGNORECASE):
                await self.handle_settings_command(message)
                return
            if re.match(r"^v!lowaccuracy(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_low_accuracy_command(message)
                return
            if re.fullmatch(r"v!afk\s*", message.content, re.IGNORECASE):
                await self.handle_afk_command(message)
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
        if guild is None:
            return
        if message.author.id == self.config.poketwo_bot_id:
            status = re.search(
                r"\bIncense\s*:\s*(Active|Inactive)\b",
                message_text(message),
                re.IGNORECASE,
            )
            if status is None:
                return
            action = (
                "start" if status.group(1).casefold() == "active" else "stop"
            )
        else:
            action = poketwo_incense_action(
                message.content, self.config.poketwo_bot_id
            )
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

    async def handle_profile_command(self, message: discord.Message) -> None:
        match = PROFILE_COMMAND_PATTERN.fullmatch(message.content)
        if match is None:
            return
        if message.guild is None or message.guild.id != SERVER_ID:
            await message.reply(
                "Profiles are only available in the configured profile server.",
                mention_author=False,
            )
            return
        user_id = int(match.group(1)) if match.group(1) else message.author.id
        settings = self.profile_settings_for_user(user_id)
        stats = self.profile_stats_for_user(message.guild.id, user_id)
        emoji_assets = await self.load_profile_emoji_assets()
        view = ProfileView(self, user_id, message.guild.id)
        response = await message.reply(
            file=discord.File(
                render_profile_image(settings, stats, emoji_assets),
                filename="profile.png",
            ),
            view=view,
            mention_author=False,
        )
        view.message = response

    async def handle_event_command(self, message: discord.Message) -> None:
        embed = discord.Embed(
            title="Choose an event",
            description="Choose an event to start. More events may be added later.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Chat event",
            value=(
                "At least two participants react to join, then compete to send "
                "the most sentences with at least four words."
            ),
            inline=False,
        )
        await message.reply(
            embed=embed,
            view=EventMenuView(self, message.author.id),
            mention_author=False,
        )

    async def start_chat_event(
        self, interaction: discord.Interaction, host_id: int
    ) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message(
                "This event needs to be started in a server channel.",
                ephemeral=True,
            )
            return
        channel_id = channel.id
        if channel_id in self.chat_events:
            await interaction.response.send_message(
                "A chat event is already running in this channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        session = ChatEventSession(host_id=host_id, channel=channel)
        self.chat_events[channel_id] = session
        embed = discord.Embed(
            title="Chat event — sign up now!",
            description=(
                f"React with {CHAT_EVENT_EMOJI} to join. Sign-ups close in "
                f"{CHAT_EVENT_SIGNUP_SECONDS} seconds; at least "
                f"{CHAT_EVENT_MIN_PARTICIPANTS} people must join. After sign-up "
                "closes, send as many sentences with at least four words as you can."
            ),
            color=discord.Color.green(),
        )
        try:
            session.message = await channel.send(embed=embed)
            await session.message.add_reaction(CHAT_EVENT_EMOJI)
        except discord.HTTPException as error:
            self.chat_events.pop(channel_id, None)
            logger.warning("Could not start chat event: %s", error)
            await interaction.followup.send(
                "I couldn't start the chat event. Check that I can send messages "
                "and add reactions in this channel.",
                ephemeral=True,
            )
            return

        asyncio.create_task(self.run_chat_event(session))
        await interaction.followup.send(
            "Choose any positive duration in minutes or hours, such as "
            "`7 minutes` or `2 hours`. A number by itself means minutes. "
            "The timer starts after the one-minute sign-up period.",
            view=ChatEventDurationView(session),
            ephemeral=True,
        )
        try:
            if interaction.message is not None:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="Chat event selected",
                        description="The sign-up message is now open below.",
                        color=discord.Color.green(),
                    ),
                    view=None,
                )
        except discord.HTTPException as error:
            logger.warning("Could not update the event menu: %s", error)

    def track_chat_event_message(self, message: discord.Message) -> None:
        if message.author.bot or message.content.casefold().startswith("v!"):
            return
        session = self.chat_events.get(message.channel.id)
        if (
            session is None
            or not session.collecting
            or message.author.id not in session.participant_ids
        ):
            return
        session.sentence_counts[message.author.id] += count_qualifying_sentences(
            message.content
        )

    async def run_chat_event(self, session: ChatEventSession) -> None:
        channel_id = session.channel.id
        try:
            await asyncio.sleep(CHAT_EVENT_SIGNUP_SECONDS)
            if session.message is None:
                return
            reaction = next(
                (
                    item
                    for item in session.message.reactions
                    if str(item.emoji) == CHAT_EVENT_EMOJI
                ),
                None,
            )
            if reaction is not None:
                try:
                    async for user in reaction.users(limit=None):
                        if not user.bot:
                            session.participant_ids.add(user.id)
                except discord.HTTPException as error:
                    logger.warning("Could not read chat event sign-ups: %s", error)
                    await session.channel.send(
                        "I couldn't read the sign-ups, so the chat event was canceled."
                    )
                    return
            try:
                await session.message.clear_reactions()
            except discord.HTTPException as error:
                logger.warning("Could not clear chat event reactions: %s", error)

            if len(session.participant_ids) < CHAT_EVENT_MIN_PARTICIPANTS:
                await session.channel.send(
                    "The chat event needs at least "
                    f"{CHAT_EVENT_MIN_PARTICIPANTS} participants; only "
                    f"{len(session.participant_ids)} signed up."
                )
                return
            session.sentence_counts = {
                user_id: 0 for user_id in session.participant_ids
            }
            await session.duration_selected.wait()
            if session.cancelled or session.duration_seconds is None:
                await session.channel.send(
                    "The chat event was canceled because no duration was chosen."
                )
                return

            session.collecting = True
            await session.channel.send(
                f"Chat event started! You have {session.duration_label}. "
                "Only sentences with at least four words count."
            )
            await asyncio.sleep(session.duration_seconds)
            session.collecting = False
            ordered_participants = sorted(
                session.participant_ids,
                key=lambda user_id: (
                    -session.sentence_counts[user_id],
                    user_id,
                ),
            )
            pages = [
                ordered_participants[index : index + 40]
                for index in range(0, len(ordered_participants), 40)
            ]
            for page_number, participant_page in enumerate(pages, start=1):
                description = "\n".join(
                    f"<@{user_id}> — {session.sentence_counts[user_id]} "
                    f"sentence(s)"
                    for user_id in participant_page
                )
                result = discord.Embed(
                    title="Chat event results"
                    if len(pages) == 1
                    else f"Chat event results ({page_number}/{len(pages)})",
                    description=description,
                    color=discord.Color.gold(),
                )
                await session.channel.send(
                    embed=result,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except discord.HTTPException:
            logger.exception("Could not complete chat event in channel %s", channel_id)
        finally:
            if self.chat_events.get(channel_id) is session:
                del self.chat_events[channel_id]

    async def handle_settings_command(self, message: discord.Message) -> None:
        await message.reply(
            view=ServerSettingsView(self, message.guild.id),
            mention_author=False,
        )

    async def report_low_accuracy(
        self, message: discord.Message, name: str, confidence: float
    ) -> None:
        guild = message.guild
        channel_id = self.low_accuracy_channels.get(str(guild.id)) if guild else None
        if channel_id is None:
            return
        channel = self.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(
                f"⚠️ Low accuracy: **{display_pokemon_name(name)}** at "
                f"{confidence:.2f}% (below {LOW_ACCURACY_THRESHOLD}%)\n"
                f"{message.jump_url}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.warning("Could not send low accuracy report", exc_info=True)

    async def handle_low_accuracy_command(self, message: discord.Message) -> None:
        permissions = getattr(message.author, "guild_permissions", None)
        if message.guild is None or permissions is None or not permissions.manage_guild:
            await message.reply(
                "You need the Manage Server permission to use this.",
                mention_author=False,
            )
            return
        argument = message.content.split(maxsplit=1)[1].strip() if " " in message.content.strip() else ""
        key = str(message.guild.id)
        if argument.lower() in ("off", "reset", "clear"):
            self.low_accuracy_channels.pop(key, None)
            save_low_accuracy_channels(self.low_accuracy_path, self.low_accuracy_channels)
            await message.reply("Low accuracy recorder turned off.", mention_author=False)
            return
        if message.channel_mentions:
            target = message.channel_mentions[0]
            self.low_accuracy_channels[key] = target.id
            save_low_accuracy_channels(self.low_accuracy_path, self.low_accuracy_channels)
            await message.reply(
                f"Low accuracy recorder on. Spawns scoring under {LOW_ACCURACY_THRESHOLD}% "
                f"will be linked in {target.mention}.",
                mention_author=False,
            )
            return
        current = self.low_accuracy_channels.get(key)
        state = f"<#{current}>" if current else "off"
        await message.reply(
            f"Low accuracy recorder: {state}\n"
            "Use `v!lowaccuracy #channel` to set it or `v!lowaccuracy off` to disable.",
            mention_author=False,
        )

    async def handle_afk_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "AFK settings can only be used in a server.",
                mention_author=False,
            )
            return
        await message.reply(
            view=AFKSettingsView(self, message.guild.id, message.author.id),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
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

    async def on_raw_message_edit(
        self, payload: discord.RawMessageUpdateEvent
    ) -> None:
        await self.daycare.handle_raw_edit(payload)

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        # Pokétwo sometimes adds the spawn image or text by editing the message.
        poketwo_catch = after.author.id == self.config.poketwo_bot_id
        catch_detection_report = has_catch_detection_embed(after)
        parsed_catch_report = (
            is_automated_message(after)
            and not poketwo_catch
            and parse_catch_details(message_text(after)) is not None
        )
        if not poketwo_catch and not catch_detection_report and not parsed_catch_report:
            return
        self.track_profile_catch(after)
        await self.handle_catch_starboard(after)
        self.track_incense_command(after)
        if not self.is_allowed_channel(after.channel):
            return
        text = message_text(after)
        if SPAWN_PATTERN.search(text):
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

    async def confirm_pokemon_name(
        self, message: discord.Message, name: str
    ) -> str | None:
        """Return the name to use, asking the user when it looks misspelled.

        Returns None for unknown names or when the user declines or times out.
        """
        if is_known_pokemon_name(name):
            return name
        suggestion = suggest_pokemon_name(name)
        if suggestion is None:
            await message.reply(
                f"**{name}** is not a valid Pokémon name.",
                mention_author=False,
            )
            return None
        view = NameSuggestionView(message.author.id)
        prompt = await message.reply(
            f"Do you mean **{suggestion}**?",
            view=view,
            mention_author=False,
        )
        await view.wait()
        confirmed = view.confirmed is True
        if view.confirmed is None:
            try:
                await prompt.edit(content="Timed out, nothing was added.", view=None)
            except discord.HTTPException:
                pass
        return suggestion if confirmed else None

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

        if re.fullmatch(r"v!sh\s+clear\s+all\s*", message.content, re.IGNORECASE):
            if not message.author.guild_permissions.administrator:
                await message.reply(
                    "Only server administrators can clear everyone's shinyhunts.",
                    mention_author=False,
                )
                return
            await message.reply(
                "Are you sure you want to clear everyone's shinyhunts in this server?",
                view=ClearShinyhuntsView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!sh\s+clear\s*", message.content, re.IGNORECASE):
            updated_shinyhunters, cleared = clear_shinyhunter(
                self.shinyhunters,
                message.guild.id,
                message.author.id,
            )
            if cleared:
                try:
                    save_reservations(self.shinyhunt_path, updated_shinyhunters)
                except ValueError:
                    logger.exception("Could not save shiny-hunt clearing")
                    await message.reply(
                        "I couldn't clear that shiny hunt. Check the bot logs.",
                        mention_author=False,
                    )
                    return
                self.shinyhunters = updated_shinyhunters
            await message.reply(
                "Your shinyhunt has been cleared.",
                mention_author=False,
            )
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
                "Usage: `v!sh <pokemon>`, `v!sh remove <pokemon>`, or "
                "`v!sh clear` or `v!sh clear all` (one Pokémon per command)",
                mention_author=False,
            )
            return

        pokemon_name = await self.confirm_pokemon_name(message, pokemon_name)
        if pokemon_name is None:
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

        if re.fullmatch(r"v!cl\s+clear\s+all\s*", message.content, re.IGNORECASE):
            if not message.author.guild_permissions.administrator:
                await message.reply(
                    "Only server administrators can clear everyone's collection.",
                    mention_author=False,
                )
                return
            await message.reply(
                "Are you sure you want to clear everyone's collection in this server?",
                view=ClearCollectionView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
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
            await message.reply(
                "Usage: `v!cl clear` or `v!cl clear all`",
                mention_author=False,
            )
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

        confirmed_names: list[str] = []
        for requested_name in pokemon_names:
            confirmed_name = await self.confirm_pokemon_name(message, requested_name)
            if confirmed_name is not None and confirmed_name.casefold() not in {
                name.casefold() for name in confirmed_names
            }:
                confirmed_names.append(confirmed_name)
        pokemon_names = confirmed_names
        if not pokemon_names:
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

    async def handle_catch_starboard(self, message: discord.Message) -> None:
        if message.guild is None or message.id in self.handled_catch_ids:
            return
        details = parse_catch_details(message_text(message))
        if details is None:
            details = parse_catch_detection_details(message)
        if details is None:
            return
        category = starboard_category(details)
        normal_pokemon_catch = is_normal_starboard_pokemon(details.pokemon)
        if category is None and not normal_pokemon_catch:
            return

        settings = self.starboard_settings_for_guild(message.guild.id)
        posts = catch_starboard_destinations(details, settings)
        if not posts:
            logger.info(
                "No starboard destination configured for catch message %s in guild %s "
                "(category=%s, normal_starboard_match=%s)",
                message.id,
                message.guild.id,
                category,
                normal_pokemon_catch,
            )
            return

        self.handled_catch_ids[message.id] = None
        while len(self.handled_catch_ids) > 5000:
            del self.handled_catch_ids[next(iter(self.handled_catch_ids))]

        for channel_id, post_category in posts.items():
            channel = self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load starboard channel %s in guild %s",
                        channel_id,
                        message.guild.id,
                    )
                    continue
            jump_url = (
                f"https://discord.com/channels/{message.guild.id}/"
                f"{message.channel.id}/{message.id}"
            )
            embed = format_starboard_embed(
                details,
                post_category,
                message.created_at,
                use_3d_shiny_model=(
                    details.shiny and channel_id == settings["shiny_channel"]
                ),
            )
            self.tint_embeds(message.guild, {"embed": embed})
            try:
                await channel.send(
                    embed=embed,
                    view=starboard_jump_view(jump_url),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                logger.info(
                    "Posted catch message %s to starboard channel %s as %s",
                    message.id,
                    channel_id,
                    post_category,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not post catch message %s to starboard channel %s",
                    message.id,
                    channel_id,
                )

        shiny_channel_id = settings["shiny_channel"]
        if details.shiny and shiny_channel_id is not None:
            shiny_channel = self.get_channel(shiny_channel_id)
            if shiny_channel is None:
                try:
                    shiny_channel = await self.fetch_channel(shiny_channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load shinyboard channel %s in guild %s",
                        shiny_channel_id,
                        message.guild.id,
                    )
            channel_name = getattr(shiny_channel, "name", None)
            if not isinstance(channel_name, str):
                channel_name = None
            try:
                updated_name = self.increment_shinyboard_count(
                    message.guild.id,
                    channel_name,
                )
            except ValueError:
                logger.exception(
                    "Could not save shinyboard catch count for guild %s",
                    message.guild.id,
                )
                return
            if (
                shiny_channel is not None
                and updated_name is not None
                and updated_name != channel_name
            ):
                try:
                    await shiny_channel.edit(
                        name=updated_name,
                        reason="Update shiny catch count",
                    )
                except discord.HTTPException:
                    logger.warning(
                        "Could not rename shinyboard channel %s to %s",
                        shiny_channel_id,
                        updated_name,
                        exc_info=True,
                    )

    async def post_test_starboard(
        self,
        message: discord.Message,
        pokemon_name: str,
        *,
        category: str,
    ) -> None:
        if message.guild is None:
            return
        is_shiny = category == "shiny"
        settings = self.starboard_settings_for_guild(message.guild.id)
        details = CatchDetails(
            user_id=message.author.id,
            pokemon=display_pokemon_name(pokemon_name),
            level="Unknown",
            iv="Unknown",
            iv_value=None,
            gender=None,
            shiny=is_shiny,
            chain=None,
            gigantamax=False,
            missingno=False,
        )
        posts = catch_starboard_destinations(details, settings)
        if not posts:
            board_name = "Shinyboard or Vivillon Starboard" if is_shiny else "Normal Starboard"
            logger.warning(
                "Cannot post v!test preview for message %s: no %s destination "
                "is configured "
                "in guild %s",
                message.id,
                board_name,
                message.guild.id,
            )
            await message.reply(
                f"No {board_name} destination is configured. "
                "Choose a channel in `v!settings`.",
                mention_author=False,
            )
            return

        failed_channels: list[int] = []
        for channel_id, post_category in posts.items():
            channel = self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load starboard channel %s in guild %s for v!test",
                        channel_id,
                        message.guild.id,
                    )
                    failed_channels.append(channel_id)
                    continue
            jump_url = (
                f"https://discord.com/channels/{message.guild.id}/"
                f"{message.channel.id}/{message.id}"
            )
            embed = format_starboard_embed(
                details,
                post_category,
                message.created_at,
                use_3d_shiny_model=(
                    is_shiny and channel_id == settings["shiny_channel"]
                ),
                test_preview=True,
            )
            self.tint_embeds(message.guild, {"embed": embed})
            try:
                await channel.send(
                    embed=embed,
                    view=starboard_jump_view(jump_url),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                logger.info(
                    "Posted v!test preview for %s to starboard channel %s as %s",
                    pokemon_name,
                    channel_id,
                    post_category,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not post v!test preview for %s to starboard channel %s",
                    pokemon_name,
                    channel_id,
                )
                failed_channels.append(channel_id)
        if failed_channels:
            await message.reply(
                "I couldn't post the test preview to every configured starboard "
                f"channel ({', '.join(map(str, failed_channels))}). "
                "Check the bot logs and channel permissions.",
                mention_author=False,
            )

    async def handle_spawn(
        self,
        message: discord.Message,
        *,
        test_mode: bool = False,
        shiny_test_mode: bool = False,
    ) -> None:
        if not test_mode and message.guild:
            naming_settings = self.naming_settings_for_guild(message.guild.id)
            if not naming_settings["enabled"]:
                return
            try:
                self.shinyhunters = load_reservations(self.shinyhunt_path)
                self.collections = migrate_legacy_all_keys(
                    load_reservations(self.collection_path)
                )
            except ValueError:
                logger.exception("Could not refresh spawn ping registrations")
                await message.reply(
                    "I couldn't load the current ping registrations. "
                    "Check the bot logs.",
                    mention_author=False,
                )
                return
            if naming_settings["pings"] and not self.has_active_ping_targets(
                message.guild.id
            ):
                return

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
        if confidence < LOW_ACCURACY_THRESHOLD:
            await self.report_low_accuracy(message, name, confidence)
        thumbnail_name = name
        name = species_display_name(name)
        guess_name = shown_form_name(name, thumbnail_name)
        if is_missingno_name(name) and not test_mode:
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
        if message.guild:
            shinyhunter_user_ids = [
                user_id
                for user_id in shinyhunter_user_ids
                if self.afk_settings_for_user(message.guild.id, user_id)[
                    "shinyhunt"
                ]
            ]
            collection_user_ids = [
                user_id
                for user_id in collection_user_ids
                if self.afk_settings_for_user(message.guild.id, user_id)[
                    "collection"
                ]
            ]
        naming_settings = (
            self.naming_settings_for_guild(message.guild.id)
            if message.guild
            else SERVER_NAMING_DEFAULTS
        )
        if test_mode:
            # Show the full spawn message, without pinging anyone.
            reserved_user_ids, shinyhunter_user_ids, collection_user_ids = [], [], []
            assisted = True
        else:
            if not naming_settings["enabled"]:
                return
            if naming_settings["pings"] and not (
                reserved_user_ids or shinyhunter_user_ids or collection_user_ids
            ):
                return
            assisted = naming_settings["assisted"]

        if test_mode:
            if shiny_test_mode:
                await self.post_test_starboard(message, name, category="shiny")
            elif is_normal_starboard_pokemon(name):
                await self.post_test_starboard(
                    message,
                    name,
                    category="normal_pokemon",
                )

        type_emojis = type_emoji_text(thumbnail_name, name)
        if type_emojis:
            card_files = catch_card_files(name, thumbnail_name) if assisted else []
            await message.reply(
                format_typed_spawn_reply(
                    name,
                    confidence,
                    POKETWO_COMMAND_BOT_ID,
                    type_emojis,
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                    assisted=assisted,
                    guess_name=guess_name,
                ),
                embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                **({"files": card_files} if card_files else {}),
                mention_author=False,
            )
            return

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
                assisted=assisted,
                guess_name=guess_name,
            )
            companion_icon_filename = (
                fire_companion_icon_filename_for_pokemon(name)
                or water_companion_icon_filename_for_pokemon(name)
                or normal_companion_icon_filename_for_pokemon(name)
                or electric_companion_icon_filename_for_pokemon(name)
            )
            if assisted and companion_icon_filename:
                await message.reply(
                    reply,
                    embed=format_pc_catch_embed(name, thumbnail_name),
                    file=discord.File(
                        Path(__file__).with_name("assets") / companion_icon_filename,
                        filename=companion_icon_filename,
                    ),
                    mention_author=False,
                )
            else:
                card_files = catch_card_files(name, thumbnail_name) if assisted else []
                await message.reply(
                    reply,
                    embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                    **({"files": card_files} if card_files else {}),
                    mention_author=False,
                )
            return

        icon_filename = type_icon_filename_for_pokemon(name)
        if icon_filename:
            type_embed = format_type_spawn_embed(
                name,
                confidence,
                POKETWO_COMMAND_BOT_ID,
                icon_filename,
                assisted=assisted,
                guess_name=guess_name,
            )
            content_lines = format_spawn_mention_lines(
                reserved_user_ids,
                shinyhunter_user_ids,
                collection_user_ids,
            )
            embeds = [type_embed]
            files = [
                discord.File(
                    Path(__file__).with_name("assets") / icon_filename,
                    filename=icon_filename,
                )
            ]
            if assisted:
                embeds.append(format_pc_catch_embed(name, thumbnail_name))
                files.extend(catch_card_files(name, thumbnail_name))
            await message.reply(
                content="\n".join(content_lines),
                embeds=embeds,
                files=files,
                mention_author=False,
            )
        else:
            card_files = catch_card_files(name, thumbnail_name) if assisted else []
            await message.reply(
                format_spawn_reply(
                    name,
                    confidence,
                    POKETWO_COMMAND_BOT_ID,
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                    assisted=assisted,
                    guess_name=guess_name,
                ),
                embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                **({"files": card_files} if card_files else {}),
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


class NameSuggestionView(discord.ui.View):
    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=NAME_SUGGESTION_TIMEOUT_SECONDS)
        self.requester_id = requester_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran the command can answer this.",
                ephemeral=True,
            )
            return False
        return True

    async def _finish(
        self, interaction: discord.Interaction, confirmed: bool, text: str
    ) -> None:
        self.confirmed = confirmed
        await interaction.response.edit_message(content=text, view=None)
        self.stop()

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await self._finish(interaction, True, "Confirmed.")

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await self._finish(interaction, False, "Cancelled, nothing was added.")


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


class ClearCollectionView(discord.ui.View):
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
            or not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "Only the administrator who ran this command can confirm it.",
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
        updated_collections = clear_guild_collection(
            self.bot.collections,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.collection_path, updated_collections)
        except ValueError:
            logger.exception("Could not clear server Pokémon collections")
            await interaction.response.send_message(
                "I couldn't clear the collections. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.collections = updated_collections
        await interaction.response.edit_message(
            content="Everyone's Pokémon collection in this server has been cleared.",
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


class ClearShinyhuntsView(discord.ui.View):
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
            or not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "Only the administrator who ran this command can confirm it.",
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
        updated_shinyhunters = clear_guild_shinyhunts(
            self.bot.shinyhunters,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.shinyhunt_path, updated_shinyhunters)
        except ValueError:
            logger.exception("Could not clear server shinyhunts")
            await interaction.response.send_message(
                "I couldn't clear the shinyhunts. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.shinyhunters = updated_shinyhunters
        await interaction.response.edit_message(
            content="Everyone's shinyhunts in this server have been cleared.",
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


def install_embed_tinting(bot: NamingBot) -> None:
    original_send = discord.abc.Messageable.send
    original_reply = discord.Message.reply

    async def send(self, *args, **kwargs):
        bot.tint_embeds(getattr(self, "guild", None), kwargs)
        return await original_send(self, *args, **kwargs)

    async def reply(self, *args, **kwargs):
        bot.tint_embeds(self.guild, kwargs)
        return await original_reply(self, *args, **kwargs)

    discord.abc.Messageable.send = send
    discord.Message.reply = reply


def main() -> None:
    config = Config.from_environment()
    bot = NamingBot(config)
    install_embed_tinting(bot)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
