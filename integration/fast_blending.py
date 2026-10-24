"""Apply MuseTalk's original Pillow blend to the face crop only.

The caller supplies an owned, writable BGR frame. Keeping the original Pillow
paste/composite arithmetic preserves the upstream pixels without converting the
entire portrait frame to RGB and back for each generated face.
"""
import numpy as np
from PIL import Image


def paste_face(image, face, face_box, mask_array, crop_box):
    x, y, x1, y1 = face_box
    xs, ys, xe, ye = crop_box
    height, width = image.shape[:2]
    left, top, right, bottom = max(0, xs), max(0, ys), min(width, xe), min(height, ye)
    # Pillow.crop pads regions outside the original image with black pixels.
    background = Image.new('RGB', (xe-xs, ye-ys))
    if right > left and bottom > top:
        visible = Image.fromarray(image[top:bottom, left:right, ::-1])
        background.paste(visible, (left-xs, top-ys))
    foreground = background.copy()
    foreground.paste(Image.fromarray(face[:, :, ::-1]), (x-xs, y-ys, x1-xs, y1-ys))
    mask = Image.fromarray(mask_array).convert('L')
    blended = Image.composite(foreground, background, mask)
    if right > left and bottom > top:
        pixels = np.asarray(blended)
        image[top:bottom, left:right] = pixels[top-ys:bottom-ys, left-xs:right-xs, ::-1]
    return image
