import argparse
import csv
import json
from pathlib import Path


EGG_GROUP_NAMES = {
    1: "Monster",
    2: "Water 1",
    3: "Bug",
    4: "Flying",
    5: "Field",
    6: "Fairy",
    7: "Grass",
    8: "Human-Like",
    9: "Water 3",
    10: "Mineral",
    11: "Amorphous",
    12: "Water 2",
    13: "Ditto",
    14: "Dragon",
    15: "Undiscovered",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build egg_groups.json from PokeAPI CSV files."
    )
    parser.add_argument("data_directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("egg_groups.json"))
    args = parser.parse_args()

    with (args.data_directory / "pokemon_species.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        identifiers = {row["id"]: row["identifier"] for row in csv.DictReader(source)}
    species: dict[str, list[int]] = {}
    with (args.data_directory / "pokemon_egg_groups.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        for row in csv.DictReader(source):
            key = identifiers[row["species_id"]].replace("-", "")
            species.setdefault(key, []).append(int(row["egg_group_id"]))
    payload = {
        "groups": {str(key): value for key, value in EGG_GROUP_NAMES.items()},
        "species": species,
    }
    args.output.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
