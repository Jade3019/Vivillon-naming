import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
