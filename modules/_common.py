"""Shared helpers for the MFS HMH face-processing modules."""

import os

from PIL import Image

try:
    import numpy as np
    import cv2

    HAVE_CV2 = True
except Exception:  # pragma: no cover - depends on build environment
    HAVE_CV2 = False

# Working size for detection/blending (keeps processing fast on phones).
MAX_SIDE = 1600
# Enhancement keeps more detail than detection.
MAX_SIDE_ENHANCE = 4096

MISSING_FILE_MSG = "ဖိုင်မတွေ့ပါ။ ထပ်ကြိုးစားကြည့်ပါ။"
INVALID_IMAGE_MSG = "ရွေးထားတဲ့ဖိုင်က ပုံဖိုင်မဟုတ်ပါ (သို့) ပုံပျက်နေပါသည်။"
NO_FACE_MSG = "ပုံထဲမှာ မျက်နှာ မတွေ့ပါ။ အခြားပုံတစ်ပုံ ရွေးကြည့်ပါ။"


def ensure_dir(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def assets_dir():
    """Directory containing the Haar cascade XML files.

    Prefers the packaged location (next to this module), then CWD.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "assets"),
        os.path.join(os.getcwd(), "assets"),
    ]
    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        if os.path.isdir(candidate):
            return candidate
    return candidates[0]


def load_image(path, max_side=MAX_SIDE):
    """Open an image, convert to RGB and downscale it when oversized.

    Raises ValueError with a user-friendly message on failure.
    """
    if not path or not os.path.exists(path):
        raise ValueError(MISSING_FILE_MSG)

    try:
        img = Image.open(path)
        img.load()
    except Exception:
        raise ValueError(INVALID_IMAGE_MSG)

    img = img.convert("RGB")

    width, height = img.size
    if max_side and max(width, height) > max_side:
        scale = max_side / float(max(width, height))
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )
    return img


def save_image(pil_image, output_path, quality=92):
    ensure_dir(output_path)
    pil_image.convert("RGB").save(output_path, "JPEG", quality=quality)


def pil_to_cv(pil_image):
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def cv_to_pil(bgr_image):
    return Image.fromarray(cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB))


# ---------------------------------------------------------------------------
# Face detection
# ---------------------------------------------------------------------------

_cascades = None


def _get_cascades():
    global _cascades
    if _cascades is None:
        _cascades = []

        search_dirs = [assets_dir()]

        # opencv-python ships the XML files in cv2.data.haarcascades.
        try:
            import cv2.data

            search_dirs.append(cv2.data.haarcascades)
        except Exception:
            pass

        for name in (
            "haarcascade_frontalface_default.xml",
            "haarcascade_frontalface_alt2.xml",
        ):
            for directory in search_dirs:
                path = os.path.join(directory, name)

                if os.path.exists(path):
                    cascade = cv2.CascadeClassifier(path)

                    if not cascade.empty():
                        _cascades.append(cascade)
                        break
    return _cascades


def detect_faces(bgr_image):
    """Detect faces in a BGR image.

    Returns a list of (x, y, w, h) tuples, largest faces first,
    with overlapping detections deduplicated.
    """
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    height, width = gray.shape
    min_size = (max(16, int(width * 0.04)), max(16, int(height * 0.04)))

    found = []
    for cascade in _get_cascades():
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=min_size,
        )
        found.extend(tuple(int(value) for value in face) for face in faces)

    # Deduplicate: keep the largest face of every overlap group.
    found.sort(key=lambda f: f[2] * f[3], reverse=True)
    unique = []
    for face in found:
        x, y, w, h = face
        center = (x + w // 2, y + h // 2)
        if any(
            fx <= center[0] <= fx + fw and fy <= center[1] <= fy + fh
            for (fx, fy, fw, fh) in unique
        ):
            continue
        unique.append(face)
    return unique


def largest_face(faces):
    if not faces:
        return None
    return max(faces, key=lambda f: f[2] * f[3])
