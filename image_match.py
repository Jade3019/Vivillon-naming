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


def compute_descriptors(data: bytes):
    """SIFT descriptors (float32) of an image, or None if unreadable."""
    if cv2 is None:
        return None
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    scale = MAX_SIDE / max(image.shape)
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sift = cv2.SIFT_create(nfeatures=FEATURES_PER_IMAGE)
    _, descriptors = sift.detectAndCompute(image, None)
    return descriptors


def pokemon_name_from_file(path: Path) -> str:
    return re.sub(r"(?:[\s_-]+\(?\d+\)?|\s*\(\d+\))$", "", path.stem).strip()


def reference_images(folder: Path) -> dict[str, list[Path]]:
    """Group reference pictures by Pokémon (subfolder name or file name)."""
    groups: dict[str, list[Path]] = {}
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES or path.name.startswith("."):
            continue
        if path.parent != folder:
            name = path.parent.relative_to(folder).parts[0].strip()
        else:
            name = pokemon_name_from_file(path)
        if name:
            groups.setdefault(name, []).append(path)
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
        """Return (pokemon name, votes) when one Pokémon clearly wins."""
        if not self.names or self.matcher is None:
            return None
        descriptors = compute_descriptors(data)
        if descriptors is None or len(descriptors) < 2:
            return None
        votes = np.zeros(len(self.names), int)
        for pair in self.matcher.knnMatch(descriptors, k=2):
            if len(pair) == 2 and pair[0].distance < RATIO * pair[1].distance:
                votes[self.labels[pair[0].trainIdx]] += 1
        order = np.argsort(votes)[::-1]
        best = int(votes[order[0]])
        second = int(votes[order[1]]) if len(order) > 1 else 0
        if best >= MIN_VOTES and best - second >= max(MIN_MARGIN, 0.3 * best):
            return self.names[int(order[0])], best
        return None
