"""Face Kiss: combines two face photos into a kiss-style montage.

Both faces are cropped (Haar detection when OpenCV is available, a
centred face-region estimate otherwise), resized to the same height,
rotated towards each other and composited side-by-side with a feathered
overlap on a soft romantic background, finished with heart accents.

The module is pure PIL so the feature works in the default Android
build (no numpy/opencv). It never raises for a missing face: when
detection is unavailable or finds nothing, the centred face-region
estimate is used, so the feature always produces an image.

Raises on load/save failure; the caller handles the UI.
Returns the output path on success.
"""

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ._common import (
    HAVE_CV2,
    detect_faces,
    largest_face,
    load_image,
    pil_to_cv,
    save_image,
)

# Tilt of each face towards the middle of the canvas, in degrees.
KISS_ANGLE = 12
# Fraction of the narrower face width that overlaps at the seam.
OVERLAP_FRACTION = 0.16
# Target face-crop height (px) before rotation.
FACE_HEIGHT = 620

# Soft romantic gradient (top -> bottom).
_BG_TOP = (255, 238, 243)
_BG_BOTTOM = (255, 185, 205)
# Heart colour (semi-transparent rose).
_HEART = (235, 52, 110, 235)


def _face_box_pil(img):
    """Centred face-region estimate (x1, y1, x2, y2) when no detection."""
    width, height = img.size
    return (
        int(width * 0.225),
        int(height * 0.15),
        int(width * 0.775),
        int(height * 0.70),
    )


def _face_box(img):
    """Bounding box of the largest detected face (with a small margin),
    falling back to the centred estimate when cv2 is unavailable or no
    face is found."""
    if HAVE_CV2:
        try:
            import cv2

            bgr = pil_to_cv(img)
            faces = detect_faces(bgr)

            if faces:
                x, y, w, h = largest_face(faces)
                x1 = max(0, int(x - w * 0.18))
                y1 = max(0, int(y - h * 0.10))
                x2 = min(img.width, int(x + w * 1.18))
                y2 = min(img.height, int(y + h * 1.12))
                return (x1, y1, x2, y2)
        except Exception:
            pass  # any cv2 hiccup -> centred estimate below

    return _face_box_pil(img)


def _vertical_gradient(size, top, bottom):
    """Solid vertical gradient RGBA image."""
    width, height = size
    ramp = Image.new("RGBA", (1, height))
    draw = ImageDraw.Draw(ramp)

    for y in range(height):
        t = y / max(1, height - 1)
        draw.point(
            (0, y),
            (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
                255,
            ),
        )
    return ramp.resize((width, height))


def _heart_points(size):
    """Sampled points of the classic heart curve, scaled to ``size`` wide."""
    scale = size / 34.0
    points = []
    for step in range(0, 360, 4):
        t = math.radians(step)
        x = 16 * math.sin(t) ** 3
        y = (
            13 * math.cos(t)
            - 5 * math.cos(2 * t)
            - 2 * math.cos(3 * t)
            - math.cos(4 * t)
        )
        points.append((x * scale, -y * scale))
    return points


def _draw_heart(canvas, cx, cy, size):
    """Draw a filled heart centred at (cx, cy) on an RGBA canvas."""
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.polygon(
        [(cx + x, cy + y) for (x, y) in _heart_points(size)],
        fill=_HEART,
    )
    canvas.alpha_composite(overlay)


def _feather_edges(face):
    """Dissolve a crop's edges with an elliptical feathered alpha mask so
    the original photo background fades out instead of showing as hard
    rectangular cards on the pink canvas."""
    width, height = face.size
    mask = Image.new("L", face.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (
            int(width * 0.03),
            int(height * 0.04),
            int(width * 0.97),
            int(height * 0.96),
        ),
        fill=255,
    )
    mask = mask.filter(
        ImageFilter.GaussianBlur(
            radius=max(8, int(min(width, height) * 0.10))
        )
    )
    face = face.convert("RGBA")
    face.putalpha(ImageChops.multiply(face.getchannel("A"), mask))
    return face


def _fade_mask(right_face, overlap):
    """Alpha mask that fades the right face in across the overlap strip,
    preserving the transparency left by its rotation."""
    full = Image.new("L", right_face.size, 255)
    if overlap > 0:
        width = min(overlap, right_face.width)
        grad = Image.new("L", (width, right_face.height))
        draw = ImageDraw.Draw(grad)

        for x in range(width):
            value = int(255 * x / max(1, width - 1))
            draw.line([(x, 0), (x, right_face.height)], fill=value)

        full.paste(grad, (0, 0))

    alpha = ImageChops.multiply(right_face.getchannel("A"), full)
    return alpha


def face_kiss(face1_path, face2_path, output_path):
    """Build a kiss montage from two face photos."""
    img1 = load_image(face1_path)
    img2 = load_image(face2_path)

    crop1 = img1.crop(_face_box(img1))
    crop2 = img2.crop(_face_box(img2))

    # Same visual height so both heads read at one scale.
    crop1 = crop1.resize(
        (
            max(1, int(crop1.width * FACE_HEIGHT / crop1.height)),
            FACE_HEIGHT,
        ),
        Image.LANCZOS,
    )
    crop2 = crop2.resize(
        (
            max(1, int(crop2.width * FACE_HEIGHT / crop2.height)),
            FACE_HEIGHT,
        ),
        Image.LANCZOS,
    )

    # Tilt towards each other: the left face leans right (clockwise in
    # PIL terms = negative), the right face leans left (positive).
    # Edges are feathered first so the crop dissolves into the canvas,
    # and expand=True + RGBA keeps the corners transparent.
    left = _feather_edges(crop1).rotate(
        -KISS_ANGLE, expand=True, resample=Image.BICUBIC
    )
    right = _feather_edges(crop2).rotate(
        KISS_ANGLE, expand=True, resample=Image.BICUBIC
    )

    overlap = int(min(left.width, right.width) * OVERLAP_FRACTION)
    side_pad = int(FACE_HEIGHT * 0.16)
    pad_top = int(FACE_HEIGHT * 0.06)
    pad_bottom = int(FACE_HEIGHT * 0.20)

    max_height = max(left.height, right.height)
    width = side_pad + left.width + right.width - overlap + side_pad
    height = pad_top + max_height + pad_bottom

    canvas = _vertical_gradient((width, height), _BG_TOP, _BG_BOTTOM)

    # Vertically centre each face in the tallest face's footprint.
    left_y = pad_top + (max_height - left.height) // 2
    right_y = pad_top + (max_height - right.height) // 2

    left_x = side_pad
    right_x = side_pad + left.width - overlap

    canvas.alpha_composite(left, (left_x, left_y))

    right.putalpha(_fade_mask(right, overlap))
    canvas.alpha_composite(right, (right_x, right_y))

    # Hearts floating at the seam, around mouth height.
    seam_x = left_x + left.width - overlap // 2
    heart_y = pad_top + int(max_height * 0.55)
    _draw_heart(canvas, seam_x, heart_y, int(FACE_HEIGHT * 0.30))
    _draw_heart(
        canvas,
        seam_x + int(FACE_HEIGHT * 0.26),
        heart_y + int(FACE_HEIGHT * 0.26),
        int(FACE_HEIGHT * 0.13),
    )

    save_image(canvas.convert("RGB"), output_path)
    return output_path
