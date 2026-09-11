"""Face Swap: transfers the face of the source image onto the target photo.

With OpenCV:
  1. detect the face in the source image,
  2. detect the face in the target image,
  3. keep a proportional amount of context around each face (hair,
     forehead, jaw) so the two regions match in framing,
  4. match the colour/lighting statistics of the source patch to the
     target region (so the face no longer looks "pasted on"),
  5. seamless-clone it onto the target with a soft feathered elliptical
     mask.

Without OpenCV (e.g. the default Android build): a PIL-only fallback
crops the central face region of the source, resizes it onto the target
region, colour-matches it and pastes it with a feathered elliptical mask,
so the feature still works on every device.

Limitation: Haar detection gives bounding boxes only (no landmarks), so
the swap is aligned by bounding box. Results are best when both faces are
roughly frontal and similar in pose.
"""

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from ._common import (
    cv2_usable,
    cv_to_pil,
    detect_faces,
    largest_face,
    load_image,
    pil_to_cv,
    save_image,
)

NO_SOURCE_FACE_MSG = "Source ပုံထဲမှာ မျက်နှာ မတွေ့ပါ။"
NO_TARGET_FACE_MSG = "Target ပုံထဲမှာ မျက်နှာ မတွေ့ပါ။"

# How much context (hair / forehead / jaw) to keep around a face box.
# 0.35 -> the face occupies ~59% of the region, which keeps natural
# framing instead of a tight, obviously-cropped rectangle.
_MARGIN = 0.35

# Ellipse of the blend mask, as a fraction of the region (in region
# coordinates the face box is 1 / (1 + 2 * _MARGIN) ~ 0.59 of the region,
# so slightly more than half of the region must be covered for the face
# to be fully replaced instead of showing through as a ghost).
_MASK_W = 0.31
_MASK_H = 0.36


def _face_region(size, face, margin=_MARGIN):
    """Region around a face box, expanded by ``margin`` and clamped to the
    image so it can always be used as an OpenCV ROI.

    ``size`` is (width, height); ``face`` is (x, y, w, h).
    """
    width, height = size
    x, y, w, h = face
    cx, cy = x + w / 2.0, y + h / 2.0

    rw = min(float(width), w * (1.0 + 2.0 * margin))
    rh = min(float(height), h * (1.0 + 2.0 * margin))

    x1 = int(round(cx - rw / 2.0))
    y1 = int(round(cy - rh / 2.0))
    x1 = max(0, min(int(width - rw), x1))
    y1 = max(0, min(int(height - rh), y1))

    return x1, y1, x1 + max(1, int(rw)), y1 + max(1, int(rh))


def _feathered_face_mask(size, width_ratio=_MASK_W, height_ratio=_MASK_H,
                         blur_ratio=0.06):
    """Soft elliptical mask centred in ``size`` (PIL path)."""
    width, height = size
    mask = Image.new("L", size, 0)

    ex = max(1, int(width * width_ratio))
    ey = max(1, int(height * height_ratio))
    cx, cy = width // 2, height // 2

    ImageDraw.Draw(mask).ellipse(
        (cx - ex, cy - ey, cx + ex, cy + ey), fill=255
    )
    return mask.filter(
        ImageFilter.GaussianBlur(radius=max(3, int(min(size) * blur_ratio)))
    )


def _match_color_pil(patch, region):
    """Shift the colour statistics of ``patch`` toward ``region``.

    A per-channel mean/std transfer: keeps the face's own detail while
    adopting the target's lighting and skin tone, which is what removes
    the "pasted on" look.
    """
    p_mean, p_std = ImageStat.Stat(patch).mean, ImageStat.Stat(patch).stddev
    r_mean, r_std = ImageStat.Stat(region).mean, ImageStat.Stat(region).stddev

    out_bands = []
    for i, band in enumerate(patch.split()):
        src_std = max(p_std[i], 1.0)
        scale = min(1.6, max(0.6, r_std[i] / src_std))
        offset = r_mean[i] - p_mean[i] * scale
        lut = [
            max(0, min(255, int(round(scale * value + offset))))
            for value in range(256)
        ]
        out_bands.append(band.point(lut))

    return Image.merge("RGB", out_bands)


def _match_color_cv2(patch, region):
    """Reinhard-style colour transfer (BGR in, BGR out) using LAB."""
    import cv2
    import numpy as np

    patch_lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).astype(np.float32)
    region_lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)

    for i in range(3):
        src = patch_lab[..., i]
        dst = region_lab[..., i]
        src_std = max(float(src.std()), 1e-3)
        scale = min(1.6, max(0.6, float(dst.std()) / src_std))
        patch_lab[..., i] = (src - float(src.mean())) * scale + float(dst.mean())

    return cv2.cvtColor(
        np.clip(patch_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR
    )


def _swap_fallback(source_path, target_path, output_path):
    """PIL-only swap: centre-crop the source face region, colour-match it
    to the target and paste it with a feathered elliptical mask."""
    source = load_image(source_path)
    target = load_image(target_path)

    sw, sh = source.size
    tw, th = target.size

    s_box = (int(sw * 0.20), int(sh * 0.12), int(sw * 0.80), int(sh * 0.72))
    t_box = (int(tw * 0.20), int(th * 0.12), int(tw * 0.80), int(th * 0.72))

    region = target.crop(t_box)
    face = source.crop(s_box).resize(region.size, Image.LANCZOS)
    face = _match_color_pil(face, region)

    mask = _feathered_face_mask(region.size)

    result = target.copy()
    result.paste(face, (t_box[0], t_box[1]), mask)

    save_image(result, output_path)
    return output_path


def face_swap(source_path, target_path, output_path):
    # cv2_usable() is False when cv2 is absent OR no Haar cascade could be
    # loaded (common on p4a/Android, where cv2.data does not exist and the
    # packaged XMLs can be unreachable). In both cases the swap must still
    # produce an image -> PIL fallback instead of a "no face found"
    # dead-end that makes the feature look broken.
    if not cv2_usable():
        return _swap_fallback(source_path, target_path, output_path)

    try:
        return _swap_cv2(source_path, target_path, output_path)
    except ValueError:
        # Genuine user-facing error (e.g. no face in the photo).
        raise
    except Exception:
        # Any unexpected cv2 failure: degrade gracefully, never crash.
        return _swap_fallback(source_path, target_path, output_path)


def _swap_cv2(source_path, target_path, output_path):
    import cv2
    import numpy as np

    src = pil_to_cv(load_image(source_path))
    dst = pil_to_cv(load_image(target_path))

    src_faces = detect_faces(src)
    dst_faces = detect_faces(dst)

    if not src_faces:
        raise ValueError(NO_SOURCE_FACE_MSG)
    if not dst_faces:
        raise ValueError(NO_TARGET_FACE_MSG)

    src_face = largest_face(src_faces)
    dst_face = largest_face(dst_faces)

    src_h, src_w = src.shape[:2]
    dst_h, dst_w = dst.shape[:2]

    sx1, sy1, sx2, sy2 = _face_region((src_w, src_h), src_face)
    dx1, dy1, dx2, dy2 = _face_region((dst_w, dst_h), dst_face)

    patch = src[sy1:sy2, sx1:sx2]
    region = dst[dy1:dy2, dx1:dx2]

    rw, rh = dx2 - dx1, dy2 - dy1
    if rw < 8 or rh < 8 or patch.size == 0:
        return _swap_fallback(source_path, target_path, output_path)

    # Aspect of the source region is preserved because both regions are
    # derived from a face box with the same relative margin; the resize
    # below is therefore a near-uniform scale.
    patch = cv2.resize(patch, (rw, rh), interpolation=cv2.INTER_LANCZOS4)

    # Adopt the target's lighting / skin tone before blending.
    patch = _match_color_cv2(patch, region)

    # Soft feathered elliptical mask covering the face (not the context).
    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (rw // 2, rh // 2),
        (max(1, int(rw * _MASK_W)), max(1, int(rh * _MASK_H))),
        0,
        0,
        360,
        255,
        -1,
    )
    mask = cv2.GaussianBlur(
        mask, (0, 0), sigmaX=max(2.0, min(rw, rh) * 0.055)
    )

    center = (dx1 + rw // 2, dy1 + rh // 2)
    result = cv2.seamlessClone(patch, dst, mask, center, cv2.NORMAL_CLONE)

    save_image(cv_to_pil(result), output_path)
    return output_path
