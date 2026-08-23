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


# Unique file-name stamp: time_ms + monotonic counter. The counter
# guards against two picks landing in the same millisecond (sequential
# single picks, fast devices) overwriting each other's file.
_copy_seq = [0]
_copy_seq_lock = threading.Lock()


def _unique_stamp():
    with _copy_seq_lock:
        _copy_seq[0] += 1
        return "%d_%d" % (int(time.time() * 1000), _copy_seq[0])


class _PickerBridge:
    """App-lifetime singleton that owns the Android on_activity_result
    listener and routes results to in-flight ImagePicker requests.

    Design:
    - The listener is bound exactly ONCE at app startup and never
      unbound, so there is no window where an activity result can
      arrive without a Python listener (the old per-picker bind /
      unbind design could lose results).
    - launch() registers the picker BEFORE startActivityForResult, so
      a result cannot slip in before registration.
    - If a result still arrives before registration (instant picker
      answers), it is buffered and delivered right after registration
      (lost-result recovery).
    - on_resume triggers a recovery scan: a pending picker that
      regained the foreground without a result is marked lost.
    - Every request_code is consumed at most once (duplicate callback
      protection), and URI copying runs on a background worker thread
      so the UI thread never blocks.
    """

    STATUS_IDLE = "idle"
    STATUS_PENDING = "pending"
    STATUS_RESULT = "result"
    STATUS_COPYING = "copying"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_LOST = "lost"
    STATUS_CANCELED = "canceled"

    _instance = None

    @classmethod
    def get(cls, app=None):
        if cls._instance is None:
            cls._instance = cls()
        if app is not None:
            cls._instance.app = app
        return cls._instance

    def __init__(self):
        self.app = None
        self._bound = False
        self._pending = {}     # request_code -> ImagePicker
        self._buffer = {}      # request_code -> (result_code, intent)
        self._handled = set()  # request codes consumed (dup protection)

    # ---- app-lifetime listener ----

    def bind(self):
        """Bind the on_activity_result / on_resume listeners exactly
        once for the whole app lifetime (idempotent)."""
        if self._bound:
            return True

        try:
            from android import activity

            activity.bind(
                on_activity_result=self._on_activity_result
            )
            activity.bind(on_resume=self._on_resume)
            self._bound = True
            Logger.info("picker_bridge: app-lifetime listener bound")
        except Exception as e:
            # Desktop / non-Android runtime: no bridge available; the
            # ImagePicker falls back to the FileChooser path.
            Logger.error("picker_bridge: bind failed: %s", e)
            self._bound = False

        return self._bound

    # ---- launch / routing ----

    def launch(self, picker, request_code, intent):
        """Register the picker BEFORE launching the system picker, then
        deliver any result that arrived early (lost-result recovery)."""
        from jnius import autoclass

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )

        if request_code in self._pending:
            Logger.warning(
                "picker_bridge: request %d already pending",
                request_code,
            )

        self._pending[request_code] = picker
        self._handled.discard(request_code)
        picker._set_status(self.STATUS_PENDING)

        act = PythonActivity.mActivity
        act.startActivityForResult(intent, request_code)

        Logger.info(
            "picker_bridge: launched code=%d status=%s",
            request_code,
            picker.status,
        )

        # Lost-result recovery: deliver a result that arrived before
        # this registration (buffered by _route).
        self._deliver_buffered(request_code)

    def _route(self, request_code, result_code, intent):
        """Kivy-thread entry: route an activity result to its picker."""
        if request_code in self._handled:
            Logger.warning(
                "picker_bridge: duplicate result code=%d ignored",
                request_code,
            )
            return

        picker = self._pending.get(request_code)

        if picker is None:
            # Result arrived before the picker registered — buffer it;
            # launch() delivers it immediately after registering
            # (lost-result recovery for the launch race).
            self._buffer[request_code] = (result_code, intent)
            Logger.info(
                "picker_bridge: buffered early result code=%d result=%d",
                request_code,
                result_code,
            )
            return

        # Duplicate callback protection: consume this code once.
        self._handled.add(request_code)
        self._buffer.pop(request_code, None)

        picker._on_bridge_result(result_code, intent)

    def _deliver_buffered(self, request_code):
        """Lost-result recovery: hand a buffered early result to its
        picker now that the picker has registered."""
        item = self._buffer.pop(request_code, None)

        if item is None:
            return

        if request_code in self._handled:
            Logger.info(
                "picker_bridge: buffered result code=%d already handled",
                request_code,
            )
            return

        self._handled.add(request_code)
        picker = self._pending.get(request_code)

        if picker is None:
            return

        result_code, intent = item
        Logger.info(
            "picker_bridge: recovered buffered result code=%d",
            request_code,
        )
        Clock.schedule_once(
            lambda dt: picker._on_bridge_result(result_code, intent), 0
        )

    def _on_activity_result(self, request_code, result_code, intent):
        """Java/UI-thread callback — marshal to the Kivy thread."""
        Clock.schedule_once(
            lambda dt: self._route(request_code, result_code, intent), 0
        )

    def _on_resume(self):
        """Android on_resume — schedule the lost-result recovery scan."""
        Clock.schedule_once(lambda dt: self._scan_lost(), 1.5)

    def _scan_lost(self):
        """Lost-result recovery: any pending picker that regained the
        foreground without a result is stuck — mark it lost."""
        final = (
            self.STATUS_DONE,
            self.STATUS_ERROR,
            self.STATUS_LOST,
            self.STATUS_CANCELED,
        )

        for code, picker in list(self._pending.items()):
            if code in self._handled:
                continue

            if picker.status in final:
                continue

            Logger.warning(
                "picker_bridge: request %d lost (no result on resume)",
                code,
            )
            picker._mark_lost()

    def forget(self, request_code):
        """Remove a finished picker from the pending registry."""
        self._pending.pop(request_code, None)


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
        self.status = _PickerBridge.STATUS_IDLE
        self.status_log = [self.status]
        self._bridge = _PickerBridge.get(app)
        self._copy_thread = None

    # ---- result-status flow ----

    def _set_status(self, status):
        """Advance this request's status (result-status flow)."""
        self.status = status
        self.status_log.append(status)
        Logger.info(
            "picker_bridge: status=%s code=%d",
            status,
            self.request_code,
        )

    def open(self):
        try:
            if platform == "android":
                self._open_android()
            else:
                self._open_fallback()
        except Exception as e:
            self._set_status(_PickerBridge.STATUS_ERROR)
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

            try:
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

                # Route through the app-lifetime bridge: the listener
                # is already bound at app startup, and the picker is
                # registered BEFORE launching so no result can be lost.
                self._bridge.bind()
                self._bridge.launch(self, self.request_code, intent)

                Logger.info(
                    "picker: Photo Picker launched code=%d",
                    self.request_code,
                )
                return
            except Exception as e:
                # Some Android 13+ devices/ROMs do not ship the Photo
                # Picker module (ActivityNotFoundException). Fall back
                # to the classic GET_CONTENT picker — universally
                # supported and works on every device.
                Logger.warning(
                    "picker: Photo Picker unavailable (%s) -> "
                    "falling back to GET_CONTENT",
                    e,
                )

            # Fall through to GET_CONTENT (also for API < 33).
            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("image/*")

            if self.multi:
                intent.putExtra(
                    Intent.EXTRA_ALLOW_MULTIPLE,
                    True,
                )

            Logger.info(
                "picker: fallback -> ACTION_GET_CONTENT image/* "
                "(multi=%s)",
                self.multi,
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
        # on_activity_result to the app-lifetime bridge listener
        # (bound once at startup). Register-before-launch leaves no
        # window in which a result could be lost.
        self._bridge.bind()
        self._bridge.launch(self, self.request_code, intent)

        Logger.info(
            "picker: startActivityForResult code=%d sent via bridge",
            self.request_code,
        )

    def _on_bridge_result(self, result_code, intent):
        """Kivy-thread: a routed activity result for THIS request."""
        try:
            from jnius import autoclass

            Activity = autoclass("android.app.Activity")

            # User pressed Cancel / Back — safe no-op.
            if result_code != Activity.RESULT_OK:
                self._set_status(_PickerBridge.STATUS_CANCELED)
                Logger.info(
                    "picker: user canceled (result=%s)",
                    result_code,
                )
                self._bridge.forget(self.request_code)
                return

            if intent is None:
                self._set_status(_PickerBridge.STATUS_ERROR)
                Logger.warning("picker: RESULT_OK but intent is None")
                self.app.show_error(
                    "ရွေးထားတဲ့ပုံရဲ့ အချက်အလက် မရရှိပါ။\n"
                    "ထပ်ကြိုးစားကြည့်ပါ။"
                )
                self._bridge.forget(self.request_code)
                return

            uris = self._parse_intent(intent)

            if not uris:
                self._set_status(_PickerBridge.STATUS_ERROR)
                self.app.show_error(
                    "ရွေးထားတဲ့ပုံကို မဖတ်နိုင်ပါ။"
                )
                self._bridge.forget(self.request_code)
                return

            self._set_status(_PickerBridge.STATUS_RESULT)

            # URI copying is I/O — run it on a background worker so
            # the UI thread never blocks (Kivy is not thread-safe, so
            # the completion is marshalled back via Clock).
            self._set_status(_PickerBridge.STATUS_COPYING)
            self._copy_thread = threading.Thread(
                target=self._copy_worker,
                args=(uris,),
                daemon=True,
            )
            self._copy_thread.start()
        except Exception as e:
            self._set_status(_PickerBridge.STATUS_ERROR)
            Logger.error("picker: result handling failed: %s", e)
            self.app.show_error(
                "Image loading failed:\n\n" + str(e)
            )

    def _parse_intent(self, intent):
        """Collect picked URIs: getData() + ClipData merged and
        deduplicated (some devices put the first URI in getData and
        the rest in ClipData)."""
        uris = []
        seen = set()

        def add_uri(uri):
            if uri is None:
                return

            key = uri.toString()

            if key in seen:
                Logger.info("picker: skip duplicate uri=%s", key)
                return

            seen.add(key)
            uris.append(uri)

        clip_data = intent.getClipData()
        add_uri(intent.getData())

        if clip_data is not None:
            count = clip_data.getItemCount()
            Logger.info("picker: clip_data items=%d", count)

            for i in range(count):
                add_uri(clip_data.getItemAt(i).getUri())

        if not self.multi:
            uris = uris[:1]

        return uris

    def _copy_worker(self, uris):
        """Background thread: copy every picked URI to app storage."""
        paths = []

        try:
            for index, uri in enumerate(uris):
                Logger.info(
                    "picker: copying item %d uri=%s", index, uri
                )
                path = self._copy_uri(uri, index)

                if path:
                    paths.append(path)

            Clock.schedule_once(
                lambda dt: self._finish_copy(paths, None), 0
            )
        except Exception as e:
            # Eager capture — the exception variable is cleared when
            # the except block exits.
            error = str(e)
            Logger.error("picker: copy worker failed: %s", error)
            Clock.schedule_once(
                lambda dt: self._finish_copy([], error), 0
            )

    def _finish_copy(self, paths, error):
        """Kivy-thread: finalize the copy worker result."""
        self._bridge.forget(self.request_code)

        if error:
            self._set_status(_PickerBridge.STATUS_ERROR)
            self.app.show_error(
                "Image loading failed:\n\n" + error
            )
            return

        if not paths:
            self._set_status(_PickerBridge.STATUS_ERROR)
            self.app.show_error(
                "ရွေးထားတဲ့ပုံကို မဖတ်နိုင်ပါ။"
            )
            return

        if self.multi and len(paths) < 2:
            self._set_status(_PickerBridge.STATUS_ERROR)
            self.app.show_error(
                "ပုံ ၂ ပုံ ရွေးပေးပါ။\n"
                "ပုံတွေကို ဖိနှိပ်ပြီး (long-press) "
                "သို့မဟုတ် အမှတ်ခြစ်ပြီး "
                "၂ ပုံရွေးပါ။"
            )
            return

        self._set_status(_PickerBridge.STATUS_DONE)
        Logger.info("picker: %d file(s) ready: %s", len(paths), paths)
        self.callback(paths)

    def _mark_lost(self):
        """Lost-result recovery terminal state: the result never
        arrived, so clean up and tell the user."""
        self._set_status(_PickerBridge.STATUS_LOST)
        self._bridge.forget(self.request_code)
        Logger.warning(
            "picker: request %d marked lost", self.request_code
        )

        try:
            self.app.show_error(
                "ပုံရွေးချယ်မှု ရလဒ် ပျောက်ဆုံးသွားပါသည်။\n"
                "ထပ်ကြိုးစားကြည့်ပါ။"
            )
        except Exception:
            pass

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
            "selected_%s_%d%s" % (_unique_stamp(), index, extension)
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

            self._set_status(_PickerBridge.STATUS_COPYING)
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
                    "selected_%s_%d%s"
                    % (_unique_stamp(), index, extension)
                )

                shutil.copy2(path, destination)
                copied.append(destination)

            self._close_fallback()
            self._set_status(_PickerBridge.STATUS_DONE)
            self.callback(copied)

        except Exception as e:
            self._set_status(_PickerBridge.STATUS_ERROR)
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

        # App-lifetime Android activity-result listener: bind the
        # picker bridge once at startup (idempotent; no-op on desktop).
        _PickerBridge.get(self).bind()

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
    #
    # Blend/Swap use TWO sequential SINGLE picks instead of one
    # multi-select pick. Multi-select pickers (Photo Picker extra,
    # GET_CONTENT EXTRA_ALLOW_MULTIPLE) behave differently per
    # device/ROM and some simply do not open or do not support
    # multi-select. Sequential single picks work on every Android
    # device (single pick already proven working).

    def choose_blend_images(self):
        self._blend_pending = []
        self._pick_blend_next("Select Image 1/2 for Blend")

    def _pick_blend_next(self, title):
        picker = ImagePicker(self, title, self._blend_picked, multi=False)
        picker.open()

    def _blend_picked(self, paths):
        if not paths:
            return

        self._blend_pending.append(paths[0])

        if len(self._blend_pending) >= 2:
            self.blend_selected(list(self._blend_pending))
            return

        self._pick_blend_next("Select Image 2/2 for Blend")

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
        self._swap_pending = []
        self._pick_swap_next("Select Image 1/2 for Face Swap")

    def _pick_swap_next(self, title):
        picker = ImagePicker(self, title, self._swap_picked, multi=False)
        picker.open()

    def _swap_picked(self, paths):
        if not paths:
            return

        self._swap_pending.append(paths[0])

        if len(self._swap_pending) >= 2:
            self.swap_selected(list(self._swap_pending))
            return

        self._pick_swap_next("Select Image 2/2 for Face Swap")

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
