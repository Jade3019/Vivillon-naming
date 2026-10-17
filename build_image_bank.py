"""Build image_bank.npz from the pictures in pokemon_images/.

Run this where the pictures are (not on the host):
    python build_image_bank.py [pokemon_images_folder] [output_file]

Per-Pokémon results are cached in .bank_cache/, so after adding or changing a
Pokémon only that one is recomputed.
"""

import hashlib
import sys
from pathlib import Path

import numpy as np

from image_match import (
    BANK_FILE,
    MAX_FEATURES_PER_POKEMON,
    SHARED_DISTANCE,
    compute_descriptors,
    consensus_descriptors,
    drop_duplicates,
    reference_images,
)

import cv2


def signature(paths: list[Path]) -> str:
    digest = hashlib.sha1()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(str(path.stat().st_size).encode())
    return digest.hexdigest()


BACKGROUND_SAMPLE = 120


def background_pool(folder: Path, exclude: set[str]):
    """Raw features of many other Pokémon's pictures, mostly scenery."""
    numbered = sorted(
        path
        for path in folder.rglob("*.png")
        if path.stem.isdigit() and path.parent.name not in exclude
    )
    step = max(1, len(numbered) // BACKGROUND_SAMPLE)
    sets = [
        found
        for found in (compute_descriptors(p.read_bytes()) for p in numbered[::step])
        if found is not None
    ]
    return np.vstack(sets).astype(np.float32)


def foreground_mask(data: bytes):
    """Mask of the Pokémon itself: the alpha channel, else a GrabCut cutout."""
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
    cut = cv2.dilate(cut, np.ones((9, 9), np.uint8))
    return cut if cut.any() else None


def remove_background(descriptors, pool):
    matcher = cv2.BFMatcher()
    keep = np.ones(len(descriptors), bool)
    for position, pair in enumerate(matcher.knnMatch(descriptors, pool, k=1)):
        if pair and pair[0].distance < SHARED_DISTANCE:
            keep[position] = False
    return descriptors[keep]


def pokemon_features(name: str, paths: list[Path], cache: Path, pool=None):
    cache_file = cache / f"{hashlib.sha1(name.encode()).hexdigest()}.npz"
    wanted = signature(paths) + "-fg1"
    if cache_file.is_file():
        with np.load(cache_file) as data:
            if str(data["signature"]) == wanted:
                return data["descriptors"]
    sets = []
    extra = []
    for path in paths:
        data = path.read_bytes()
        found = compute_descriptors(data, mask=None if path.stem.isdigit() else foreground_mask(data))
        if found is None or len(found) < 2:
            continue
        # Hand-added pictures (not the numbered scraped ones) are a different
        # render, so they can't pass the repeat check; keep all their features.
        if path.stem.isdigit():
            sets.append(found)
        else:
            extra.append(remove_background(found, pool) if pool is not None else found)
    parts = ([consensus_descriptors(sets)] if sets else []) + extra
    if not parts:
        return np.zeros((0, 128), np.float32)
    descriptors = drop_duplicates(np.vstack(parts))
    np.savez(cache_file, signature=wanted, descriptors=descriptors)
    return descriptors


def assemble_bank(names: list[str], per_pokemon: dict):
    """Combine per-Pokémon features into (descriptors uint8, labels)."""
    # Features that look the same in other Pokémon are background, so drop them.
    compact = {
        name: descriptors[
            np.linspace(0, len(descriptors) - 1, MAX_FEATURES_PER_POKEMON).astype(int)
        ] if len(descriptors) > MAX_FEATURES_PER_POKEMON else descriptors
        for name, descriptors in list(per_pokemon.items())
    }
    per_pokemon.clear()
    everything = np.vstack(list(compact.values())).astype(np.float32)
    owner = np.concatenate(
        [np.full(len(compact[name]), i) for i, name in enumerate(names)]
    )
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=32))
    matcher.add([everything])
    matcher.train()
    kept_descriptors, kept_labels = [], []
    for index, name in enumerate(names):
        features = compact[name].astype(np.float32)
        if len(features) == 0:
            continue
        keep = np.ones(len(features), bool)
        for position, neighbours in enumerate(matcher.knnMatch(features, k=6)):
            for neighbour in neighbours:
                if owner[neighbour.trainIdx] != index and neighbour.distance < SHARED_DISTANCE:
                    keep[position] = False
                    break
        features = features[keep]
        if len(features) > MAX_FEATURES_PER_POKEMON:
            chosen = np.linspace(0, len(features) - 1, MAX_FEATURES_PER_POKEMON).astype(int)
            features = features[chosen]
        kept_descriptors.append(features)
        kept_labels.append(np.full(len(features), index))

    descriptors = np.vstack(kept_descriptors)
    return (
        np.clip(np.rint(descriptors), 0, 255).astype(np.uint8),
        np.concatenate(kept_labels).astype(np.int32),
    )


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "pokemon_images")
    output = Path(sys.argv[2] if len(sys.argv) > 2 else BANK_FILE)
    cache = Path(".bank_cache")
    cache.mkdir(exist_ok=True)

    groups = reference_images(folder)
    if not groups:
        sys.exit(f"No pictures found in {folder}")
    pool = None
    if any(not path.stem.isdigit() for paths in groups.values() for path in paths):
        print("Building background pool for hand-added pictures...", flush=True)
        pool = background_pool(folder, set())
    names = sorted(groups)
    per_pokemon = {}
    for number, name in enumerate(names, 1):
        per_pokemon[name] = pokemon_features(name, groups[name], cache, pool)
        if number == 1 or number % 25 == 0 or number == len(names):
            print(f"[{number}/{len(names)}] {name}: {len(per_pokemon[name])} features", flush=True)

    descriptors, labels = assemble_bank(names, per_pokemon)
    np.savez_compressed(
        output,
        descriptors=descriptors,
        labels=labels,
        names=np.array(names),
    )
    print(f"Wrote {output}: {len(names)} Pokémon, {len(descriptors)} features")


if __name__ == "__main__":
    main()
