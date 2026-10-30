"""Recognise spawns from reference pictures, ignoring the background.

`build_image_bank.py` turns the pictures in pokemon_images/ into a compact
feature file (image_bank.npz). The bot only loads that file.
"""

import logging
import re
from functools import lru_cache
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
SPECIES_MIN_VOTES = {"Boldore": 8, "Milcery": 6}
SPECIES_MIN_MARGIN = {"Boldore": 4, "Milcery": 3}
SHARED_DISTANCE = 150.0
DUPLICATE_DISTANCE = 100.0
BANK_FILE = "image_bank.npz"
# Bank entries that are kept separate for recognition but reported under another name.
DISPLAY_NAMES = {
    "Busted Mimikyu": "Mimikyu",
    "Disguised Mimikyu": "Mimikyu",
    "Full-Belly Morpeko": "Morpeko",
    "Paldean Tauros": "Tauros",
    "Totem-Busted Mimikyu": "Mimikyu",
    "Totem-Disguised Mimikyu": "Mimikyu",
}
CUSTOM_FORM_SPECIES = {
    "Partner Pikachu": "Pikachu",
    "Gliding Build Koraidon": "Koraidon",
    "Zenith Marshadow": "Marshadow",
    "Galarian Zen Darmanitan": "Darmanitan",
    "Zygarde Cell": "Zygarde",
    "Combat Breed Tauros": "Tauros",
    "Blaze Breed Tauros": "Tauros",
    "Aqua Breed Tauros": "Tauros",
}
# Folders like "Unown Variant 3" are learned separately (so each can have its own
# thumbnail) but the Pokémon is still named after the base species.
VARIANT_PATTERN = re.compile(r"^(?P<base>.+?)\s+variant\s+(?P<number>\d+)$", re.IGNORECASE)


NEIGHBOURS = 6
REFERENCE_PATCH = 192
GOOD_ALIGNMENT = 25


def base_pokemon_name(name: str) -> str:
    match = VARIANT_PATTERN.match(name)
    return match.group("base") if match else name


SILVALLY_TYPES = (
    "Bug", "Dark", "Dragon", "Electric", "Fighting", "Fire", "Flying", "Ghost",
    "Grass", "Ground", "Ice", "Poison", "Psychic", "Rock", "Steel", "Water", "Fairy",
)
SILVALLY_FORMS = frozenset({"Silvally", *(f"{kind} Silvally" for kind in SILVALLY_TYPES)})
VIVILLON_FORMS = (
    "Vivillon", "Icy-Snow Vivillon", "Polar Vivillon", "Tundra Vivillon",
    "Continental Vivillon", "Garden Vivillon", "Elegant Vivillon", "Modern Vivillon",
    "Marine Vivillon", "Archipelago Vivillon", "High-Plains Vivillon",
    "Sandstorm Vivillon", "River Vivillon", "Monsoon Vivillon", "Savanna Vivillon",
    "Sun Vivillon", "Ocean Vivillon", "Jungle Vivillon", "Fancy Vivillon",
    "Poke-Ball Vivillon",
)
VIVILLON_FORM_SET = frozenset(VIVILLON_FORMS)
ARCEUS_FORMS = (
    "Arceus", *(f"{kind} Arceus" for kind in SILVALLY_TYPES),
)
ARCEUS_FORM_SET = frozenset(ARCEUS_FORMS)
# Names shown to users for the bank entries above.
FORM_DISPLAY_NAMES = {
    "Icy-Snow Vivillon": "Icy Snow Vivillon",
    "High-Plains Vivillon": "High Plains Vivillon",
    "Poke-Ball Vivillon": "Poké Ball Vivillon",
}
THUMBNAIL_DIR = Path(__file__).with_name("assets") / "thumbnails"


# Forms the matcher reports as-is so their own thumbnail can be chosen; the
# Pokémon is still named after the species.
THUMBNAIL_FORM_SPECIES = {
    "Blue-Plumage Squawkabilly": "Squawkabilly",
    "Green-Plumage Squawkabilly": "Squawkabilly",
    "Hangry Morpeko": "Morpeko",
    "White-Plumage Squawkabilly": "Squawkabilly",
    "Yellow-Plumage Squawkabilly": "Squawkabilly",
    **{
        form: "Minior"
        for form in (
            "Blue-Meteor Minior",
            "Blue Minior",
            "Green-Meteor Minior",
            "Green Minior",
            "Indigo-Meteor Minior",
            "Indigo Minior",
            "Orange-Meteor Minior",
            "Orange Minior",
            "Red-Meteor Minior",
            "Red Minior",
            "Violet-Meteor Minior",
            "Violet Minior",
            "Yellow-Meteor Minior",
            "Yellow Minior",
        )
    },
    "East Gastrodon": "Gastrodon",
    "East Sea Gastrodon": "Gastrodon",
    "East Sea Shellos": "Shellos",
    "East Shellos": "Shellos",
    "West Gastrodon": "Gastrodon",
    "West Sea Gastrodon": "Gastrodon",
    "West Sea Shellos": "Shellos",
    "West Shellos": "Shellos",
    **CUSTOM_FORM_SPECIES,
    **{form: "Silvally" for form in SILVALLY_FORMS},
    **{form: "Vivillon" for form in VIVILLON_FORMS},
    **{form: "Arceus" for form in ARCEUS_FORMS},
}


# Forms that look alike share features, so they count as one family when
# deciding which features are distinctive.
FAMILY_OVERRIDES = {
    "Finizen": "Palafin",
    "Hero Palafin": "Palafin",
    **CUSTOM_FORM_SPECIES,
    **{form: "Silvally" for form in SILVALLY_FORMS},
    **{form: "Vivillon" for form in VIVILLON_FORMS},
    **{form: "Arceus" for form in ARCEUS_FORMS},
}
# Families whose members are near-identical pictures: the best-scoring member
# is named even when members of the same family score closely.
INDISTINGUISHABLE_FAMILIES = {"Palafin", "Silvally", "Vivillon", "Arceus"}


def family_name(name: str) -> str:
    return FAMILY_OVERRIDES.get(name, base_pokemon_name(name))


def species_display_name(name: str) -> str:
    return THUMBNAIL_FORM_SPECIES.get(name, base_pokemon_name(name))


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


def foreground_mask(data: bytes):
    """Mask the Pokémon using its alpha channel or a GrabCut cutout."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 3 and image.shape[2] == 4:
        return np.where(image[..., 3] > 128, 255, 0).astype(np.uint8)
    if image.ndim != 3:
        return None
    height, width = image.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    rect = (int(width * 0.12), int(height * 0.1), int(width * 0.76), int(height * 0.8))
    cv2.grabCut(image, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_RECT)
    cut = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
    cut = cv2.morphologyEx(cut, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cut)
    if count > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        cut = np.where(labels == biggest, 255, 0).astype(np.uint8)
    cut = cv2.dilate(cut, np.ones((5, 5), np.uint8))
    return cut if cut.any() else None


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
    custom_forms_by_key = {key(form): form for form in CUSTOM_FORM_SPECIES}
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
        if normalized_key in custom_forms_by_key:
            return custom_forms_by_key[normalized_key]
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


def has_belly_patch(data: bytes) -> bool | None:
    """Palafin has a red patch on its belly that Finizen lacks."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    scale = 800 / max(image.shape[:2])
    if scale > 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] < 10) | (hsv[..., 0] > 165)) & (hsv[..., 1] > 60) & (hsv[..., 2] > 120)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(red.astype(np.uint8))
    grey = (hsv[..., 1] < 50) & (hsv[..., 2] > 90) & (hsv[..., 2] < 220)
    kernel = np.ones((5, 5), np.uint8)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < 40 or area > 400 or w < 1.5 * h:
            continue
        blob = (labels == i).astype(np.uint8)
        ring = (cv2.dilate(blob, kernel, iterations=2) > 0) & (blob == 0)
        # The patch sits on the grey belly, unlike reddish background details.
        if grey[ring].mean() >= 0.5:
            return True
    return False


def silvally_thumbnail_path(form: str) -> Path:
    return THUMBNAIL_DIR / (re.sub(r"[^a-z0-9]", "", form.casefold()) + ".png")


@lru_cache(maxsize=1)
def _silvally_references():
    """Normal Silvally's features plus each type's colour in the plume/fin area."""
    if cv2 is None:
        return None
    images = {}
    for form in SILVALLY_FORMS:
        image = cv2.imread(str(silvally_thumbnail_path(form)), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] != 4:
            return None
        images[form] = image
    base = images["Silvally"]
    solid = base[..., 3] > 128
    differs = np.zeros(solid.shape, bool)
    for image in images.values():
        if image.shape != base.shape:
            return None
        differs |= np.abs(image[..., :3].astype(int) - base[..., :3].astype(int)).max(2) > 40
    area = cv2.erode((differs & solid).astype(np.uint8), np.ones((3, 3), np.uint8))
    if int(area.sum()) < 200:
        return None
    colours = {
        form: np.median(cv2.cvtColor(image[..., :3], cv2.COLOR_BGR2LAB)[area > 0], axis=0)
        for form, image in images.items()
    }
    keypoints, descriptors = cv2.SIFT_create().detectAndCompute(
        cv2.cvtColor(base[..., :3], cv2.COLOR_BGR2GRAY), solid.astype(np.uint8) * 255
    )
    if descriptors is None or len(keypoints) < 10:
        return None
    points = np.float32([keypoint.pt for keypoint in keypoints])
    return area, colours, points, descriptors


def silvally_form_by_color(data: bytes) -> str | None:
    """Tell Silvally's type forms apart; they only differ in colour."""
    references = _silvally_references()
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if cv2 else None
    if references is None or image is None:
        return None
    area, colours, ref_points, ref_descriptors = references
    scale = MAX_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    best: tuple[int, str] | None = None
    for mirror, upscale in ((False, 1), (True, 1), (False, 2), (True, 2)):
        if best is not None and best[0] >= GOOD_ALIGNMENT and upscale > 1:
            break
        candidate = cv2.flip(image, 1) if mirror else image
        if upscale > 1:
            candidate = cv2.resize(candidate, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        keypoints, descriptors = cv2.SIFT_create(nfeatures=FEATURES_PER_IMAGE * upscale).detectAndCompute(
            cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY), None
        )
        if descriptors is None or len(keypoints) < 10:
            continue
        pairs = cv2.BFMatcher().knnMatch(ref_descriptors, descriptors, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 8:
            continue
        source = np.float32([ref_points[m.queryIdx] for m in good])
        target = np.float32([keypoints[m.trainIdx].pt for m in good])
        matrix, inliers = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
        if matrix is None or int(inliers.sum()) < 8:
            continue
        height, width = candidate.shape[:2]
        region = cv2.warpPerspective(area, matrix, (width, height), flags=cv2.INTER_NEAREST) > 0
        if int(region.sum()) < 100:
            continue
        observed = np.median(cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB)[region], axis=0)
        form = min(colours, key=lambda f: float(np.linalg.norm(colours[f] - observed)))
        if best is None or int(inliers.sum()) > best[0]:
            best = (int(inliers.sum()), form)
    return best[1] if best else None


def form_thumbnail_path(form: str) -> Path:
    return THUMBNAIL_DIR / (re.sub(r"[^a-z0-9]", "", form.casefold()) + ".png")


@lru_cache(maxsize=None)
def _pattern_references(forms: tuple[str, ...]):
    """Each form's picture, the area where the forms differ, and alignment features."""
    if cv2 is None:
        return None
    images = {}
    for form in forms:
        image = cv2.imread(str(form_thumbnail_path(form)), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] != 4:
            return None
        images[form] = image
    base = images[forms[0]]
    if any(image.shape != base.shape for image in images.values()):
        return None
    solid = (base[..., 3] > 128).astype(np.uint8)
    small = (REFERENCE_PATCH, REFERENCE_PATCH)
    lab = {
        form: cv2.resize(
            cv2.cvtColor(image[..., :3], cv2.COLOR_BGR2LAB), small, interpolation=cv2.INTER_AREA
        ).astype(np.float32)
        for form, image in images.items()
    }
    # Only the pixels deep inside the Pokémon are compared, so thin parts blending
    # into the scenery don't count.
    inside = cv2.erode(
        cv2.resize(solid, small, interpolation=cv2.INTER_NEAREST), np.ones((7, 7), np.uint8)
    ) > 0
    stack = np.stack(list(lab.values()))
    spread = np.linalg.norm(stack - np.median(stack, axis=0), axis=3).max(0)
    mask = inside & (spread > 12)
    if int(mask.sum()) < 60:
        mask = inside
    keypoints, descriptors = cv2.SIFT_create().detectAndCompute(
        cv2.cvtColor(base[..., :3], cv2.COLOR_BGR2GRAY), solid * 255
    )
    if descriptors is None or len(keypoints) < 10 or int(mask.sum()) < 60:
        return None
    points = np.float32([keypoint.pt for keypoint in keypoints])
    return lab, mask, points, descriptors, base.shape[:2]


def form_by_pattern(data: bytes, forms: tuple[str, ...]) -> str | None:
    """Tell forms that differ only in colouring apart by lining the spawn up with the reference."""
    references = _pattern_references(forms)
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if cv2 else None
    if references is None or image is None:
        return None
    lab, mask, ref_points, ref_descriptors, (ref_height, ref_width) = references
    scale = MAX_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    best: tuple[int, str] | None = None
    for mirror, upscale in ((False, 1), (True, 1), (False, 2), (True, 2)):
        if best is not None and best[0] >= GOOD_ALIGNMENT and upscale > 1:
            break
        candidate = cv2.flip(image, 1) if mirror else image
        if upscale > 1:
            candidate = cv2.resize(candidate, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        keypoints, descriptors = cv2.SIFT_create(nfeatures=FEATURES_PER_IMAGE * upscale).detectAndCompute(
            cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY), None
        )
        if descriptors is None or len(keypoints) < 10:
            continue
        pairs = cv2.BFMatcher().knnMatch(ref_descriptors, descriptors, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 8:
            continue
        source = np.float32([ref_points[m.queryIdx] for m in good])
        target = np.float32([keypoints[m.trainIdx].pt for m in good])
        # A spawn is the reference scaled and moved, so a similarity fit is steadier.
        matrix, inliers = cv2.estimateAffinePartial2D(
            target, source, method=cv2.RANSAC, ransacReprojThreshold=5.0
        )
        if matrix is None or int(inliers.sum()) < 8:
            continue
        aligned = cv2.warpAffine(
            candidate, matrix, (ref_width, ref_height), flags=cv2.INTER_AREA
        )
        observed = cv2.resize(
            cv2.cvtColor(aligned, cv2.COLOR_BGR2LAB),
            (REFERENCE_PATCH, REFERENCE_PATCH),
            interpolation=cv2.INTER_AREA,
        ).astype(np.float32)
        form = min(
            lab,
            key=lambda f: float(np.median(np.linalg.norm(lab[f][mask] - observed[mask], axis=1))),
        )
        if best is None or int(inliers.sum()) > best[0]:
            best = (int(inliers.sum()), form)
    return best[1] if best else None


def vivillon_form_by_pattern(data: bytes) -> str | None:
    return form_by_pattern(data, VIVILLON_FORMS)


def arceus_form_by_color(data: bytes) -> str | None:
    return form_by_pattern(data, ARCEUS_FORMS)


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
                self.families = [family_name(name) for name in self.names]
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
            "Loaded image bank from %s: %d Pokémon, %d features",
            bank_path.resolve(),
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
        if not results:
            # Busy scenery can hide features; accept a slightly weaker clear winner.
            results = [
                result
                for result in (
                    self._match(data, False, relaxed=True),
                    self._match(data, True, relaxed=True),
                )
                if result is not None
            ]
        if not results:
            return None
        vivillon_form: str | None = None
        vivillon_checked = False
        for candidate, votes in sorted(
            results, key=lambda result: result[1], reverse=True
        ):
            if candidate in VIVILLON_FORM_SET:
                if not vivillon_checked:
                    vivillon_form = vivillon_form_by_pattern(data)
                    vivillon_checked = True
                if vivillon_form is None:
                    continue
                candidate = vivillon_form
            name = candidate
            break
        else:
            return None
        if name in ("Palafin", "Finizen"):
            if has_belly_patch(data) is not True:
                return None
            name = "Palafin"
        if name in SILVALLY_FORMS:
            name = silvally_form_by_color(data) or name
        if name in ARCEUS_FORM_SET:
            name = arceus_form_by_color(data) or name
        return name, votes

    def _match(self, data: bytes, mirror: bool, mask=None, relaxed: bool = False) -> tuple[str, int] | None:
        descriptors = compute_descriptors(data, mirror, mask)
        if descriptors is None or len(descriptors) < 2:
            return None
        votes = np.zeros(len(self.names), int)
        for neighbours in self.matcher.knnMatch(descriptors, k=NEIGHBOURS):
            if len(neighbours) < 2:
                continue
            best_label = int(self.labels[neighbours[0].trainIdx])
            rival = neighbours[1]
            family = self.families[best_label]
            if self.names[best_label] != family or family in INDISTINGUISHABLE_FAMILIES:
                # Variants of one species share features; only outside rivals count.
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
        if self.families[int(order[0])] in INDISTINGUISHABLE_FAMILIES:
            outside = [
                int(votes[i])
                for i in order
                if self.families[int(i)] != self.families[int(order[0])]
            ]
            second = outside[0] if outside else 0
        # Variant pictures (e.g. Unown letters) are plain shapes with few features.
        is_variant = VARIANT_PATTERN.match(name) is not None
        min_votes = SPECIES_MIN_VOTES.get(name, MIN_VOTES)
        min_margin = SPECIES_MIN_MARGIN.get(name, MIN_MARGIN)
        if is_variant:
            min_votes, min_margin = 2, 2
        elif relaxed:
            min_votes, min_margin = (4, 3) if name != "Pumpkaboo" else (99, 99)
        if best >= min_votes and best - second >= max(min_margin, 0.3 * best):
            return DISPLAY_NAMES.get(name, name), best
        return None
