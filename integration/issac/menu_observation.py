"""Read only the pinned game's own rendered title/file-selection surface.

Unknown frames and fades authorize no input. File selection
requires both the stable FILE SELECT heading and one clearly highlighted paper.
The native writable-slot check remains the final authority before gameplay.
"""
import base64
import hashlib
import io

from .common import AdmissionError


def recognize_menu(jpeg, signature):
    from PIL import Image, ImageFilter, ImageStat
    if len(jpeg) > 4*1024*1024:
        raise AdmissionError('BOUNDED_NATIVE_MENU_IMAGE_REQUIRED')
    image = Image.open(io.BytesIO(jpeg))
    if image.width < 320 or image.height < 180 or image.width > 4096 or image.height > 4096:
        raise AdmissionError('NATIVE_MENU_IMAGE_SHAPE_REQUIRED')
    image = image.convert('RGB').resize((960, 540))
    heading = signature['file_heading']
    pixels = image.convert('L').crop(heading['rect']).filter(ImageFilter.GaussianBlur(1)).resize(tuple(heading['size'])).tobytes()
    reference = base64.b64decode(heading['luminance_base64'])
    if len(pixels) != len(reference):
        raise AdmissionError('PINNED_MENU_SIGNATURE_SHAPE_REQUIRED')
    heading_error = sum(abs(a-b) for a, b in zip(pixels, reference))/len(pixels)
    levels = [ImageStat.Stat(image.convert('L').crop(rect)).mean[0]
              for rect in signature['file_paper_regions']]
    ordered = sorted(enumerate(levels, start=1), key=lambda row: row[1], reverse=True)
    gap = ordered[0][1]-ordered[1][1]
    title = signature['title_logo']
    sample = image.crop(title['rect']).resize(tuple(title['size']))
    mask = bytes(int(r > 64 and r > g*1.7+12 and r > b*1.7+12) for r, g, b in sample.getdata())
    expected = base64.b64decode(title['red_mask_base64'])
    if len(mask) != len(expected):
        raise AdmissionError('PINNED_MENU_SIGNATURE_SHAPE_REQUIRED')
    union = sum(bool(a or b) for a, b in zip(mask, expected))
    title_iou = sum(bool(a and b) for a, b in zip(mask, expected))/union if union else 0
    intro_errors = []
    for intro in signature['observed_opening_film']:
        intro_pixels = image.convert('L').crop(intro['rect']).filter(ImageFilter.GaussianBlur(2)).resize(tuple(intro['size'])).tobytes()
        intro_reference = base64.b64decode(intro['luminance_base64'])
        if len(intro_pixels) != len(intro_reference):
            raise AdmissionError('PINNED_MENU_SIGNATURE_SHAPE_REQUIRED')
        intro_errors.append(sum(abs(a-b) for a, b in zip(intro_pixels, intro_reference))/len(intro_pixels))
    intro_error = min(intro_errors)
    page, selected = 'unknown', None
    if heading_error <= 6 and gap >= 25:
        page, selected = 'file_select', ordered[0][0]
    elif title_iou >= .8:
        page = 'title'
    elif intro_error <= 8:
        page = 'opening_film'
    return {'page': page, 'selected_file': selected, 'file_heading_error': round(heading_error, 3),
            'selection_brightness_gap': round(gap, 3), 'title_logo_iou': round(title_iou, 4),
            'observed_opening_error': round(intro_error, 3),
            'native_frame_sha256': hashlib.sha256(jpeg).hexdigest()}
