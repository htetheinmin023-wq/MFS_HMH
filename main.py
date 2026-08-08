from kivy.app import App
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.popup import Popup

from modules.face_scan import face_scan
from modules.face_enhance import face_enhance
from modules.face_blend import face_blend


class AIChat(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kwargs)

        self.chat = Label(
            text="HMH AI\n\nမင်္ဂလာပါ။ ဘာမေးချင်လဲ?",
            size_hint_y=None,
            halign="left",
            valign="top"
        )
        self.chat.bind(texture_size=self.chat.setter("size"))

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

        buttons = BoxLayout(size_hint_y=None, height=55, spacing=5)

        send = Button(text="Send")
        image = Button(text=" Image")
        video = Button(text=" Video")
        back = Button(text="Back")

        send.bind(on_press=self.send_message)
        image.bind(on_press=lambda x: self.choose_file(["*.jpg", "*.jpeg", "*.png", "*.webp"]))
        video.bind(on_press=lambda x: self.choose_file(["*.mp4", "*.mkv", "*.mov", "*.avi"]))
        back.bind(on_press=lambda x: self.back_to_menu())

        buttons.add_widget(send)
        buttons.add_widget(image)
        buttons.add_widget(video)
        buttons.add_widget(back)

        self.add_widget(buttons)

    def send_message(self, instance):
        message = self.input_box.text.strip()

        if not message:
            return

        self.chat.text += f"\n\nYou: {message}\n\nHMH AI: API credits မရှိသေးလို့ အခု Demo Mode နဲ့ လုပ်နေပါတယ်။"
        self.input_box.text = ""

    def choose_file(self, filters):
        chooser = FileChooserIconView(filters=filters)

        popup = Popup(
            title="Choose file",
            content=chooser,
            size_hint=(0.95, 0.9)
        )

        chooser.bind(
            on_submit=lambda chooser, selection, touch:
            self.file_selected(selection, popup)
        )

        popup.open()

    def file_selected(self, selection, popup):
        if selection:
            path = selection[0]
            self.chat.text += f"\n\n File selected:\n{path}\n\nHMH AI: File ရွေးပြီးပါပြီ။"
            popup.dismiss()

    def back_to_menu(self):
        App.get_running_app().show_menu()


class MFSApp(App):
    def build(self):
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
        btn4 = Button(text="4. HMH AI Chat")

        btn1.bind(on_press=lambda x: face_scan())
        btn2.bind(on_press=lambda x: face_enhance())
        btn3.bind(on_press=lambda x: face_blend())
        btn4.bind(on_press=lambda x: self.show_ai_chat())

        layout.add_widget(btn1)
        layout.add_widget(btn2)
        layout.add_widget(btn3)
        layout.add_widget(btn4)

        self.root = layout

    def show_ai_chat(self):
        self.root = AIChat()


if __name__ == "__main__":
    MFSApp().run()
