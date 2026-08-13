"""Face Blend: blends two face images.

With OpenCV, when a face is found in both images, the face regions are
aligned and blended; otherwise (or without OpenCV) the two whole images
are alpha-blended 50/50. Both images are converted to RGB and resized to
match, so mixed PNG/JPEG inputs never raise.
Raises on failure; the caller handles the UI.
Returns the output path on success.
"""

from PIL import Image

from ._common import (
    HAVE_CV2,
    cv_to_pil,
    detect_faces,
    largest_face,
    load_image,
    pil_to_cv,
    save_image,
)


def _square_face_crop(bgr_image, face, margin=0.6):
    """Crop a square region around the face, expanded by ``margin``."""
    height, width = bgr_image.shape[:2]
    x, y, w, h = face

    side = int(max(w, h) * (1.0 + 2.0 * margin))
    center_x = x + w // 2
    center_y = y + h // 2

    half = side // 2
    x1 = max(0, center_x - half)
    y1 = max(0, center_y - half)
    x2 = min(width, center_x + half)
    y2 = min(height, center_y + half)
    return bgr_image[y1:y2, x1:x2]


def face_blend(face1_path, face2_path, output_path):
    img1 = load_image(face1_path)
    img2 = load_image(face2_path)

    if HAVE_CV2:
        import cv2

        bgr1 = pil_to_cv(img1)
        bgr2 = pil_to_cv(img2)

        faces1 = detect_faces(bgr1)
        faces2 = detect_faces(bgr2)

        if faces1 and faces2:
            crop1 = _square_face_crop(bgr1, largest_face(faces1))
            crop2 = _square_face_crop(bgr2, largest_face(faces2))
            side = min(crop1.shape[0], crop2.shape[0], crop1.shape[1], crop2.shape[1])
            crop1 = cv2.resize(crop1, (side, side), interpolation=cv2.INTER_LINEAR)
            crop2 = cv2.resize(crop2, (side, side), interpolation=cv2.INTER_LINEAR)
            blended = cv2.addWeighted(crop1, 0.5, crop2, 0.5, 0)
            save_image(cv_to_pil(blended), output_path)
            return output_path

        # No faces found: blend the whole images.
        bgr2 = cv2.resize(bgr2, (bgr1.shape[1], bgr1.shape[0]))
        blended = cv2.addWeighted(bgr1, 0.5, bgr2, 0.5, 0)
        save_image(cv_to_pil(blended), output_path)
        return output_path

    # Fallback (no OpenCV available).
    img2 = img2.resize(img1.size, Image.LANCZOS)
    save_image(Image.blend(img1, img2, 0.5), output_path)
    return output_path
