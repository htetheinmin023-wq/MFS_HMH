"""Face Swap: transfers the face of the source image onto the target photo.

With OpenCV:
  1. detect the face in the source image,
  2. detect the face in the target image,
  3. fit the source face onto the target face region with a feathered
     elliptical mask,
  4. seamless-clone it onto the target so colours blend naturally.

Without OpenCV (e.g. the default Android build): a PIL-only fallback
crops the central face region of the source, resizes it onto the target
face region and pastes it with a feathered elliptical mask, so the
feature still works on every device.

Limitation: Haar detection gives bounding boxes only (no landmarks), so
the swapped face is aligned by bounding box. Results are best when both
faces are roughly frontal and similar in size.
"""

from PIL import Image, ImageDraw, ImageFilter

from ._common import (
    HAVE_CV2,
    cv_to_pil,
    detect_faces,
    largest_face,
    load_image,
    pil_to_cv,
    save_image,
)

NO_SOURCE_FACE_MSG = "Source ပုံထဲမှာ မျက်နှာ မတွေ့ပါ။"
NO_TARGET_FACE_MSG = "Target ပုံထဲမှာ မျက်နှာ မတွေ့ပါ။"


def _swap_fallback(source_path, target_path, output_path):
    """PIL-only swap: center-crop the source face region and paste it
    onto the target with a feathered elliptical mask."""
    source = load_image(source_path)
    target = load_image(target_path)

    sw, sh = source.size
    tw, th = target.size

    # Face region: centered box (55% width, 55% height).
    sx1 = int(sw * 0.225)
    sy1 = int(sh * 0.15)
    sx2 = int(sw * 0.775)
    sy2 = int(sh * 0.70)

    tx1 = int(tw * 0.225)
    ty1 = int(th * 0.15)
    tx2 = int(tw * 0.775)
    ty2 = int(th * 0.70)

    face = source.crop((sx1, sy1, sx2, sy2))
    face = face.resize((tx2 - tx1, ty2 - ty1), Image.LANCZOS)

    mask = Image.new("L", face.size, 0)
    ImageDraw.Draw(mask).ellipse(
        (0, 0, face.size[0], face.size[1]), fill=255
    )
    mask = mask.filter(
        ImageFilter.GaussianBlur(
            radius=max(2, face.size[0] * 0.08)
        )
    )

    result = target.copy()
    result.paste(face, (tx1, ty1), mask)

    save_image(result, output_path)
    return output_path


def face_swap(source_path, target_path, output_path):
    if not HAVE_CV2:
        return _swap_fallback(source_path, target_path, output_path)

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

    sx, sy, sw, sh = largest_face(src_faces)
    dx, dy, dw, dh = largest_face(dst_faces)

    # Expand the source crop a little around the face.
    margin = 0.15
    src_y1 = max(0, int(sy - sh * margin))
    src_y2 = min(src.shape[0], int(sy + sh * (1.0 + margin)))
    src_x1 = max(0, int(sx - sw * margin))
    src_x2 = min(src.shape[1], int(sx + sw * (1.0 + margin)))
    src_face = src[src_y1:src_y2, src_x1:src_x2]

    # Fit the source face onto the target face region.
    src_face = cv2.resize(src_face, (dw, dh), interpolation=cv2.INTER_LINEAR)

    # Feathered elliptical mask.
    mask = np.zeros((dh, dw), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (dw // 2, dh // 2),
        (max(1, int(dw * 0.48)), max(1, int(dh * 0.48))),
        0,
        0,
        360,
        255,
        -1,
    )
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(2.0, dw / 60.0))

    center = (dx + dw // 2, dy + dh // 2)
    result = cv2.seamlessClone(src_face, dst, mask, center, cv2.NORMAL_CLONE)

    save_image(cv_to_pil(result), output_path)
    return output_path
