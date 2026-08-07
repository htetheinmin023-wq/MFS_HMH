import cv2

def face_scan():
    try:
        img = cv2.imread("input/face.jpg")

        if img is None:
            print("Image not found")
            return

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 
            "haarcascade_frontalface_default.xml"
        )

        faces = face_cascade.detectMultiScale(
            gray, 
            1.3, 
            5
        )

        print("Faces detected:", len(faces))

        for (x,y,w,h) in faces:
            cv2.rectangle(
                img,
                (x,y),
                (x+w,y+h),
                (255,0,0),
                2
            )

        cv2.imwrite(
            "output/MFS_face_scan.jpg",
            img
        )

        print("Face Scan Done!")

    except Exception as e:
        print("Error:", e)
