"""Match spawn images against reference pictures in pokemon_images/."""

import io
import logging
import re
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # Pillow is optional; the bot falls back to OpenAI.
    Image = None

logger = logging.getLogger(__name__)

HASH_SIZE = 16
MAX_DISTANCE = 12
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def hash_image(data: bytes) -> int | None:
    """Difference hash of an image, or None if it can't be read."""
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            gray = Image.alpha_composite(background, rgba).convert("L")
            small = gray.resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None
    pixels = list(small.getdata())
    bits = 0
    for row in range(HASH_SIZE):
        offset = row * (HASH_SIZE + 1)
        for column in range(HASH_SIZE):
            bits = (bits << 1) | (pixels[offset + column] > pixels[offset + column + 1])
    return bits


def pokemon_name_from_file(path: Path) -> str:
    # "Pikachu 2.png" is a second picture of Pikachu.
    return re.sub(r"(?:[\s_-]+\(?\d+\)?|\s*\(\d+\))$", "", path.stem).strip()


class ImageMatcher:
    def __init__(self, folder: Path) -> None:
        self.entries: list[tuple[int, str]] = []
        if Image is None or not folder.is_dir():
            return
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            name = pokemon_name_from_file(path)
            image_hash = hash_image(path.read_bytes())
            if name and image_hash is not None:
                self.entries.append((image_hash, name))
            else:
                logger.warning("Could not use reference image %s", path.name)
        logger.info("Loaded %d reference Pokémon images", len(self.entries))

    def match(self, data: bytes) -> tuple[str, int] | None:
        """Return (pokemon name, distance) for the closest reference, if close."""
        if not self.entries:
            return None
        image_hash = hash_image(data)
        if image_hash is None:
            return None
        distance, name = min(
            ((image_hash ^ known).bit_count(), name) for known, name in self.entries
        )
        return (name, distance) if distance <= MAX_DISTANCE else None
