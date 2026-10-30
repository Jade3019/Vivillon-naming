import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))
    except OSError as error:
        raise ValueError(f"Could not read Pokémon form source file {path}") from error


def format_display_name(species_name: str, form_identifier: str) -> str:
    if not form_identifier:
        return species_name.replace("-", " ")
    form_name = form_identifier.replace("_", " ")
    return f"{form_name} {species_name.replace('-', ' ')}"


def generate_type_aliases(
    data_directory: Path,
    type_ids: set[str],
) -> list[str]:
    pokemon_rows = read_csv(data_directory / "pokemon.csv")
    type_rows = read_csv(data_directory / "pokemon_types.csv")
    form_rows = read_csv(data_directory / "pokemon_forms.csv")
    species_rows = read_csv(data_directory / "pokemon_species.csv")

    type_ids_by_pokemon: dict[str, set[str]] = defaultdict(set)
    for row in type_rows:
        type_ids_by_pokemon[row["pokemon_id"]].add(row["type_id"])
    form_identifiers = {
        row["pokemon_id"]: row["form_identifier"] or ""
        for row in form_rows
    }
    species_by_id = {row["id"]: row["identifier"] for row in species_rows}

    aliases: set[str] = set()
    for pokemon in pokemon_rows:
        if type_ids_by_pokemon[pokemon["id"]] != type_ids:
            continue

        identifier = pokemon["identifier"]
        species_name = species_by_id.get(pokemon["species_id"])
        if species_name is None:
            raise ValueError(
                f"Pokémon {identifier!r} references missing species "
                f"{pokemon['species_id']!r}"
            )
        form_identifier = form_identifiers.get(pokemon["id"], "")
        display_name = format_display_name(species_name, form_identifier)
        aliases.update({identifier, identifier.replace("-", " "), display_name})
        if pokemon.get("is_default") == "1":
            aliases.add(species_name.replace("-", " "))
        if form_identifier:
            aliases.add(f"{species_name.replace('-', ' ')} {form_identifier}")

    return sorted(alias.casefold() for alias in aliases)


def generate_form_catalog(data_directory: Path) -> dict[str, list[dict[str, str]]]:
    pokemon_rows = read_csv(data_directory / "pokemon.csv")
    form_rows = read_csv(data_directory / "pokemon_forms.csv")
    species_rows = read_csv(data_directory / "pokemon_species.csv")

    pokemon_by_id = {row["id"]: row for row in pokemon_rows}
    species_by_id = {row["id"]: row["identifier"] for row in species_rows}
    forms_by_species: dict[str, list[tuple[int, int, dict[str, str]]]] = defaultdict(list)

    for row in form_rows:
        identifier = row["identifier"]
        form_identifier = row["form_identifier"] or ""
        if (
            form_identifier.casefold() == "unknown"
            or identifier.casefold() == "arceus-unknown"
        ):
            continue

        pokemon = pokemon_by_id.get(row["pokemon_id"])
        if pokemon is None:
            raise ValueError(
                f"Pokémon form {identifier!r} references missing Pokémon "
                f"{row['pokemon_id']!r}"
            )
        species_name = species_by_id.get(pokemon["species_id"])
        if species_name is None:
            raise ValueError(
                f"Pokémon form {identifier!r} references missing species "
                f"{pokemon['species_id']!r}"
            )

        form = {
            "identifier": identifier,
            "display_name": format_display_name(species_name, form_identifier),
        }
        forms_by_species[species_name].append(
            (
                int(row["is_default"]),
                int(row["form_order"]),
                form,
            )
        )

    catalog: dict[str, list[dict[str, str]]] = {}
    for species_name, forms in forms_by_species.items():
        if len(forms) < 2:
            continue
        forms.sort(key=lambda entry: (-entry[0], entry[1], entry[2]["identifier"]))
        catalog[species_name] = [form for _, _, form in forms]
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the Pokémon alternate-form catalog."
    )
    parser.add_argument(
        "data_directory",
        type=Path,
        help="Directory containing PokeAPI pokemon.csv, pokemon_forms.csv, "
        "pokemon_species.csv, and pokemon_types.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("pokemon_forms.json"),
        help="Output JSON path (default: pokemon_forms.json beside this script)",
    )
    args = parser.parse_args()

    catalog = generate_form_catalog(args.data_directory)
    single_type_fire = generate_type_aliases(args.data_directory, {"10"})
    single_type_normal = generate_type_aliases(args.data_directory, {"1"})
    single_type_water = generate_type_aliases(args.data_directory, {"11"})
    single_type_electric = generate_type_aliases(args.data_directory, {"13"})
    single_type_grass = generate_type_aliases(args.data_directory, {"12"})
    single_type_ice = generate_type_aliases(args.data_directory, {"15"})
    ice_and_fire = generate_type_aliases(args.data_directory, {"10", "15"})
    ice_and_water = generate_type_aliases(args.data_directory, {"11", "15"})
    ice_and_electric = generate_type_aliases(args.data_directory, {"13", "15"})
    normal_and_ice = generate_type_aliases(args.data_directory, {"1", "15"})
    grass_and_fire = generate_type_aliases(args.data_directory, {"10", "12"})
    grass_and_water = generate_type_aliases(args.data_directory, {"11", "12"})
    grass_and_normal = generate_type_aliases(args.data_directory, {"1", "12"})
    grass_and_electric = generate_type_aliases(args.data_directory, {"12", "13"})
    normal_and_water = generate_type_aliases(args.data_directory, {"1", "11"})
    water_and_fire = generate_type_aliases(args.data_directory, {"10", "11"})
    fire_and_electric = generate_type_aliases(args.data_directory, {"10", "13"})
    electric_and_water = generate_type_aliases(args.data_directory, {"11", "13"})
    electric_and_normal = generate_type_aliases(args.data_directory, {"1", "13"})
    fire_and_normal = generate_type_aliases(args.data_directory, {"1", "10"})
    data = {
        "_source": (
            "PokeAPI CSV: pokemon_forms.csv, pokemon.csv, pokemon_species.csv, "
            "pokemon_types.csv"
        ),
        "_regional_forms_excluded": False,
        "forms": catalog,
        "single_type_fire_aliases": single_type_fire,
        "single_type_normal_aliases": single_type_normal,
        "single_type_water_aliases": single_type_water,
        "single_type_electric_aliases": single_type_electric,
        "single_type_grass_aliases": single_type_grass,
        "single_type_ice_aliases": single_type_ice,
        "ice_and_fire_type_aliases": ice_and_fire,
        "ice_and_water_type_aliases": ice_and_water,
        "ice_and_electric_type_aliases": ice_and_electric,
        "normal_and_ice_type_aliases": normal_and_ice,
        "grass_and_fire_type_aliases": grass_and_fire,
        "grass_and_water_type_aliases": grass_and_water,
        "grass_and_normal_type_aliases": grass_and_normal,
        "grass_and_electric_type_aliases": grass_and_electric,
        "normal_and_water_type_aliases": normal_and_water,
        "water_and_fire_type_aliases": water_and_fire,
        "fire_and_electric_type_aliases": fire_and_electric,
        "electric_and_water_type_aliases": electric_and_water,
        "electric_and_normal_type_aliases": electric_and_normal,
        "fire_and_normal_type_aliases": fire_and_normal,
    }
    try:
        args.output.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise SystemExit(f"Could not write Pokémon form catalog to {args.output}") from error

    total_forms = sum(len(forms) for forms in catalog.values())
    print(
        f"Wrote {total_forms} forms across {len(catalog)} species "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
