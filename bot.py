import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass
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
CAUGHT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:caught|catch|congratulations)\b", re.IGNORECASE
)
LEVEL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:level|lvl)\s*[:#]?\s*(\d{1,3})\b", re.IGNORECASE
)
GENDER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bgender\s*[:=]\s*(male|female|genderless|unknown|♂|♀)\b",
    re.IGNORECASE,
)
IV_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bIV(?:s| percentage)?\s*[:=]\s*(\d{1,3}(?:\.\d+)?)\s*%?(?!\s*/)(?!\w)",
    re.IGNORECASE,
)
STAT_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    stat: re.compile(
        rf"\b{re.escape(stat)}\s*[:=]\s*(\d{{1,2}})\b",
        re.IGNORECASE,
    )
    for stat in ("HP", "Attack", "Defense", "Sp. Atk", "Sp. Def", "Speed")
}


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
) -> tuple[str, int]:
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
                    "through #1026. Choose the single most likely Pokémon name. Never "
                    "return multiple candidates, alternate names, aliases, or a list. "
                    "Estimate your confidence in that one guess as a whole-number "
                    "percentage from 0 to 100. Return JSON only, in the form "
                    '{"name":"one Pokétwo-accepted English name","confidence":85}. '
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
        or not isinstance(confidence, int)
        or not 0 <= confidence <= 100
    ):
        raise ValueError("Vision model response included an invalid confidence percentage")
    name = name.strip()
    if len(name) > 60 or (name and not re.fullmatch(r"[A-Za-z0-9 .'-]+", name)):
        raise ValueError("Vision model returned an invalid Pokémon name")
    return name, confidence


def format_guess(name: str, confidence: int) -> str:
    return f"{name}: {confidence}%"


def extract_stats(text: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    level = LEVEL_PATTERN.search(text)
    if level:
        stats["Level"] = level.group(1)

    gender = GENDER_PATTERN.search(text)
    if gender:
        stats["Gender"] = {"♂": "Male", "♀": "Female"}.get(
            gender.group(1), gender.group(1).capitalize()
        )
    else:
        gender_symbol = re.search(r"(?<!\w)(♂|♀)(?!\w)", text)
        if gender_symbol:
            stats["Gender"] = "Male" if gender_symbol.group(1) == "♂" else "Female"

    iv = IV_PATTERN.search(text)
    if iv:
        stats["IV"] = f"{iv.group(1)}%"
    else:
        individual_ivs = [
            int(match.group(1))
            for pattern in STAT_PATTERNS.values()
            if (match := pattern.search(text))
        ]
        if len(individual_ivs) == len(STAT_PATTERNS):
            stats["IV"] = f"{sum(individual_ivs) / (31 * len(STAT_PATTERNS)) * 100:.1f}%"
    return stats


class NamingBot(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.openai = AsyncOpenAI(api_key=config.openai_api_key)
        self.image_http: aiohttp.ClientSession | None = None

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
        if message.author.id != self.config.poketwo_bot_id:
            return
        if (
            self.config.allowed_channel_id is not None
            and message.channel.id != self.config.allowed_channel_id
        ):
            return

        text = message_text(message)
        if SPAWN_PATTERN.search(text):
            await self.handle_spawn(message)
            return

        stats = extract_stats(text)
        if stats and (CAUGHT_PATTERN.search(text) or len(stats) >= 2):
            summary = "Pokétwo details: " + " · ".join(
                f"{label}: {value}" for label, value in stats.items()
            )
            await message.reply(summary, mention_author=False)

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
        await message.reply(format_guess(name, confidence), mention_author=False)


def main() -> None:
    config = Config.from_environment()
    bot = NamingBot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
