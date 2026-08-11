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
import time


class ImagePicker:
    def __init__(self, app, title, callback, multi=False):
        self.app = app
        self.title = title
        self.callback = callback
        self.multi = multi
        self.popup = None
        self.chooser = None
        self.request_code = 2301

    def open(self):
        try:
            from kivy.utils import platform
            if platform == "android":
                self._open_android()
            else:
                self._open_fallback()
        except Exception as e:
            self.app.show_error("Image picker failed:\n\n" + str(e))

    def _open_android(self):
        try:
            from jnius import autoclass

            PythonActivity = autoclass(
                "org.kivy.android.PythonActivity"
            )
            Intent = autoclass("android.content.Intent")

            activity = PythonActivity.mActivity

            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("image/*")

            if self.multi:
                intent.putExtra(
                    Intent.EXTRA_ALLOW_MULTIPLE,
                    True
                )

            activity.bind(
                on_activity_result=self._on_activity_result
            )

            activity.startActivityForResult(
                intent,
                self.request_code
            )

        except Exception as e:
            self.app.show_error(
                "Android image picker failed:\n\n" + str(e)
            )

    def _on_activity_result(self, request_code, result_code, intent):
        if request_code != self.request_code:
            return

        try:
            from jnius import autoclass

            Activity = autoclass("android.app.Activity")

            if result_code != Activity.RESULT_OK:
                return

            if intent is None:
                return

            paths = []
            clip_data = intent.getClipData()

            if clip_data is not None:
                count = clip_data.getItemCount()

                for i in range(count):
                    uri = clip_data.getItemAt(i).getUri()
                    path = self._copy_uri(uri, i)

                    if path:
                        paths.append(path)
            else:
                uri = intent.getData()

                if uri is not None:
                    path = self._copy_uri(uri, 0)

                    if path:
                        paths.append(path)

            if not self.multi:
                paths = paths[:1]

            if not paths:
                self.app.show_error(
                    "ရွေးထားတဲ့ပုံကို မဖတ်နိုင်ပါ။"
                )
                return

            self.callback(paths)

        except Exception as e:
            self.app.show_error(
                "Image loading failed:\n\n" + str(e)
            )

    def _copy_uri(self, uri, index):
        from jnius import autoclass

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )

        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()
        stream = resolver.openInputStream(uri)

        if stream is None:
            return None

        os.makedirs(self.app.input_dir, exist_ok=True)

        destination = os.path.join(
            self.app.input_dir,
            "selected_%d_%d.jpg"
            % (int(time.time() * 1000), index)
        )

        output = open(destination, "wb")
        buffer = bytearray(8192)

        while True:
            count = stream.read(buffer)

            if count <= 0:
                break

            output.write(bytes(buffer[:count]))

        output.close()
        stream.close()

        return destination

    def _open_fallback(self):
        layout = BoxLayout(
            orientation="vertical",
            spacing=8,
            padding=8
        )

        self.chooser = FileChooserIconView(
            filters=[
                "*.jpg",
                "*.jpeg",
                "*.png",
                "*.webp"
            ],
            multiselect=self.multi
        )

        layout.add_widget(self.chooser)

        buttons = BoxLayout(
            size_hint_y=None,
            height=55,
            spacing=8
        )

        select_button = Button(text="Select")
        cancel_button = Button(text="Cancel")

        select_button.bind(
            on_press=self._fallback_select
        )
        cancel_button.bind(
            on_press=self._close_fallback
        )

        buttons.add_widget(select_button)
        buttons.add_widget(cancel_button)

        layout.add_widget(buttons)

        self.popup = Popup(
            title=self.title,
            content=layout,
            size_hint=(0.95, 0.9),
            auto_dismiss=False
        )

        self.popup.open()

    def _fallback_select(self, instance):
        try:
            paths = list(self.chooser.selection)

            if not paths:
                self.app.show_error("ပုံတစ်ပုံရွေးပေးပါ။")
                return

            copied = []

            os.makedirs(
                self.app.input_dir,
                exist_ok=True
            )

            for index, path in enumerate(paths):
                extension = os.path.splitext(path)[1].lower()

                if not extension:
                    extension = ".jpg"

                destination = os.path.join(
                    self.app.input_dir,
                    "selected_%d_%d%s"
                    % (
                        int(time.time() * 1000),
                        index,
                        extension
                    )
                )

                shutil.copy2(path, destination)
                copied.append(destination)

            self._close_fallback()
            self.callback(copied)

        except Exception as e:
            self.app.show_error(
                "Image selection failed:\n\n" + str(e)
            )

    def _close_fallback(self, instance=None):
        if self.popup is not None:
            self.popup.dismiss()
            self.popup = None

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

        self.input_dir = os.path.join(os.getcwd(), "input")
        self.output_dir = os.path.join(os.getcwd(), "output")

        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

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
            self,
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
            self,
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
            self,
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
            self,
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
