import asyncio
import base64
import json
import logging
import math
import os
import re
import time
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
    r"^v!r\s+search\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+remove\s+(.+?)(?:(?:\s*,\s*|\s+)<@!?(\d+)>)?\s*$",
    re.IGNORECASE,
)
RESERVATION_EMBED_PAGE_SIZE: Final[int] = 20

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
                    "For example, Eldegoss has a large round white cotton puff with "
                    "small brown seeds around a yellow-green leafy face; Shaymin's "
                    "Land Forme is a small white quadruped with green hedgehog-like "
                    "back fur and a pink flower by its ear, not a cotton puff. "
                    "Lumineon is a fish with a dark blue body, pink eyes, and very "
                    "large wing-like fins with pale blue edges and dark scalloped "
                    "markings; do not mistake its fins for wings or use the underwater "
                    "background alone to identify it. "
                    "Pidove is a small, round-bodied gray pigeon Pokémon with a pale "
                    "cream-white chest and face, a large yellow-orange eye, a short dark "
                    "beak with a pink cere, and dark gray patches on its wings and tail. "
                    "Distinguish it from other small gray birds by its plump pigeon "
                    "silhouette, contrasting dark wing patches, and pink feet; do not "
                    "mistake the raised wing for its body shape. "
                    "Doduo is a flightless bird Pokémon with two long, thin necks, "
                    "each ending in a small tan, shaggy head with a long narrow beak "
                    "and one visible eye. Its round fuzzy tan body is supported by long "
                    "slender legs with three-toed feet, and it has no visible wings. "
                    "Count the two heads and distinguish Doduo from Dodrio, which has "
                    "three heads and a larger body. "
                    "Wattrel is a small seabird Pokémon with a charcoal-black head and "
                    "back, a slate-gray chest, a bold yellow patch across the folded "
                    "wing, a long pointed dark tail, and a narrow orange beak and legs. "
                    "Distinguish the compact Wattrel from the larger, longer-winged "
                    "Kilowattrel; do not mistake its yellow wing patch for a fully yellow "
                    "body or rely on a water background to identify it. "
                    "Houndour is a small dark canine with an orange muzzle and pale "
                    "bone-like bands around its legs and back; distinguish its dog-like "
                    "body from other dark quadruped Pokémon. "
                    "Herdier is a sturdy, medium-sized dog Pokémon with a dark navy "
                    "blue-gray shaggy coat over its back, a tan face and legs, long "
                    "upright ears, and distinctive cream-colored bushy facial fur that "
                    "forms a large mustache and eyebrows. Distinguish it from the smaller "
                    "Lillipup and the larger, heavily mustached Stoutland by its "
                    "intermediate size and single dark back coat. "
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
                    "Dreepy is a small floating Pokémon with a long, pale mint-green "
                    "body, a large dark slate-gray angular head, prominent yellow eyes, "
                    "and bright pink-red fin-like projections behind its head; distinguish "
                    "its small single-headed silhouette from the larger Drakloak and "
                    "Dragapult, and do not mistake it for a fish based on its streamlined "
                    "shape. "
                    "Nymble is a tiny, low-slung, dark gray grasshopper-like Pokémon "
                    "with a rounded body, a yellow face marking with a black X-shaped "
                    "center, pale gray lower-body patches, and long folded hind legs; "
                    "its tall, upright dark hind-leg parts have distinctive pale ring "
                    "markings. Distinguish this compact insect from Scyther and other "
                    "larger insect Pokémon, and do not mistake its folded legs for extra "
                    "wings or a second head. "
                    "Pansage is a small green monkey-like Pokémon with very large round "
                    "ears, a pale cream face and hands, a leafy green tuft on top of its "
                    "head, and a long curled tail; distinguish it from the similar "
                    "Pansear and Panpour by its green coloring. "
                    "White Flower Flabébé is a tiny white-bodied fairy Pokémon with "
                    "large red eyes and a yellow, scalloped head tuft, clinging to a "
                    "single large white flower with a yellow center, green stem, and "
                    "leaves. Identify its flower color from the petals it holds, not "
                    "from its yellow head or the scene; do not mistake the flower for "
                    "part of its body or confuse it with Floette, which has a more "
                    "developed, upright body and holds its flower differently. "
                    "Lairon is a stocky, low-slung, four-legged armored Pokémon with "
                    "overlapping pale silver-white metal plates marked by distinct black "
                    "round spots, a gray segmented body, and a blunt horned head with "
                    "blue eyes. Distinguish its spotted armor and compact quadrupedal "
                    "shape from the smaller, smoother Aron and the larger, more imposing "
                    "Aggron; do not identify it as Aggron from the steel armor alone. "
                    "Cascoon is a floating cocoon-shaped Pokémon with a pale lavender "
                    "segmented shell, several long pointed spikes, and one visible red "
                    "eye; distinguish it from Silcoon, which is green and has no spikes. "
                    "Sewaddle is a small green caterpillar-like Pokémon wearing a "
                    "large leaf hood, with a yellow face, black eyes, orange mouth, and "
                    "a segmented green body with small orange bumps; distinguish it from "
                    "other small Bug-type Pokémon by the leaf covering its head. "
                    "Blipbug is a tiny blue-purple insect Pokémon with an oversized "
                    "round head, very large pale oval eyes with dark pupils, two long "
                    "thin antennae, a small yellow-orange mouth, and a short segmented "
                    "body with tiny legs. Its large eyes dominate its face and its "
                    "antennae rise distinctly above the head. Distinguish this small "
                    "crawling larva from Dottler's larger, round orange shell and "
                    "Orbeetle's red-domed, flying saucer-like form. "
                    "Scatterbug (Purmel) is a small gray caterpillar Pokémon with a "
                    "large round charcoal-gray head, pale cream eye rings with narrow "
                    "vertical pupils, three thin white hairs sticking up from its head, "
                    "and a short segmented gray body with pale spots and a white ruff "
                    "around its neck. Distinguish it from the more compact, cocoon-shaped "
                    "Spewpa and do not mistake its upright antenna-like hairs for horns. "
                    "Prinplup is a medium-sized upright penguin Pokémon with a dark "
                    "navy-blue head, back, and broad flipper-like wings; a light blue "
                    "belly marked with several large white oval spots; a sharp yellow "
                    "three-point crest over its eyes; and yellow webbed feet. Distinguish "
                    "it from the smaller, rounder Piplup and the larger Empoleon, which "
                    "has a prominent trident-shaped head crest and a more armored build. "
                    "Lileep is a stationary-looking fossil Pokémon with a short purple "
                    "stalk rooted in a flared, lobed base, supporting a rounded purple "
                    "cup-shaped body. Its black face sits at the top center with two "
                    "small yellow eyes, surrounded by several long, curved pink tentacles "
                    "that spread outward like a flower or sea lily. Distinguish Lileep "
                    "from Cradily, which has a longer neck, a wider green body, and "
                    "more conspicuous yellow markings. "
                    "Pyukumuku is a small black, flattened oval sea-cucumber Pokémon "
                    "with several short pink spikes on its back, tiny pink eyes, and a "
                    "distinctive white X-shaped mouth; do not confuse its oval silhouette "
                    "with a fish or spiky sea creature. "
                    "Tadbulb is a tiny floating electric Pokémon with a large bright "
                    "yellow bulb-like head, a dark gray face area with small glowing "
                    "eyes, and a short dangling orange-and-gray tail; distinguish it "
                    "from round yellow Pokémon by this dark face and tapered tail. "
                    "Toedscool is a small, pale pinkish-white mushroom-like Pokémon "
                    "with a smooth rounded cap-shaped body, bright yellow circular "
                    "markings on its head, and a small face with narrow eyes and a "
                    "toothy mouth. Its two long, thin, flexible legs trail beneath it "
                    "like tentacles. Distinguish Toedscool from Tentacool by its "
                    "mushroom-like body and leg-shaped tentacles rather than a blue "
                    "jellyfish body with multiple tentacles. "
                    "Snorunt is a small, cone-shaped Pokémon enclosed in a pale yellow "
                    "triangular hood with an orange inner border, a dark face opening "
                    "with two small blue eyes, and a wide row of white, tooth-like "
                    "markings near the bottom of the face. Its short dark feet and "
                    "rounded black mitten-like hands peek out below the hood; distinguish "
                    "this hooded, triangular silhouette from other Ice-type Pokémon. "
                    "Cetitan is a very large, stocky white whale-like Pokémon with a "
                    "rounded segmented body, small pink-rimmed eyes, short legs, and "
                    "prominent pointed horn-like protrusions on its head and body. Its "
                    "broad flipper-like limbs and tail have pink accents. Distinguish "
                    "the massive, round, multi-horned Cetitan from the much smaller, "
                    "smoother Cetoddle; do not confuse its pale body with a generic "
                    "snowball-shaped Pokémon. "
                    "Nihilego is a floating, translucent jellyfish-like Ultra Beast "
                    "with a domed, glassy pale lavender bell marked by white star-like "
                    "shapes, a wavy light-blue frilled rim, and several long, thin "
                    "ribbon-like tentacles hanging below. Its bell and tentacles create "
                    "a delicate, nearly transparent silhouette; distinguish it from "
                    "ordinary jellyfish Pokémon by the distinctive star patterns and "
                    "pale blue scalloped edge, not just its floating pose. "
                    "Honedge is a floating ghost sword with a single blue eye set "
                    "in its brown-and-gold hilt, a long gray blade, and a blue cloth "
                    "strip wrapped around the hilt and trailing behind it. Its blade "
                    "may be partly covered by a brown sheath-like section with a dark "
                    "diamond-shaped opening. Distinguish the single-eyed sword form "
                    "from Doublade's two crossed swords and Aegislash's shield. "
                    "Marill is a small, round blue mouse-like Pokémon with a white "
                    "belly, large round ears with reddish inner surfaces, and a thin "
                    "black zigzag tail ending in a blue ball. The tail ball is attached "
                    "by the distinctive angular black stem and is a key identifying "
                    "feature; distinguish Marill from Azurill, which has a different "
                    "body color and a large blue ball tail on a spring-like black stem. "
                    "Tandemaus consists of two tiny, nearly identical white mouse-like "
                    "Pokémon standing together as a pair, with round bodies, large "
                    "circular ears, small black eyes and noses, and pale gray lower-body "
                    "markings. Identify the pair as one Pokémon, not two separate "
                    "individuals; distinguish its paired composition from a single "
                    "mouse Pokémon such as Maushold, whose family has more members. "
                    "Sandile is a small, low-slung crocodile-like Pokémon with tan "
                    "skin crossed by broad dark brown bands, a long snout, and oversized "
                    "black goggle-like patches around its eyes with small visible pupils. "
                    "It has a dark-tipped tail and short clawed legs. Distinguish Sandile "
                    "from Krokorok by its smaller, more compact body and lack of Krokorok's "
                    "prominent dark body markings and sunglasses-like eye mask. "
                    "Rellor is a tiny dung beetle Pokémon with a low, rounded cream-tan "
                    "body, short jointed legs, and a vivid pink face with dark eyes. It "
                    "pushes a very large, nearly spherical brown ball marked with curved "
                    "yellow-orange bands and pale streaks. Treat the ball as a separate "
                    "object being rolled in front of Rellor, not as the Pokémon's body; "
                    "distinguish this beetle-and-ball silhouette from a round-bodied "
                    "Pokémon such as Spheal. "
                    "Fraxure is a sturdy bipedal dragon Pokémon with a green armored "
                    "head and upper body, a broad gray lower body, red claws, and two "
                    "long, blade-like tusks projecting sideways from its jaw; the tusks "
                    "are gray with red tips. It also has a dark gray tail with a red tip "
                    "and small red markings on its belly. Distinguish Fraxure's two "
                    "prominent side tusks and stocky build from the smaller Axew and "
                    "the larger, more heavily armored Haxorus with massive curved tusks. "
                    "Hisuian Arcanine is a large, muscular orange-red canine Pokémon "
                    "with bold black zigzag bands across its legs and torso, a charcoal "
                    "gray rocky mane and enormous curled bushy tail, and dark gray "
                    "stone-like horns. Its mane and tail are dark gray rather than the "
                    "cream-colored fur of standard Arcanine. Identify the Hisuian form "
                    "from the rocky gray head, chest, and tail fur together with its "
                    "orange-and-black body markings. "
                    "Gimmighoul in Chest Form is a tiny gray ghost with round eyes "
                    "peeking out of or floating above an open red-and-gold treasure chest "
                    "filled with gold coins; the chest is its characteristic form, not "
                    "a separate Pokémon. Look for the small gray body and coin-filled "
                    "chest together, and distinguish this form from Roaming Form "
                    "Gimmighoul, which is a tiny gray ghost carrying a single coin and "
                    "has no chest. "
                    "Simisear is a red-orange bipedal monkey Pokémon with a cream-yellow "
                    "face, large yellow inner ears, yellow hands and feet, and fluffy "
                    "white tufts at its neck. Its most distinctive features are the "
                    "curled flame-shaped red crest on its head and flame-like pointed "
                    "tail. Distinguish it from green Simisage, which has leafy head "
                    "features, and blue Simipour, which has a water-droplet-shaped "
                    "crest and a curled tail tuft. "
                    "Palpitoad is a squat blue amphibian Pokémon with a broad cream "
                    "belly, a large dark rounded disk on its forehead topped by a pale "
                    "blue bulb, and rounded blue-and-black nodules on the sides of its "
                    "head and body. It has small eyes peeking from below the forehead "
                    "disk and a short pale tail. Distinguish Palpitoad from Tympole's "
                    "small round body and long tail, and from Seismitoad's larger, "
                    "more muscular build and prominent raised bumps. "
                    "DJ Rotom is a Rotom form integrated into a portable stereo setup: "
                    "a small orange central body with Rotom's expressive face and a "
                    "music-equalizer panel sits between two large rectangular speakers "
                    "with dark circular speaker cones and orange trim. A short antenna "
                    "or lightning-bolt-shaped element rises above the center. Identify "
                    "the whole speaker-and-Rotom assembly as DJ Rotom, not as a plain "
                    "stereo or a Rotom next to unrelated speakers. "
                    "Seedot is a tiny acorn-shaped Pokémon with a smooth tan-brown "
                    "body, small feet, and a gray, layered acorn cap topped by a short "
                    "upright stem. Its large cream-colored eyes have dark, heavy-looking "
                    "outlines. Distinguish this compact seed-like body and capped head "
                    "from Nuzleaf, which is taller and has a leaf-like head and limbs. "
                    "Smoliv is a tiny, pale yellow-green olive Pokémon with a squat, "
                    "pear-shaped body, small black eyes, and a little wavy mouth. A "
                    "round olive fruit with a short green leaf grows on top of its head, "
                    "with two green leaves projecting from the sides of its neck. "
                    "Distinguish Smoliv's single head olive and small rounded body from "
                    "Dolliv, which is taller and has a more developed leafy crown, and "
                    "Arboliva, which is much larger and tree-like. "
                    "Ducklett is a small pale blue duckling Pokémon with a long neck, "
                    "large oval eyes, a broad yellow bill, and yellow webbed feet. It "
                    "has a distinctive two-lobed heart-shaped tuft on top of its head "
                    "and a large pale blue wing that may be raised behind it. Distinguish "
                    "Ducklett from the larger, more swan-like Swanna by its rounder "
                    "duckling body, short tail, and head tuft. "
                    "Shroodle is a tiny, low-slung, dark gray rodent-like Pokémon with "
                    "a very large pale mint-green eye area, a rounded dark bulbous snout, "
                    "a small pale tuft on top of its head, and short purple feet and tail. "
                    "Its crouched body may appear almost hidden behind its oversized "
                    "head. Distinguish it from Grafaiai, which is taller and has a "
                    "longer, more upright body and colorful markings on its fingers. "
                    "Remoraid is a small pale blue-gray fish Pokémon with a rounded "
                    "streamlined body, a pointed snout, one prominent horn-like dorsal "
                    "fin, several dark blue stripes along its side, and large pale "
                    "split fins, especially its forked tail. Distinguish it from "
                    "Octillery, its larger octopus-like evolution, and do not mistake "
                    "the dorsal fin for a horn on a land Pokémon. "
                    "Boldore is a squat, angular rock Pokémon made of dark navy-blue "
                    "faceted stone, with a pointed ridge rising from its back, narrow "
                    "yellow eyes, and several bright orange-red crystal spikes protruding "
                    "from its body and legs. Its broad blocky front limbs give it a "
                    "low, sturdy stance. Distinguish Boldore from Roggenrola's small "
                    "round body and Gigalith's much larger, heavily crystal-covered form. "
                    "Salandit is a small, low-slung dark gray lizard Pokémon with a "
                    "narrow head, four short legs, and a long slender tail that curves "
                    "upward and has a vivid red-orange stripe along its underside. Look "
                    "for pale lavender markings around its face and orange-red accents "
                    "near the tail base. Distinguish the compact four-legged Salandit "
                    "from Salazzle's taller, upright, more humanoid shape. "
                    "Impidimp is a small, wiry pink imp Pokémon with a large rounded "
                    "pink head, long pointed ears with red inner surfaces, and a dark "
                    "purple mask-like marking around its pale face and eyes. It has "
                    "thin long arms with three-pronged hands, slender legs, and a "
                    "pointed dark tuft beneath its chin. Distinguish it from Morgrem "
                    "and Grimmsnarl by its smaller, less muscular body and oversized "
                    "head and ears. "
                    "Gothita is a small, doll-like Pokémon with a large lavender "
                    "head, bright blue eyes, black pointed hair tufts, and oversized "
                    "white bow-shaped tufts on either side of its head. It wears a "
                    "small black dress-like body with a prominent white bow at the "
                    "neck and a jagged white band around the waist. Distinguish Gothita "
                    "from Gothorita and Gothitelle by its much smaller, rounder body "
                    "and especially large head bows. "
                    "Monferno is a nimble orange bipedal monkey Pokémon with a vivid "
                    "blue mask-like marking around its eyes, a cream-colored muzzle and "
                    "belly, a shaggy white neck ruff, and a long tail tipped with flame. "
                    "It has large round ears and long, spread-out limbs with darker "
                    "hands and feet. Distinguish Monferno from smaller Chimchar, which "
                    "has a simpler face and a prominent flame atop its head, and from "
                    "Infernape, which has a more elaborate flame-like head crest and "
                    "bulkier golden armor-like markings. "
                    "Stufful is a small, compact pink teddy-bear Pokémon with a pale "
                    "cream muzzle, short rounded limbs, and distinctive dark ear patches "
                    "with pink inner ears. Its plush, cub-like proportions are much "
                    "smaller and rounder than Bewear's. Bewear is a large pink bear with "
                    "a broad white mask-like face marking, very long dark brown arms and "
                    "legs, and a short tail with a pink circular spot; use its long dark "
                    "limbs and bulky build to distinguish it from Stufful. "
                    "Dracozolt is a visibly mismatched fossil-fusion Pokémon with a "
                    "small yellow bird-like upper body and head attached to a much "
                    "larger teal, long-tailed dinosaur-like lower body. Look for the "
                    "row of tall red-pink plates along its back and tail, red-pink "
                    "bands on its teal legs, and yellow lightning-shaped markings "
                    "across its chest. The bird upper half appears perched at the front "
                    "of the oversized reptilian body; distinguish this combination from "
                    "the other Galar fossil Pokémon by its teal hindquarters and long "
                    "spined tail. "
                    "Vigoroth is a lean, active white sloth-like Pokémon with shaggy "
                    "fur, a red tuft on its forehead, a brown mask around its eyes, "
                    "and long powerful arms ending in dark claws. It has a small pointed "
                    "tail and an energetic, often upright or lunging posture. Distinguish "
                    "it from Slakoth's relaxed horizontal pose and brown body, and from "
                    "Slaking's much larger, heavier build and broad pale face marking. "
                    "Tinkatuff is a small pink humanoid Pokémon with a rounded head, "
                    "a pale pink swept-back hair tuft, and a bold pale zigzag marking "
                    "across its forehead. It carries an oversized rough gray metal "
                    "hammer with a blocky head and purple handle. Distinguish it from "
                    "Tinkatink, which has a much smaller, simpler hammer, and from "
                    "Tinkaton, which is taller and carries an even larger hammer. "
                    "Peakychu is a small, plump, pale cream-white Pikachu-like Pokémon "
                    "with a rounded upright body, long floppy ears with tan tips, large "
                    "dark eyes, pink oval cheek patches, tiny feet, and subtle lavender "
                    "shading along its lower body. Identify it by this soft, mostly white "
                    "appearance and drooping ears rather than assuming every Pikachu-like "
                    "face is standard yellow Pikachu. "
                    "Charcadet is a small humanoid Pokémon with a dark charcoal helmet-like "
                    "head, a glowing orange-red eye, red and orange armor-like body parts, "
                    "and a small flame-like plume on top; distinguish it from other "
                    "fire-themed humanoid Pokémon by its oversized dark head. "
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


def format_server_reservation_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
) -> list[discord.Embed]:
    guild_prefix = f"{guild_id}:"
    entries = sorted(
        (
            f"{key.removeprefix(guild_prefix)} <@{user_id}>"
            for key, user_ids in reservations.items()
            if key.startswith(guild_prefix)
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


def format_pokemon_reserver_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[discord.Embed]:
    key = reservation_key(guild_id, pokemon_name)
    user_ids = sorted(set(reservations.get(key, [])))
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
            if re.fullmatch(r"v!ping\s*", message.content, re.IGNORECASE):
                await self.handle_ping_command(message)
                return
            if re.match(r"^v!sh(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_shinyhunt_command(message)
                return
            if re.match(
                r"^v!r\s+(?:add|list|search|remove|clear)(?:\s|$)",
                message.content,
                re.IGNORECASE,
            ):
                await self.handle_reserve_command(message)
            return

        if SPAWN_PATTERN.search(text):
            await self.handle_spawn(message)

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

        embeds = format_pokemon_reserver_embeds(
            self.reservations,
            message.guild.id,
            pokemon_name,
        )
        await reply_with_reservation_embeds(message, embeds)

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
