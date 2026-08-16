from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.logger import Logger
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.popup import Popup
from kivy.uix.image import Image
from kivy.utils import platform
import json
import os
import shutil
import sys
import threading
import time
import traceback

# ---------------------------------------------------------------------------
# Myanmar (Burmese) font support
#
# The whole UI is in Burmese, but Kivy's bundled default font (Roboto)
# contains NO Myanmar glyphs, and Kivy on Android does NOT automatically
# fall back to the system fonts. Without this the app opens with every
# label/button rendered as blank/tofu boxes and appears completely
# unusable. Registering under the name "Roboto" makes ALL widgets
# (Label/Button/TextInput) use the bundled Noto Sans Myanmar font by
# default, since every widget defaults to font_name="Roboto".
# ---------------------------------------------------------------------------
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets",
    "fonts",
)
LabelBase.register(
    name="Roboto",
    fn_regular=os.path.join(_FONT_DIR, "NotoSansMyanmar-Regular.ttf"),
    fn_bold=os.path.join(_FONT_DIR, "NotoSansMyanmar-Bold.ttf"),
)

from modules.ai_chat import (
    AIClient,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    detect_action,
)


def _crash_hook(*args):
    """Global safety net: any uncaught Python exception is logged and
    shown in-app instead of silently closing the app on Android.

    Handles both sys.excepthook (exc_type, exc_value, exc_tb) and
    threading.excepthook (single args object with those 3 fields).
    """
    try:
        if len(args) == 3:
            exc_type, exc_value, exc_tb = args
        else:
            exc_type = args[0].exc_type
            exc_value = args[0].exc_value
            exc_tb = args[0].exc_traceback

        tb = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)
        )
        Logger.exception("Uncaught exception: %s", exc_value)

        from kivy.app import App

        app = App.get_running_app()

        if app is None:
            return

        try:
            log_path = os.path.join(app.user_data_dir, "crash.log")

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(tb + "\n")
        except Exception:
            pass

        Clock.schedule_once(
            lambda dt: app.show_error(
                "မမျှော်လင့်ထားတဲ့ အမှားတစ်ခု ဖြစ်ခဲ့ပါတယ်။\n\n"
                + tb[:1500]
            )
        )
    except Exception:
        pass


sys.excepthook = _crash_hook

if hasattr(threading, "excepthook"):
    threading.excepthook = _crash_hook


class ImagePicker:
    _next_request_code = 2301

    # MIME type -> file extension map, used when the content provider
    # does not return a usable DISPLAY_NAME (or the name has no ext).
    _MIME_EXT = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/x-png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/x-bmp": ".bmp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "image/avif": ".avif",
    }

    # Extensions we trust from DISPLAY_NAME (anything else falls back
    # to the MIME map, then to ".jpg").
    _SAFE_EXT = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
        ".avif",
    }

    def __init__(self, app, title, callback, multi=False):
        self.app = app
        self.title = title
        self.callback = callback
        self.multi = multi
        self.popup = None
        self.chooser = None
        self.request_code = ImagePicker._next_request_code
        ImagePicker._next_request_code += 1
        self._bound = False

    def open(self):
        try:
            if platform == "android":
                self._open_android()
            else:
                self._open_fallback()
        except Exception as e:
            self.app.show_error("Image picker failed:\n\n" + str(e))

    def _open_android(self):
        """Launch the system image picker.

        - API 33+: Android Photo Picker (ACTION_PICK_IMAGES) — the
          modern system picker. No storage permission needed; the app
          only ever sees content:// URIs and copies from them.
        - API 24–32: ACTION_GET_CONTENT with image/* — the classic,
          universally-supported fallback (safe picker, no
          READ_EXTERNAL_STORAGE required on 24–32 either).
        """
        from android import activity
        from jnius import autoclass

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )
        Intent = autoclass("android.content.Intent")
        # VERSION is a nested class — pyjnius needs the "$" form.
        # Build.VERSION raises "no attribute 'VERSION'" on Android.
        BuildVersion = autoclass("android.os.Build$VERSION")

        act = PythonActivity.mActivity
        sdk_int = BuildVersion.SDK_INT
        Logger.info(
            "picker: _open_android api=%d multi=%s",
            sdk_int,
            self.multi,
        )

        if sdk_int >= 33:
            MediaStore = autoclass("android.provider.MediaStore")
            intent = Intent(MediaStore.ACTION_PICK_IMAGES)

            if self.multi:
                intent.putExtra(
                    MediaStore.EXTRA_PICK_IMAGES_MAX,
                    20,
                )

            Logger.info(
                "picker: api>=33 -> Photo Picker "
                "(ACTION_PICK_IMAGES, max=%s)",
                20 if self.multi else 1,
            )
        else:
            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("image/*")

            if self.multi:
                intent.putExtra(
                    Intent.EXTRA_ALLOW_MULTIPLE,
                    True,
                )

            Logger.info(
                "picker: api<33 -> ACTION_GET_CONTENT image/* "
                "(multi=%s)",
                self.multi,
            )

        # p4a official API: the android.activity module dispatches
        # on_activity_result to Python callbacks. Bind only once per
        # picker so repeated picks do not stack duplicate listeners.
        if not self._bound:
            activity.bind(
                on_activity_result=self._on_activity_result
            )
            self._bound = True

        act.startActivityForResult(
            intent,
            self.request_code
        )

        Logger.info(
            "picker: startActivityForResult code=%d sent",
            self.request_code,
        )

    def _on_activity_result(self, request_code, result_code, intent):
        Logger.info(
            "picker: on_activity_result code=%d result=%d intent=%s",
            request_code,
            result_code,
            intent is not None,
        )

        if request_code != self.request_code:
            Logger.warning(
                "picker: ignoring result for foreign request %d",
                request_code,
            )
            return

        # The Java callback arrives on the Android UI thread. Move the
        # rest of the handling to the Kivy main-loop thread before
        # touching any Kivy widgets (Kivy is not thread-safe).
        Clock.schedule_once(
            lambda dt: self._handle_result(result_code, intent), 0
        )

    def _handle_result(self, result_code, intent):
        try:
            try:
                from android.activity import unbind
            except Exception:
                unbind = None

            # Unbind once so repeated picks do not stack listeners.
            if self._bound:
                if unbind is not None:
                    unbind(
                        on_activity_result=self._on_activity_result
                    )
                self._bound = False

            from jnius import autoclass

            Activity = autoclass("android.app.Activity")

            # User pressed Cancel / Back — safe no-op.
            if result_code != Activity.RESULT_OK:
                Logger.info("picker: user canceled (result=%s)", result_code)
                return

            if intent is None:
                Logger.warning("picker: RESULT_OK but intent is None")
                return

            paths = []
            clip_data = intent.getClipData()

            if clip_data is not None:
                count = clip_data.getItemCount()
                Logger.info("picker: clip_data items=%d", count)

                for i in range(count):
                    uri = clip_data.getItemAt(i).getUri()
                    Logger.info("picker: copying item %d uri=%s", i, uri)
                    path = self._copy_uri(uri, i)

                    if path:
                        paths.append(path)
            else:
                uri = intent.getData()
                Logger.info("picker: single uri=%s", uri)

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

            Logger.info("picker: %d file(s) ready: %s", len(paths), paths)
            self.callback(paths)

        except Exception as e:
            Logger.error("picker: result handling failed: %s", e)
            self.app.show_error(
                "Image loading failed:\n\n" + str(e)
            )

    def _resolve_extension(self, uri, resolver):
        """Pick a real file extension for a picked URI.

        Order: DISPLAY_NAME extension -> MIME type -> ".jpg".
        Returns a string starting with a dot, e.g. ".jpg".
        """
        from jnius import autoclass

        OpenableColumns = autoclass(
            "android.provider.OpenableColumns"
        )

        # 1) DISPLAY_NAME
        try:
            cursor = resolver.query(
                uri,
                [OpenableColumns.DISPLAY_NAME],
                None,
                None,
                None,
            )
            if cursor is not None and cursor.moveToFirst():
                name = cursor.getString(0)
                ext = os.path.splitext(name or "")[1].lower()

                if ext in self._SAFE_EXT:
                    Logger.info(
                        "picker: ext via DISPLAY_NAME '%s' -> %s",
                        name,
                        ext,
                    )
                    return ext
            if cursor is not None:
                cursor.close()
        except Exception as e:
            Logger.warning(
                "picker: DISPLAY_NAME lookup failed: %s", e
            )

        # 2) MIME type
        try:
            mime = resolver.getType(uri) or ""
            ext = self._MIME_EXT.get(mime.lower())

            if ext:
                Logger.info("picker: ext via MIME '%s' -> %s", mime, ext)
                return ext

            Logger.warning("picker: unmapped MIME '%s'", mime)
        except Exception as e:
            Logger.warning("picker: MIME lookup failed: %s", e)

        # 3) fallback
        Logger.warning("picker: no extension resolvable, using .jpg")
        return ".jpg"

    def _copy_uri(self, uri, index):
        from jnius import autoclass

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )

        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()
        stream = resolver.openInputStream(uri)

        if stream is None:
            Logger.error("picker: openInputStream returned None for %s", uri)
            return None

        os.makedirs(self.app.input_dir, exist_ok=True)

        extension = self._resolve_extension(uri, resolver)

        destination = os.path.join(
            self.app.input_dir,
            "selected_%d_%d%s"
            % (int(time.time() * 1000), index, extension)
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

        Logger.info(
            "picker: copied %s -> %s", uri, destination
        )

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

    def __init__(self, app, **kwargs):
        super().__init__(
            orientation="vertical",
            spacing=8,
            padding=10,
            **kwargs
        )

        self.app = app
        self.history = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self._busy = False

        self.chat = Label(
            text=(
                "HMH AI\n\n"
                "မင်္ဂလာပါ။ ဘာမေးချင်လဲ?\n\n"
                "AI မသုံးခင် Settings မှာ "
                "API key ထည့်ပေးပါ။\n"
                "(Free key: Google AI Studio သို့မဟုတ် Groq)"
            ),
            size_hint_y=None,
            halign="left",
            valign="top"
        )

        self.chat.bind(
            texture_size=self.chat.setter("size")
        )

        # Wrap long lines inside the scroll area.
        self.chat.bind(
            width=lambda *a:
            setattr(
                self.chat,
                "text_size",
                (self.chat.width, None)
            )
        )

        self.scroll = ScrollView()
        self.scroll.add_widget(self.chat)
        self.add_widget(self.scroll)

        # Quick-action row (AI Agent): appears when the AI detects
        # that the user is asking for an app feature.
        self.action_box = BoxLayout(
            size_hint_y=None,
            height=0,
            spacing=5
        )

        self.add_widget(self.action_box)

        self.actions = {
            "scan": ("Face Scan", self.app.choose_scan_image),
            "enhance": ("Face Enhance", self.app.choose_enhance_image),
            "blend": ("Face Blend", self.app.choose_blend_images),
            "swap": ("Face Swap", self.app.choose_swap_images),
        }

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

        self.send_btn = Button(text="Send")
        image_btn = Button(text="Image")
        video_btn = Button(text="Video")
        settings_btn = Button(text="Settings")
        back_btn = Button(text="Back")

        self.send_btn.bind(on_press=self.send_message)
        image_btn.bind(on_press=self.attach_image)
        video_btn.bind(on_press=self.attach_video)
        settings_btn.bind(
            on_press=lambda x: self.app.show_chat_settings()
        )
        back_btn.bind(on_press=lambda x: self.app.show_menu())

        buttons.add_widget(self.send_btn)
        buttons.add_widget(image_btn)
        buttons.add_widget(video_btn)
        buttons.add_widget(settings_btn)
        buttons.add_widget(back_btn)

        self.add_widget(buttons)

    def _scroll_bottom(self):
        Clock.schedule_once(
            lambda dt: setattr(self.scroll, "scroll_y", 0)
        )

    def _append_chat(self, text):
        self.chat.text += text
        self._scroll_bottom()

    def attach_image(self, instance):
        self._append_chat(
            "\n\nHMH AI: ပုံရွေးရန် ဖွင့်နေပါသည်..."
        )

        picker = ImagePicker(
            self.app,
            "Attach Image",
            self._image_attached
        )

        picker.open()

    def _image_attached(self, paths):
        name = os.path.basename(paths[0])

        self._append_chat(
            "\n\nImage ပူးတွဲထားသည်: %s\n"
            "(ဤဗားရှင်းတွင် ပုံကို AI သို့ မပို့သေးပါ)" % name
        )

    def attach_video(self, instance):
        self._append_chat(
            "\n\nVideo: ဤဗားရှင်းတွင် "
            "ဗီဒီယို ပူးတွဲ၍ မရနိုင်သေးပါ။"
        )

    def send_message(self, instance):
        if self._busy:
            return

        message = self.input_box.text.strip()

        if not message:
            return

        self.input_box.text = ""

        self._append_chat("\n\nYou: " + message)
        self.history.append(
            {"role": "user", "content": message}
        )

        # Keep context small: system prompt + last 8 messages.
        if len(self.history) > 9:
            self.history = [self.history[0]] + self.history[-8:]

        action = detect_action(message)

        if action is not None:
            self._offer_action(action)
        else:
            self._ask_ai()

    def _offer_action(self, action):
        """AI Agent: the AI found an app-feature request — offer a
        one-tap button to run it (user confirms before executing)."""
        label, callback = self.actions[action]

        run_btn = Button(text="▶ Run: " + label)
        run_btn.bind(on_press=lambda x: callback())

        self.action_box.clear_widgets()
        self.action_box.height = 55
        self.action_box.add_widget(run_btn)

        self._append_chat(
            "\n\nHMH AI: လုပ်ဆောင်ချက် တွေ့ပါပြီ — "
            "အောက်က ခလုတ်ကို နှိပ်ပါ။"
        )

    def _ask_ai(self):
        self._busy = True
        self.send_btn.disabled = True

        self._append_chat("\n\nHMH AI: စဉ်းစားနေပါသည်...")

        messages = list(self.history)

        thread = threading.Thread(
            target=self._ai_worker,
            args=(messages,),
            daemon=True
        )

        thread.start()

    def _ai_worker(self, messages):
        try:
            client = self.app.get_ai_client()
            reply = client.chat(messages)
            Clock.schedule_once(
                lambda dt: self._finish_reply(reply, None)
            )
        except Exception as e:
            # Capture the message eagerly: the exception variable is
            # cleared when the except block exits, so a lazy str(e)
            # inside the Clock lambda raises UnboundLocalError later
            # (which crashes the whole app on Android).
            error = str(e)
            Clock.schedule_once(
                lambda dt: self._finish_reply(None, error)
            )

    def _finish_reply(self, reply, error):
        self._busy = False
        self.send_btn.disabled = False

        marker = "\n\nHMH AI: စဉ်းစားနေပါသည်..."

        if self.chat.text.endswith(marker):
            self.chat.text = self.chat.text[: -len(marker)]

        if reply:
            self.history.append(
                {"role": "assistant", "content": reply}
            )
            self._append_chat("\n\nHMH AI: " + reply)
        else:
            self._append_chat("\n\nHMH AI: " + error)


class ChatSettings(BoxLayout):

    def __init__(self, app, **kwargs):
        super().__init__(
            orientation="vertical",
            spacing=8,
            padding=10,
            **kwargs
        )

        self.app = app
        config = app.get_chat_config()

        title = Label(
            text="HMH AI Settings",
            font_size=20,
            size_hint_y=None,
            height=40
        )

        self.add_widget(title)

        info = Label(
            text=(
                "OpenAI-compatible API ဖြစ်ပါတယ်။\n"
                "Free key ရနိုင်တဲ့နေရာ:\n"
                "- Google AI Studio (Gemini)\n"
                "- Groq (Llama)\n"
                "Base URL / Key / Model ပြောင်းလို့ရပါတယ်။"
            ),
            size_hint_y=None,
            height=120,
            halign="left",
            valign="top"
        )

        info.bind(
            width=lambda *a:
            setattr(info, "text_size", (info.width, None))
        )

        self.add_widget(info)

        self.base_url_input = TextInput(
            text=config["base_url"],
            hint_text="Base URL",
            size_hint_y=None,
            height=60
        )

        self.api_key_input = TextInput(
            text=config["api_key"],
            hint_text="API Key",
            password=True,
            size_hint_y=None,
            height=60
        )

        self.model_input = TextInput(
            text=config["model"],
            hint_text="Model",
            size_hint_y=None,
            height=60
        )

        self.add_widget(self.base_url_input)
        self.add_widget(self.api_key_input)
        self.add_widget(self.model_input)

        buttons = BoxLayout(
            size_hint_y=None,
            height=55,
            spacing=5
        )

        save_btn = Button(text="Save")
        back_btn = Button(text="Back")

        save_btn.bind(on_press=self._save)
        back_btn.bind(on_press=lambda x: self.app.show_ai_chat())

        buttons.add_widget(save_btn)
        buttons.add_widget(back_btn)

        self.add_widget(buttons)

    def _save(self, instance):
        config = {
            "base_url": self.base_url_input.text.strip(),
            "api_key": self.api_key_input.text.strip(),
            "model": self.model_input.text.strip(),
        }

        try:
            self.app.save_chat_config(config)
            self.app.show_ai_chat()
        except Exception as e:
            self.app.show_error(
                "Settings သိမ်းလို့မရပါ:\n\n" + str(e)
            )


class MFSApp(App):

    def build(self):
        self._setup_dirs()

        # Single persistent root — screens swap inside it.
        # (Kivy only attaches the root widget to the window once.)
        self.root = BoxLayout()

        # Android Back button returns to the main menu instead of
        # quitting from inside a feature screen.
        from kivy.core.window import Window

        Window.bind(on_keyboard=self._on_keyboard)

        self.show_menu()

        return self.root

    def _setup_dirs(self):
        base = self.user_data_dir
        self.input_dir = os.path.join(base, "input")
        self.output_dir = os.path.join(base, "output")

        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _set_screen(self, widget):
        self._in_menu = False
        self.root.clear_widgets()
        self.root.add_widget(widget)

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        # Android Back button (keycode 27): return to the main menu.
        # On the main menu itself, let the system handle Back (exit).
        if key == 27 and platform == "android":
            if not getattr(self, "_in_menu", False):
                self.show_menu()
                return True
        return False

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

        buttons = [
            ("1. Face Scan", self.choose_scan_image),
            ("2. Face Enhance", self.choose_enhance_image),
            ("3. Face Blend", self.choose_blend_images),
            ("4. Face Swap", self.choose_swap_images),
            ("5. HMH AI Chat", self.show_ai_chat),
            ("6. Exit", self.exit_app),
        ]

        for text, callback in buttons:
            button = Button(
                text=text,
                size_hint_y=None,
                height=55
            )

            button.bind(
                on_press=lambda x, cb=callback: cb()
            )

            layout.add_widget(button)

        self._set_screen(layout)
        self._in_menu = True

    def exit_app(self):
        self.stop()

    # ---- processing helpers ----

    def _run_async(self, status_text, worker, *args):
        """Run image processing off the UI thread."""
        self._show_status(status_text)

        thread = threading.Thread(
            target=self._worker_wrapper,
            args=(worker, args),
            daemon=True
        )

        thread.start()

    def _worker_wrapper(self, worker, args):
        try:
            out_path, title = worker(*args)
            Clock.schedule_once(
                lambda dt: self.show_result(out_path, title)
            )
        except Exception as e:
            # Eager capture — lazy str(e) in the Clock lambda would
            # raise UnboundLocalError later and crash the app.
            error = str(e)
            Clock.schedule_once(
                lambda dt: self.show_error(error)
            )

    # ---- Face Scan ----

    def choose_scan_image(self):
        picker = ImagePicker(
            self,
            "Select Face Image",
            self.scan_selected
        )

        picker.open()

    def scan_selected(self, paths):
        if not paths:
            return

        input_path = os.path.join(
            self.input_dir, "face.jpg"
        )
        output_path = os.path.join(
            self.output_dir, "MFS_face_scan.jpg"
        )

        self._run_async(
            "Face Scan လုပ်နေပါသည်...",
            self._scan_worker,
            paths[0],
            input_path,
            output_path
        )

    def _scan_worker(self, src, input_path, output_path):
        shutil.copy(src, input_path)

        from modules.face_scan import face_scan

        face_scan(input_path, output_path)

        return output_path, "Face Scan Result"

    # ---- Face Enhance ----

    def choose_enhance_image(self):
        picker = ImagePicker(
            self,
            "Select Image",
            self.enhance_selected
        )

        picker.open()

    def enhance_selected(self, paths):
        if not paths:
            return

        input_path = os.path.join(
            self.input_dir, "face.jpg"
        )
        output_path = os.path.join(
            self.output_dir, "MFS_face_enhanced.jpg"
        )

        self._run_async(
            "Face Enhance လုပ်နေပါသည်...",
            self._enhance_worker,
            paths[0],
            input_path,
            output_path
        )

    def _enhance_worker(self, src, input_path, output_path):
        shutil.copy(src, input_path)

        from modules.face_enhance import face_enhance

        face_enhance(input_path, output_path)

        return output_path, "Face Enhance Result"

    # ---- Face Blend ----

    def choose_blend_images(self):
        picker = ImagePicker(
            self,
            "Select 2 Images for Blend",
            self.blend_selected,
            multi=True
        )

        picker.open()

    def blend_selected(self, paths):
        if len(paths) < 2:
            self.show_error("ပုံ ၂ ပုံရွေးပေးပါ။")
            return

        input1 = os.path.join(self.input_dir, "face1.jpg")
        input2 = os.path.join(self.input_dir, "face2.jpg")
        output_path = os.path.join(
            self.output_dir, "MFS_blend_result.jpg"
        )

        self._run_async(
            "Face Blend လုပ်နေပါသည်...",
            self._blend_worker,
            paths[0],
            paths[1],
            input1,
            input2,
            output_path
        )

    def _blend_worker(
        self, src1, src2, input1, input2, output_path
    ):
        shutil.copy(src1, input1)
        shutil.copy(src2, input2)

        from modules.face_blend import face_blend

        face_blend(input1, input2, output_path)

        return output_path, "Face Blend Result"

    # ---- Face Swap ----

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

        input1 = os.path.join(self.input_dir, "face1.jpg")
        input2 = os.path.join(self.input_dir, "face2.jpg")
        output_path = os.path.join(
            self.output_dir, "MFS_face_swapped.jpg"
        )

        self._run_async(
            "Face Swap လုပ်နေပါသည်...",
            self._swap_worker,
            paths[0],
            paths[1],
            input1,
            input2,
            output_path
        )

    def _swap_worker(
        self, src1, src2, input1, input2, output_path
    ):
        shutil.copy(src1, input1)
        shutil.copy(src2, input2)

        from modules.face_swap import face_swap

        face_swap(input1, input2, output_path)

        return output_path, "Face Swap Result"

    # ---- HMH AI Chat ----

    def show_ai_chat(self):
        try:
            self._set_screen(AIChat(self))
        except Exception as e:
            Logger.exception("AI chat screen failed to open")
            self.show_error("AI Chat ဖွင့်လို့မရပါ:\n\n" + str(e))

    def get_chat_config(self):
        path = os.path.join(
            self.user_data_dir, "chat_config.json"
        )

        default = {
            "base_url": DEFAULT_BASE_URL,
            "api_key": "",
            "model": DEFAULT_MODEL,
        }

        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)

            merged = dict(default)
            merged.update(config)
            return merged
        except Exception:
            return default

    def save_chat_config(self, config):
        path = os.path.join(
            self.user_data_dir, "chat_config.json"
        )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                config,
                f,
                ensure_ascii=False,
                indent=2
            )

    def get_ai_client(self):
        config = self.get_chat_config()

        return AIClient(
            config["base_url"],
            config["api_key"],
            config["model"]
        )

    def show_chat_settings(self):
        try:
            self._set_screen(ChatSettings(self))
        except Exception as e:
            Logger.exception("AI chat settings screen failed to open")
            self.show_error("Settings ဖွင့်လို့မရပါ:\n\n" + str(e))

    # ---- screens ----

    def show_result(self, path, title):
        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=10
        )

        heading = Label(
            text=title,
            font_size=18,
            size_hint_y=None,
            height=40
        )

        layout.add_widget(heading)

        if os.path.exists(path):
            layout.add_widget(Image(source=path))
        else:
            layout.add_widget(
                Label(text="Result file မတွေ့ပါ။")
            )

        back = Button(
            text="Back",
            size_hint_y=None,
            height=55
        )

        back.bind(on_press=lambda x: self.show_menu())

        layout.add_widget(back)

        self._set_screen(layout)

    def show_error(self, message):
        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=10
        )

        layout.add_widget(Label(text=message))

        ok = Button(
            text="OK",
            size_hint_y=None,
            height=55
        )

        ok.bind(on_press=lambda x: self.show_menu())

        layout.add_widget(ok)

        self._set_screen(layout)

    def _show_status(self, text):
        layout = BoxLayout(
            orientation="vertical",
            spacing=10,
            padding=20
        )

        layout.add_widget(Label(text=text))

        self._set_screen(layout)


if __name__ == "__main__":
    MFSApp().run()
