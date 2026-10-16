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


def pokemon_features(name: str, paths: list[Path], cache: Path):
    cache_file = cache / f"{hashlib.sha1(name.encode()).hexdigest()}.npz"
    wanted = signature(paths)
    if cache_file.is_file():
        with np.load(cache_file) as data:
            if str(data["signature"]) == wanted:
                return data["descriptors"]
    sets = [
        descriptors
        for descriptors in (compute_descriptors(path.read_bytes()) for path in paths)
        if descriptors is not None and len(descriptors) >= 2
    ]
    if not sets:
        return np.zeros((0, 128), np.float32)
    descriptors = drop_duplicates(consensus_descriptors(sets))
    np.savez(cache_file, signature=wanted, descriptors=descriptors)
    return descriptors


def assemble_bank(names: list[str], per_pokemon: dict):
    """Combine per-Pokémon features into (descriptors uint8, labels)."""
    # Features that look the same in other Pokémon are background, so drop them.
    everything = np.vstack(list(per_pokemon.values())).astype(np.float32)
    owner = np.concatenate(
        [np.full(len(per_pokemon[name]), i) for i, name in enumerate(names)]
    )
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=32))
    matcher.add([everything])
    matcher.train()
    kept_descriptors, kept_labels = [], []
    for index, name in enumerate(names):
        features = per_pokemon[name].astype(np.float32)
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
    names = sorted(groups)
    per_pokemon = {}
    for number, name in enumerate(names, 1):
        per_pokemon[name] = pokemon_features(name, groups[name], cache)
        print(f"[{number}/{len(names)}] {name}: {len(per_pokemon[name])} features")

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
