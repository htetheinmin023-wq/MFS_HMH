from kivy.app import App
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.popup import Popup
from kivy.uix.image import Image
from kivy.uix.widget import Widget
import os
import shutil


class ImagePicker(BoxLayout):
    def __init__(self, title, callback, multi=False, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.title = title
        self.callback = callback
        self.multi = multi
        self.chooser = FileChooserIconView(
            filters=["*.jpg", "*.jpeg", "*.png", "*.webp"],
            multiselect=multi,
        )
        self.add_widget(self.chooser)

    def open(self):
        self.popup = Popup(
            title=self.title,
            content=self,
            size_hint=(0.95, 0.9),
        )
        self.popup.open()

    def select(self):
        try:
            paths = list(self.chooser.selection)
            if not paths:
                return
            os.makedirs("input", exist_ok=True)
            copied = []
            for path in paths:
                name = os.path.basename(path)
                dest = os.path.join("input", name)
                shutil.copy2(path, dest)
                copied.append(dest)
            self.popup.dismiss()
            self.callback(copied)
        except Exception as e:
            App.get_running_app().show_error(
                "Image selection failed:\\n" + str(e)
            )

class AIChat(BoxLayout):

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            spacing=8,
            padding=10,
            **kwargs
        )

        self.chat = Label(
            text="HMH AI\n\nမင်္ဂလာပါ။ ဘာမေးချင်လဲ?",
            size_hint_y=None,
            halign="left",
            valign="top"
        )

        self.chat.bind(
            texture_size=self.chat.setter("size")
        )

        scroll = ScrollView()
        scroll.add_widget(self.chat)
        self.add_widget(scroll)

        self.input_box = TextInput(
            hint_text="Ask anything...",
            multiline=True,
            size_hint_y=None,
            height=100
        )

        self.add_widget(self.input_box)

        buttons = BoxLayout(
            size_hint_y=None,
            height=55,
            spacing=5
        )

        send = Button(text="Send")
        back = Button(text="Back")

        send.bind(on_press=self.send_message)
        back.bind(
            on_press=lambda x:
            App.get_running_app().show_menu()
        )

        buttons.add_widget(send)
        buttons.add_widget(back)

        self.add_widget(buttons)

    def send_message(self, instance):

        message = self.input_box.text.strip()

        if not message:
            return

        self.chat.text += (
            f"\n\nYou: {message}"
            "\n\nHMH AI: Demo Mode"
        )

        self.input_box.text = ""


class MFSApp(App):

    def build(self):

        os.makedirs("input", exist_ok=True)
        os.makedirs("output", exist_ok=True)

        self.show_menu()

        return self.root

    def show_menu(self):

        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=20
        )

        title = Label(
            text="MFS HMH",
            font_size=28,
            size_hint_y=None,
            height=60
        )

        layout.add_widget(title)

        btn1 = Button(text="1. Face Scan")
        btn2 = Button(text="2. Face Enhance")
        btn3 = Button(text="3. Face Blend")
        btn4 = Button(text="4. Face Swap")
        btn5 = Button(text="5. HMH AI Chat")

        btn1.bind(
            on_press=lambda x:
            self.choose_scan_image()
        )

        btn2.bind(
            on_press=lambda x:
            self.choose_enhance_image()
        )

        btn3.bind(
            on_press=lambda x:
            self.choose_blend_images()
        )

        btn4.bind(
            on_press=lambda x:
            self.choose_swap_images()
        )

        btn5.bind(
            on_press=lambda x:
            self.show_ai_chat()
        )

        layout.add_widget(btn1)
        layout.add_widget(btn2)
        layout.add_widget(btn3)
        layout.add_widget(btn4)
        layout.add_widget(btn5)

        if self.root is None:
            self.root = layout
        else:
            self.root.clear_widgets()
            self.root.add_widget(layout)

    def choose_scan_image(self):

        picker = ImagePicker(
            "Select Face Image",
            self.scan_selected
        )

        picker.open()

    def scan_selected(self, paths):

        try:

            shutil.copy(
                paths[0],
                "input/face.jpg"
            )

            from modules.face_scan import face_scan

            face_scan()

            self.show_result(
                "output/MFS_face_scan.jpg",
                "Face Scan Result"
            )

        except Exception as e:

            self.show_error(str(e))

    def choose_enhance_image(self):

        picker = ImagePicker(
            "Select Image",
            self.enhance_selected
        )

        picker.open()

    def enhance_selected(self, paths):

        try:

            shutil.copy(
                paths[0],
                "input/face.jpg"
            )

            from modules.face_enhance import face_enhance

            face_enhance()

            self.show_result(
                "output/MFS_face_enhanced.jpg",
                "Face Enhance Result"
            )

        except Exception as e:

            self.show_error(str(e))

    def choose_blend_images(self):

        picker = ImagePicker(
            "Select 2 Images",
            self.blend_selected,
            multi=True
        )

        picker.open()

    def blend_selected(self, paths):

        if len(paths) < 2:

            self.show_error(
                "ပုံ ၂ ပုံရွေးပေးပါ။"
            )

            return

        try:

            shutil.copy(
                paths[0],
                "input/face1.jpg"
            )

            shutil.copy(
                paths[1],
                "input/face2.jpg"
            )

            from modules.face_blend import face_blend

            face_blend()

            self.show_result(
                "output/MFS_blend_result.jpg",
                "Face Blend Result"
            )

        except Exception as e:

            self.show_error(str(e))

    def choose_swap_images(self):

        picker = ImagePicker(
            "Select 2 Images for Face Swap",
            self.swap_selected,
            multi=True
        )

        picker.open()

    def swap_selected(self, paths):

        if len(paths) < 2:

            self.show_error(
                "Face Swap အတွက် ပုံ ၂ ပုံရွေးပေးပါ။"
            )

            return

        self.show_error(
            "Face Swap module မရှိသေးပါ။\n"
            "အခု Button ကို ထည့်ပြီးပါပြီ။"
        )

    def show_result(self, path, title):

        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=10
        )

        if os.path.exists(path):

            image = Image(
                source=path
            )

            layout.add_widget(image)

        else:

            layout.add_widget(
                Label(
                    text="Result file မတွေ့ပါ။"
                )
            )

        back = Button(
            text="Back",
            size_hint_y=None,
            height=55
        )

        back.bind(
            on_press=lambda x:
            self.show_menu()
        )

        layout.add_widget(back)

        self.root = layout

    def show_error(self, message):

        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=10
        )

        layout.add_widget(
            Label(
                text=message
            )
        )

        back = Button(
            text="OK",
            size_hint_y=None,
            height=55
        )

        back.bind(
            on_press=lambda x:
            self.show_menu()
        )

        layout.add_widget(back)

        self.root = layout

    def show_ai_chat(self):

        chat = AIChat()
        self.root.clear_widgets()
        self.root.add_widget(chat)


if __name__ == "__main__":

    MFSApp().run()
