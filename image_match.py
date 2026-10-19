"""Recognise spawns from reference pictures, ignoring the background.

`build_image_bank.py` turns the pictures in pokemon_images/ into a compact
feature file (image_bank.npz). The bot only loads that file.
"""

import logging
import re
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # Optional: without them the bot falls back to OpenAI.
    cv2 = None
    np = None

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
FEATURES_PER_IMAGE = 800
MAX_SIDE = 800
MAX_FEATURES_PER_POKEMON = 300
CONSENSUS_COMPARISONS = 8
RATIO = 0.8
MIN_VOTES = 6
MIN_MARGIN = 3
SHARED_DISTANCE = 150.0
DUPLICATE_DISTANCE = 100.0
BANK_FILE = "image_bank.npz"
# Bank entries that are kept separate for recognition but reported under another name.
DISPLAY_NAMES = {
    "Busted Mimikyu": "Mimikyu",
    "Disguised Mimikyu": "Mimikyu",
    "Full-Belly Morpeko": "Morpeko",
    "Hangry Morpeko": "Morpeko",
    "Paldean Tauros": "Tauros",
    "Totem-Busted Mimikyu": "Mimikyu",
    "Totem-Disguised Mimikyu": "Mimikyu",
}
# Folders like "Unown Variant 3" are learned separately (so each can have its own
# thumbnail) but the Pokémon is still named after the base species.
VARIANT_PATTERN = re.compile(r"^(?P<base>.+?)\s+variant\s+(?P<number>\d+)$", re.IGNORECASE)


NEIGHBOURS = 6


def base_pokemon_name(name: str) -> str:
    match = VARIANT_PATTERN.match(name)
    return match.group("base") if match else name


def compute_descriptors(data: bytes, mirror: bool = False, mask=None):
    """SIFT descriptors (float32) of an image, or None if unreadable."""
    if cv2 is None:
        return None
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    if mirror:
        image = cv2.flip(image, 1)
        if mask is not None:
            mask = cv2.flip(mask, 1)
    scale = MAX_SIDE / max(image.shape)
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if mask is not None:
            mask = cv2.resize(mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=FEATURES_PER_IMAGE)
    _, descriptors = sift.detectAndCompute(image, mask)
    return descriptors


def pokemon_name_from_file(path: Path) -> str:
    return re.sub(r"(?:[\s_-]+\(?\d+\)?|\s*\(\d+\))$", "", path.stem).strip()


def reference_images(folder: Path) -> dict[str, list[Path]]:
    """Group images by canonical Pokémon/form name, anywhere below folder."""
    import json
    import unicodedata

    def key(value: str) -> str:
        value = unicodedata.normalize("NFKD", value.casefold())
        value = "".join(char for char in value if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]", "", value)

    try:
        species = json.loads(
            Path(__file__).with_name("pokemon_names.json").read_text(encoding="utf-8")
        )
        form_data = json.loads(
            Path(__file__).with_name("pokemon_forms.json").read_text(encoding="utf-8")
        )["forms"]
    except (OSError, ValueError, KeyError, TypeError):
        species, form_data = [], {}

    species_by_key = {key(name): name for name in species}
    forms_by_key: dict[str, str] = {}
    for species_name, forms in form_data.items():
        canonical_species = (
            species_by_key.get(key(species_name), species_name.title())
            if key(species_name) == key("pumpkaboo")
            else None
        )
        for form in forms:
            display = form["display_name"].title()
            canonical = canonical_species or display
            forms_by_key[key(form["identifier"])] = canonical
            forms_by_key[key(form["display_name"])] = canonical

    regions = {
        "alola": "Alolan",
        "galar": "Galarian",
        "hisui": "Hisuian",
        "paldea": "Paldean",
    }
    event_tokens = {
        "anniversary", "autumn", "christmas", "day", "easter", "festive",
        "halloween", "of", "pride", "spring", "summer", "thanksgiving",
        "the", "valentine", "weather", "winter",
    }

    def canonical_name(raw: str) -> str | None:
        raw = raw.strip()
        normalized_key = key(raw)
        if normalized_key in forms_by_key:
            return forms_by_key[normalized_key]
        if normalized_key in species_by_key:
            return species_by_key[normalized_key]

        tokens = raw.casefold().replace("_", "-").split("-")
        for index, token in enumerate(tokens):
            if token in regions:
                base = species_by_key.get(key("".join(tokens[:index])))
                if base:
                    return f"{regions[token]} {base}"

        # Event costumes remain catchable as their base species. Composite
        # pictures containing multiple species are intentionally not assigned.
        kept = [token for token in tokens if token not in event_tokens]
        found: set[str] = set()
        for start in range(len(kept)):
            for end in range(start + 1, len(kept) + 1):
                name = species_by_key.get(key("".join(kept[start:end])))
                if name:
                    found.add(name)
        if len(found) == 1:
            return next(iter(found))
        if len(found) > 1:
            return None

        # Preserve a readable name for hand-created forms such as Zygarde-Core.
        return "-".join(token[:1].upper() + token[1:] for token in raw.replace("_", "-").split("-"))

    groups: dict[str, list[Path]] = {}
    skipped: set[str] = set()
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES or path.name.startswith("."):
            continue
        raw_name = path.parent.name if path.parent != folder else pokemon_name_from_file(path)
        variant = VARIANT_PATTERN.match(raw_name)
        if variant:
            base = canonical_name(variant.group("base"))
            name = f"{base} Variant {int(variant.group('number'))}" if base else None
        else:
            name = canonical_name(raw_name)
        if name is None:
            skipped.add(raw_name)
            continue
        groups.setdefault(name, []).append(path)
    if skipped:
        logger.warning("Skipped ambiguous composite image folders: %s", ", ".join(sorted(skipped)))
    return groups


def consensus_descriptors(descriptor_sets: list):
    """Keep features that repeat across a Pokémon's pictures (not backgrounds)."""
    count = len(descriptor_sets)
    matcher = cv2.BFMatcher()
    kept = []
    for index, descriptors in enumerate(descriptor_sets):
        others = [i for i in range(count) if i != index]
        step = max(1, len(others) // CONSENSUS_COMPARISONS)
        others = others[::step][:CONSENSUS_COMPARISONS]
        hits = np.zeros(len(descriptors), int)
        for other in others:
            for position, pair in enumerate(
                matcher.knnMatch(descriptors, descriptor_sets[other], k=2)
            ):
                if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance:
                    hits[position] += 1
        needed = 1 if len(others) < 3 else max(2, len(others) // 4)
        kept.append(descriptors[hits >= needed])
    return np.vstack(kept) if kept else np.zeros((0, 128), np.float32)


def drop_duplicates(descriptors):
    if len(descriptors) == 0:
        return descriptors
    squared = (descriptors**2).sum(1)
    chosen: list[int] = []
    for index in range(len(descriptors)):
        if chosen:
            distances = (
                squared[chosen] + squared[index] - 2 * descriptors[chosen] @ descriptors[index]
            )
            if distances.min() < DUPLICATE_DISTANCE**2:
                continue
        chosen.append(index)
    return descriptors[chosen]


class ImageMatcher:
    def __init__(self, bank_path: Path) -> None:
        self.names: list[str] = []
        self.labels = None
        self.matcher = None
        if cv2 is None or not bank_path.is_file():
            return
        try:
            with np.load(bank_path, allow_pickle=False) as data:
                descriptors = data["descriptors"].astype(np.float32)
                self.names = [str(name) for name in data["names"]]
                self.labels = data["labels"]
                self.families = [base_pokemon_name(name) for name in self.names]
        except (OSError, ValueError, KeyError):
            logger.warning("Could not read %s; image matching disabled", bank_path)
            self.names = []
            return
        self.matcher = cv2.FlannBasedMatcher(
            dict(algorithm=1, trees=4), dict(checks=32)
        )
        self.matcher.add([descriptors])
        self.matcher.train()
        logger.info(
            "Loaded image bank: %d Pokémon, %d features",
            len(self.names),
            len(descriptors),
        )

    @property
    def entries(self) -> list[str]:
        return self.names

    def match(self, data: bytes) -> tuple[str, int] | None:
        """Return (pokemon name, votes) when one Pokémon clearly wins.

        Spawns can face either way, so the picture is also tried mirrored.
        """
        if not self.names or self.matcher is None:
            return None
        results = [
            result
            for result in (self._match(data, False), self._match(data, True))
            if result is not None
        ]
        return max(results, key=lambda result: result[1]) if results else None

    def _match(self, data: bytes, mirror: bool) -> tuple[str, int] | None:
        descriptors = compute_descriptors(data, mirror)
        if descriptors is None or len(descriptors) < 2:
            return None
        votes = np.zeros(len(self.names), int)
        for neighbours in self.matcher.knnMatch(descriptors, k=NEIGHBOURS):
            if len(neighbours) < 2:
                continue
            best_label = int(self.labels[neighbours[0].trainIdx])
            rival = neighbours[1]
            if self.names[best_label] != self.families[best_label]:
                # Variants of one species share features; only outside rivals count.
                family = self.families[best_label]
                rival = next(
                    (n for n in neighbours[1:] if self.families[int(self.labels[n.trainIdx])] != family),
                    neighbours[-1],
                )
            if neighbours[0].distance < RATIO * rival.distance:
                votes[best_label] += 1
        order = np.argsort(votes)[::-1]
        best = int(votes[order[0]])
        second = int(votes[order[1]]) if len(order) > 1 else 0
        name = self.names[int(order[0])]
        # Variant pictures (e.g. Unown letters) are plain shapes with few features.
        is_variant = VARIANT_PATTERN.match(name) is not None
        min_votes, min_margin = (2, 2) if is_variant else (MIN_VOTES, MIN_MARGIN)
        if best >= min_votes and best - second >= max(min_margin, 0.3 * best):
            return DISPLAY_NAMES.get(name, name), best
        return None
