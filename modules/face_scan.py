from PIL import Image, ImageDraw

def face_scan():
    try:
        input_path = "input/face.jpg"
        output_path = "output/MFS_face_scan.jpg"

        img = Image.open(input_path).convert("RGB")

        draw = ImageDraw.Draw(img)

        # Safe scan mode:
        # OpenCV မသုံးဘဲ image ကို scan လုပ်ပြီး
        # အလယ်ပိုင်းမှာ scan box ပြထားမယ်။
        w, h = img.size

        margin_x = int(w * 0.20)
        margin_y = int(h * 0.15)

        x1 = margin_x
        y1 = margin_y
        x2 = w - margin_x
        y2 = h - margin_y

        draw.rectangle(
            (x1, y1, x2, y2),
            outline=(255, 0, 0),
            width=max(3, int(min(w, h) * 0.01))
        )

        img.save(output_path, "JPEG", quality=95)

        print("Face Scan Done!")

    except Exception as e:
        print("Error:", e)
