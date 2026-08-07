from PIL import Image

def face_blend():
    try:
        face1 = Image.open("input/face1.jpg")
        face2 = Image.open("input/face2.jpg")

        face2 = face2.resize(face1.size)

        result = Image.blend(face1, face2, 0.5)


        result.save("output/MFS_blend_result.jpg")

        print("Face Blend Done!")
    except Exception as e:
        print("Error:", e)




