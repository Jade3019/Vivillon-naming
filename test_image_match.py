import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import image_match
from image_match import ImageMatcher, compute_descriptors, reference_images


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class ImageMatcherTests(unittest.TestCase):
    def test_normal_deoxys_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "deoxys-normal" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Deoxys"])

    def test_ordinary_keldeo_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "keldeo-ordinary" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Keldeo"])

    def test_land_shaymin_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "shaymin-land" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Shaymin"])

    def test_rapid_strike_urshifu_reference_uses_spaced_form_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "urshifu-rapid-strike" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Rapid Strike Urshifu"])

    def test_confined_hoopa_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "hoopa" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Hoopa"])

    def test_koraidon_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "Koraidon" / "image.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Koraidon"])

    def test_pumpkaboo_size_and_costume_references_use_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in (
                "Pumpkaboo",
                "pumpkaboo-average",
                "pumpkaboo-small",
                "pumpkaboo-large",
                "pumpkaboo-super",
                "pumpkaboo-autumn",
            ):
                image_path = root / folder / "1.png"
                image_path.parent.mkdir()
                image_path.write_bytes(b"")

            groups = reference_images(root)

        self.assertEqual(list(groups), ["Pumpkaboo"])
        self.assertEqual(len(groups["Pumpkaboo"]), 6)

    def test_power_construct_zygarde_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "zygarde-10-power-construct" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Zygarde"])

    def test_incarnate_tornadus_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "tornadus-incarnate" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Tornadus"])

    def test_paldean_tauros_match_is_reported_as_tauros(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(5).integers(0, 256, (256, 256), dtype=np.uint8)
        descriptors = compute_descriptors(cv2.imencode(".png", image)[1].tobytes())

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Paldean Tauros"]),
            )
            result = ImageMatcher(bank_path).match(cv2.imencode(".png", image)[1].tobytes())

        self.assertEqual(result[0], "Tauros")

    def test_mimikyu_and_morpeko_forms_are_reported_by_species_name(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(6).integers(0, 256, (256, 256), dtype=np.uint8)
        encoded = cv2.imencode(".png", image)[1].tobytes()
        descriptors = compute_descriptors(encoded)

        for form_name in (
            "Busted Mimikyu",
            "Disguised Mimikyu",
            "Totem-Busted Mimikyu",
            "Totem-Disguised Mimikyu",
            "Full-Belly Morpeko",
        ):
            with self.subTest(form_name=form_name), tempfile.TemporaryDirectory() as directory:
                bank_path = Path(directory) / "image_bank.npz"
                np.savez(
                    bank_path,
                    descriptors=descriptors,
                    labels=np.zeros(len(descriptors), dtype=np.int32),
                    names=np.array([form_name]),
                )
                result = ImageMatcher(bank_path).match(encoded)

            self.assertEqual(result[0], form_name.split()[-1])

    def test_matches_reference_when_spawn_image_is_flipped(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(17).integers(0, 256, (256, 256), dtype=np.uint8)
        encoded = cv2.imencode(".png", image)[1].tobytes()
        flipped = cv2.imencode(".png", cv2.flip(image, 1))[1].tobytes()
        descriptors = compute_descriptors(encoded)
        self.assertIsNotNone(descriptors)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Pikachu"]),
            )
            matcher = ImageMatcher(bank_path)

            result = matcher.match(flipped)
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "Pikachu")

    def test_foreground_retry_cannot_reclassify_boldore_or_milcery(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(23).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Milcery", "Boldore"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(
                    matcher,
                    "_match",
                    side_effect=[("Milcery", 46), None],
                ),
                patch("image_match.foreground_mask") as mask,
            ):
                result = matcher.match(b"spawn image")

        self.assertEqual(result, ("Milcery", 46))
        mask.assert_not_called()

    def test_palafin_finizen_match_requires_a_detected_belly_patch(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(24).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Finizen", "Palafin"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(
                    matcher,
                    "_match",
                    side_effect=[("Finizen", 20), ("Finizen", 18)],
                ),
                patch("image_match.has_belly_patch", return_value=False),
            ):
                result = matcher.match(b"ambiguous spawn image")

        self.assertIsNone(result)

    def test_vivillon_match_requires_a_valid_pattern_alignment(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(24).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Vivillon"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(matcher, "_match", side_effect=[("Vivillon", 20), None]),
                patch("image_match.vivillon_form_by_pattern", return_value=None),
            ):
                result = matcher.match(b"unrelated spawn image")

        self.assertIsNone(result)

    def test_invalid_vivillon_match_does_not_hide_a_second_species_match(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(25).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Vivillon", "Milcery"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(
                    matcher,
                    "_match",
                    side_effect=[("Vivillon", 20), ("Milcery", 16)],
                ),
                patch("image_match.vivillon_form_by_pattern", return_value=None),
            ):
                result = matcher.match(b"milcery spawn image")

        self.assertEqual(result, ("Milcery", 16))


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class SilvallyTests(unittest.TestCase):
    def test_folders_keep_their_type_names(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.SILVALLY_FORMS:
            self.assertIn(form, groups)

    def test_type_forms_are_reported_as_silvally(self) -> None:
        self.assertEqual(image_match.species_display_name("Bug Silvally"), "Silvally")
        self.assertEqual(image_match.family_name("Fairy Silvally"), "Silvally")

    def test_type_is_chosen_by_colour(self) -> None:
        for form in ("Silvally", "Bug Silvally", "Fire Silvally", "Water Silvally"):
            path = image_match.silvally_thumbnail_path(form)
            self.assertEqual(
                image_match.silvally_form_by_color(path.read_bytes()), form
            )


class VivillonTests(unittest.TestCase):
    def test_every_pattern_has_a_folder_and_thumbnail(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.VIVILLON_FORMS:
            self.assertIn(form, groups)
            self.assertTrue(image_match.form_thumbnail_path(form).is_file(), form)

    def test_patterns_are_reported_as_vivillon(self) -> None:
        self.assertEqual(image_match.species_display_name("Polar Vivillon"), "Vivillon")
        self.assertEqual(image_match.family_name("Fancy Vivillon"), "Vivillon")

    def test_custom_reference_forms_resolve_to_their_species(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        forms = {
            "Partner Pikachu": "Pikachu",
            "Gliding Build Koraidon": "Koraidon",
            "Zenith Marshadow": "Marshadow",
            "Galarian Zen Darmanitan": "Darmanitan",
            "Zygarde Cell": "Zygarde",
            "Combat Breed Tauros": "Tauros",
        }
        for form, species in forms.items():
            with self.subTest(form=form):
                self.assertIn(form, groups)
                self.assertEqual(image_match.species_display_name(form), species)
                self.assertEqual(image_match.family_name(form), species)

    def test_pattern_is_chosen_by_appearance_even_mirrored(self) -> None:
        import cv2

        for form in image_match.VIVILLON_FORMS:
            data = image_match.form_thumbnail_path(form).read_bytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(data), form)
            image = cv2.flip(cv2.imread(str(image_match.form_thumbnail_path(form))), 1)
            mirrored = cv2.imencode(".png", image)[1].tobytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(mirrored), form)


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class CustomFormRecognitionTests(unittest.TestCase):
    def test_supplied_form_images_match_their_named_forms(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        forms = (
            "Partner Pikachu",
            "Gliding Build Koraidon",
            "Zenith Marshadow",
            "Galarian Zen Darmanitan",
            "Zygarde Cell",
            "Combat Breed Tauros",
        )
        for form in forms:
            with self.subTest(form=form):
                image_path = (
                    Path(__file__).with_name("pokemon_images")
                    / form
                    / "image.png"
                )
                result = matcher.match(image_path.read_bytes())

                self.assertIsNotNone(result)
                self.assertEqual(result[0], form)

    def test_all_vivillon_forms_match_their_reference_images(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.VIVILLON_FORMS:
            with self.subTest(form=form):
                result = matcher.match(groups[form][0].read_bytes())

                self.assertIsNotNone(result)
                self.assertEqual(result[0], form)

    def test_zygarde_cell_matches_when_rendered_in_a_scene(self) -> None:
        import cv2
        import numpy as np

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Zygarde Cell"
            / "image.png"
        )
        source = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        canvas = np.full((420, 420, 3), (70, 105, 45), dtype=np.uint8)
        pokemon = cv2.resize(source, (250, 250))
        alpha = pokemon[..., 3:4] / 255.0
        region = canvas[85:335, 85:335]
        canvas[85:335, 85:335] = (
            pokemon[..., :3] * alpha + region * (1 - alpha)
        ).astype(np.uint8)
        data = cv2.imencode(".png", canvas)[1].tobytes()

        result = matcher.match(data)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Zygarde Cell")


class ArceusTests(unittest.TestCase):
    def test_every_type_has_a_folder_and_thumbnail(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.ARCEUS_FORMS:
            self.assertIn(form, groups)
            self.assertTrue(image_match.form_thumbnail_path(form).is_file(), form)

    def test_types_are_reported_as_arceus(self) -> None:
        self.assertEqual(image_match.species_display_name("Fire Arceus"), "Arceus")
        self.assertEqual(image_match.family_name("Fairy Arceus"), "Arceus")

    def test_type_is_chosen_by_colour_even_mirrored(self) -> None:
        import cv2

        for form in image_match.ARCEUS_FORMS:
            path = image_match.form_thumbnail_path(form)
            self.assertEqual(image_match.arceus_form_by_color(path.read_bytes()), form)
            mirrored = cv2.imencode(".png", cv2.flip(cv2.imread(str(path)), 1))[1].tobytes()
            self.assertEqual(image_match.arceus_form_by_color(mirrored), form)


class RotomTests(unittest.TestCase):
    FORMS = (
        "Rotom", "Heat Rotom", "Wash Rotom", "Frost Rotom", "Fan Rotom", "Mow Rotom",
        "DJ Rotom", "Rotom Pokédex", "Rotom Phone", "Rotom Drone",
    )

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)


class DeoxysTests(unittest.TestCase):
    FORMS = ("Deoxys", "Attack Deoxys", "Defense Deoxys", "Speed Deoxys")

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)

    def test_each_form_is_recognised_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for form in self.FORMS:
            folder = Path(__file__).with_name("pokemon_images") / form
            for name in ("image.png", "image_mirrored.png"):
                img = cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
                bg = cv2.resize(img[..., :3], (500, 400)) // 2 + 60
                x, y = 60, 20
                roi = bg[y:y + 360, x:x + 360]
                small = cv2.resize(img, (360, 360))
                al = small[..., 3:4] / 255.0
                bg[y:y + 360, x:x + 360] = (small[..., :3] * al + roi * (1 - al)).astype(bg.dtype)
                ok, buf = cv2.imencode(".png", bg)
                self.assertEqual(matcher.match(buf.tobytes())[0], form, name)


class PichuTests(unittest.TestCase):
    FORMS = ("Pichu", "Spiky-Eared Pichu")

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)

    def test_each_form_is_recognised_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for form in self.FORMS:
            folder = Path(__file__).with_name("pokemon_images") / form
            for name in ("image.png", "image_mirrored.png"):
                img = cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
                bg = cv2.resize(img[..., :3], (500, 400)) // 2 + 60
                x, y = 60, 20
                roi = bg[y:y + 360, x:x + 360]
                small = cv2.resize(img, (360, 360))
                al = small[..., 3:4] / 255.0
                bg[y:y + 360, x:x + 360] = (small[..., :3] * al + roi * (1 - al)).astype(bg.dtype)
                ok, buf = cv2.imencode(".png", bg)
                self.assertEqual(matcher.match(buf.tobytes())[0], form, name)


if __name__ == "__main__":
    unittest.main()
