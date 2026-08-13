"""Face Enhance: sharpen + boost contrast / colour / brightness.

Converts to RGB first so PNG (RGBA) inputs never crash when saved as
JPEG, and downscales extremely large images to protect phone memory.
Raises on failure; the caller handles the UI.
Returns the output path on success.
"""

from PIL import ImageEnhance

from ._common import MAX_SIDE_ENHANCE, load_image, save_image


def face_enhance(input_path, output_path):
    img = load_image(input_path, max_side=MAX_SIDE_ENHANCE)

    img = ImageEnhance.Sharpness(img).enhance(1.8)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.15)
    img = ImageEnhance.Brightness(img).enhance(1.05)

    save_image(img, output_path)
    return output_path
