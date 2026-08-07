from kivy.app import App
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout

from modules.face_scan import face_scan
from modules.face_enhance import face_enhance
from modules.face_blend import face_blend


class MFSApp(App):

    def build(self):

        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=20
        )

        btn1 = Button(text="1. Face Scan")
        btn2 = Button(text="2. Face Enhance")
        btn3 = Button(text="3. Face Blend")

        btn1.bind(on_press=lambda x: face_scan())
        btn2.bind(on_press=lambda x: face_enhance())
        btn3.bind(on_press=lambda x: face_blend())

        layout.add_widget(btn1)
        layout.add_widget(btn2)
        layout.add_widget(btn3)

        return layout


if __name__ == "__main__":
    MFSApp().run()
