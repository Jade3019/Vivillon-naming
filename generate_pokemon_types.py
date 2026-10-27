"""Build pokemon_types.json from PokeAPI's pokemon_types.csv and pokemon_sprites.json."""
import argparse
import csv
import json
import re
from pathlib import Path

TYPE_NAMES = {
    1: "normal", 2: "fighting", 3: "flying", 4: "poison", 5: "ground", 6: "rock",
    7: "bug", 8: "ghost", 9: "steel", 10: "fire", 11: "water", 12: "grass",
    13: "electric", 14: "psychic", 15: "ice", 16: "dragon", 17: "dark", 18: "fairy",
}
# Pictures that have no PokeAPI entry of their own.
EXTRA = {
    "DJ Rotom": ["electric", "ghost"],
    "Rotom Drone": ["electric", "ghost"],
    "Rotom Phone": ["electric", "ghost"],
    "Rotom Pokédex": ["electric", "ghost"],
    "Spiky-Eared Pichu": ["electric"],
    "Peakychu": ["electric"],
    "Smearguru": ["normal"],
    "Mosslax": ["normal"],
    "Prof Tangrowth": ["grass"],
    "Chef Dente": ["electric", "fairy"],
    "Cherrim Variant 1": ["grass"],
    "Cherrim Variant 2": ["grass"],
}


def simplify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("types_csv", type=Path)
    parser.add_argument("pokemon_csv", type=Path)
    args = parser.parse_args()
    by_id: dict[int, list[tuple[int, int]]] = {}
    with args.types_csv.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            by_id.setdefault(int(row["pokemon_id"]), []).append(
                (int(row["slot"]), int(row["type_id"]))
            )
    with args.pokemon_csv.open(encoding="utf-8", newline="") as source:
        ids = {row["identifier"]: int(row["id"]) for row in csv.DictReader(source)}
    forms = json.loads(Path("pokemon_forms.json").read_text(encoding="utf-8"))["forms"]
    form_ids = {
        simplify(form["display_name"]): ids[form["identifier"]]
        for entries in forms.values()
        for form in entries
        if form["identifier"] in ids
    }
    sprites = json.loads(Path("pokemon_sprites.json").read_text(encoding="utf-8"))
    result = {}
    for name, dex in sprites.items():
        # The form's own id carries its types (e.g. Heat Rotom), the sprite id may be the base species.
        dex = form_ids.get(simplify(name), dex)
        if dex in by_id:
            result[name] = [TYPE_NAMES[type_id] for _, type_id in sorted(by_id[dex])]
    result.update(EXTRA)
    Path("pokemon_types.json").write_text(
        json.dumps(dict(sorted(result.items())), ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote pokemon_types.json: {len(result)} entries")


if __name__ == "__main__":
    main()
