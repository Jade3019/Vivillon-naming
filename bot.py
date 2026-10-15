import asyncio
import base64
import json
import logging
import os
import re
import unicodedata
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
                    "Choose the single most likely Pokémon name. Never "
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
    name = unicodedata.normalize("NFC", name.strip())
    if len(name) > 60 or (name and not is_valid_pokemon_name(name)):
        raise ValueError("Vision model returned an invalid Pokémon name")
    return name, confidence


def is_valid_pokemon_name(name: str) -> bool:
    allowed_punctuation = " .'-:♀♂"
    return bool(name) and any(char.isalpha() for char in name) and all(
        unicodedata.category(char)[0] in {"L", "M", "N"}
        or char in allowed_punctuation
        for char in name
    )


def format_guess(name: str, confidence: int) -> str:
    return f"{name}: {confidence}%"


def format_catch_command(poketwo_bot_id: int, name: str) -> str:
    return f"<@{poketwo_bot_id}> c {name.lower()}"


def format_spawn_reply(name: str, confidence: int, poketwo_bot_id: int) -> str:
    return (
        f"{format_guess(name, confidence)}\n"
        f"`{format_catch_command(poketwo_bot_id, name)}`"
    )


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
        await message.reply(
            format_spawn_reply(name, confidence, self.config.poketwo_bot_id),
            mention_author=False,
        )


def main() -> None:
    config = Config.from_environment()
    bot = NamingBot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
