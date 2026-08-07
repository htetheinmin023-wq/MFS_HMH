from PIL import Image, ImageEnhance

def face_enhance():
    try:
        img = Image.open("input/face.jpg")

        enhance = ImageEnhance.Sharpness(img)
        img = enhance.enhance(2)

        enhance = ImageEnhance.Contrast(img)
        img = enhance.enhance(1.5)

        img.save("output/MFS_face_enhanced.jpg")

        print("Face Enhance Done!")

    except Exception as e:
        print("Error:", e)
