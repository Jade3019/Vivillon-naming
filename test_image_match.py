import tempfile
import unittest
from pathlib import Path

import image_match
from image_match import ImageMatcher, compute_descriptors


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class ImageMatcherTests(unittest.TestCase):
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
