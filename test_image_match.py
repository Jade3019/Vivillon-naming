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

    def test_pattern_is_chosen_by_appearance_even_mirrored(self) -> None:
        import cv2

        for form in image_match.VIVILLON_FORMS:
            data = image_match.form_thumbnail_path(form).read_bytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(data), form)
            image = cv2.flip(cv2.imread(str(image_match.form_thumbnail_path(form))), 1)
            mirrored = cv2.imencode(".png", image)[1].tobytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(mirrored), form)


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


if __name__ == "__main__":
    unittest.main()
