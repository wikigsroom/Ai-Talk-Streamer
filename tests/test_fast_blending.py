"""Pixel compatibility with upstream MuseTalk, including padded crop edges."""
import unittest

import numpy as np
from PIL import Image

from integration.fast_blending import paste_face


def upstream(image, face, face_box, mask_array, crop_box):
    body = Image.fromarray(image[:, :, ::-1])
    face = Image.fromarray(face[:, :, ::-1])
    x, y, x1, y1 = face_box
    xs, ys, xe, ye = crop_box
    face_large = body.crop(crop_box)
    mask_image = Image.fromarray(mask_array).convert('L')
    face_large.paste(face, (x-xs, y-ys, x1-xs, y1-ys))
    body.paste(face_large, crop_box[:2], mask_image)
    return np.array(body)[:, :, ::-1]


class BlendingCompatibility(unittest.TestCase):
    def test_pixels_match_upstream_for_soft_masks_and_boundary_crops(self):
        rng = np.random.default_rng(384)
        image = rng.integers(0, 256, (96, 64, 3), dtype=np.uint8)
        for crop in [(10, 15, 50, 75), (-6, -8, 43, 60), (30, 55, 73, 108), (-5, 10, 70, 80)]:
            xs, ys, xe, ye = crop
            box = (xs+3, ys+4, xs+20, ys+26)
            face = rng.integers(0, 256, (22, 17, 3), dtype=np.uint8)
            for kind in ['zero', 'opaque', 'soft', 'rgb']:
                with self.subTest(crop=crop, mask=kind):
                    shape = (ye-ys, xe-xs)
                    if kind == 'zero': mask = np.zeros(shape, dtype=np.uint8)
                    elif kind == 'opaque': mask = np.full(shape, 255, dtype=np.uint8)
                    else: mask = rng.integers(0, 256, shape+((3,) if kind == 'rgb' else ()), dtype=np.uint8)
                    owned = image.copy()
                    result = paste_face(owned, face, box, mask, crop)
                    self.assertIs(result, owned)
                    self.assertTrue(result.flags.c_contiguous)
                    np.testing.assert_array_equal(result, upstream(image, face, box, mask, crop))


if __name__ == '__main__':
    unittest.main()
