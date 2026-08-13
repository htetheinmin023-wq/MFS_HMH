"""Face Scan: detects faces in an image and draws boxes around them.

When OpenCV is available the scan performs real face detection and draws
a green box around every detected face; a no-face image raises a clear
error. Without OpenCV it falls back to drawing a centered scan frame.

Raises on invalid/missing input; the caller handles the error UI.
Returns the output path on success.
"""

from PIL import Image, ImageDraw

from ._common import (
    HAVE_CV2,
    NO_FACE_MSG,
    cv_to_pil,
    detect_faces,
    load_image,
    pil_to_cv,
    save_image,
)


def face_scan(input_path, output_path):
    img = load_image(input_path)

    if HAVE_CV2:
        import cv2

        bgr = pil_to_cv(img)
        faces = detect_faces(bgr)

        if not faces:
            raise ValueError(NO_FACE_MSG)

        height, width = bgr.shape[:2]
        thickness = max(2, int(min(height, width) * 0.004))

        for (x, y, w, h) in faces:
            cv2.rectangle(bgr, (x, y), (x + w, y + h), (0, 255, 0), thickness)

        save_image(cv_to_pil(bgr), output_path)
        return output_path

    # Fallback (no OpenCV available): draw a centered scan frame.
    draw = ImageDraw.Draw(img)
    width, height = img.size

    draw.rectangle(
        (
            int(width * 0.20),
            int(height * 0.15),
            int(width * 0.80),
            int(height * 0.85),
        ),
        outline=(255, 0, 0),
        width=max(3, int(min(width, height) * 0.01)),
    )

    save_image(img, output_path)
    return output_path
