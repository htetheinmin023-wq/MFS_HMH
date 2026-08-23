"""Shared test stubs for MFS HMH verification suites.

Fakes kivy / jnius / android modules so main.py can be imported and
exercised on the host with zero external dependencies. Also provides a
tiny PASS/FAIL harness and the fake Android environment (activity,
content resolver, intents, URIs).

Usage from a test script:
    import _test_stubs as stubs
    stubs.install()          # install fake modules into sys.modules
    stubs.reset_env()        # fresh fake Android env per test
    import main              # now safe to import
"""

import os
import sys
import tempfile
import threading
import time
import types


# ---------------------------------------------------------------------------
# PASS/FAIL harness
# ---------------------------------------------------------------------------

class Harness:
    def __init__(self):
        self.results = []
        self.exceptions = []

    def check(self, name, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        self.results.append((name, status))
        suffix = (" - " + detail) if detail else ""
        print("%s - %s%s" % (status, name, suffix))
        return bool(cond)

    def try_run(self, fn):
        """Run a test function, recording any uncaught exception."""
        try:
            fn()
        except Exception as e:
            import traceback
            self.exceptions.append(e)
            print("FAIL - %s raised: %r" % (getattr(fn, "__name__", fn), e))
            traceback.print_exc()

    def summary(self, label):
        total = len(self.results)
        passed = sum(1 for _, s in self.results if s == "PASS")
        print("----")
        print("%s: %d/%d PASS, exceptions: %d"
              % (label, passed, total, len(self.exceptions)))
        ok = (passed == total) and not self.exceptions
        print("RESULT: %s" % ("ALL VERIFICATION TESTS PASSED" if ok else "FAILED"))
        return ok


# ---------------------------------------------------------------------------
# kivy stubs
# ---------------------------------------------------------------------------

class _Logger:
    def __init__(self):
        self.lines = []

    def _log(self, level, msg, args):
        line = "[%s] %s" % (level, (msg % args) if args else msg)
        self.lines.append(line)
        print(line)

    def info(self, msg, *args):
        self._log("INFO", msg, args)

    def warning(self, msg, *args):
        self._log("WARNING", msg, args)

    def error(self, msg, *args):
        self._log("ERROR", msg, args)

    def exception(self, msg, *args):
        self._log("EXC", msg, args)

    def debug(self, msg, *args):
        self._log("DEBUG", msg, args)


Logger = _Logger()


class _Clock:
    """Minimal Clock: schedule_once stores jobs; flush() runs them in
    order (including jobs scheduled from within a job)."""

    def __init__(self):
        self._jobs = []
        self._order = 0

    def schedule_once(self, cb, delay=0):
        self._order += 1
        self._jobs.append((delay, cb, self._order))
        return self._order

    def flush(self):
        while self._jobs:
            delay, cb, order = self._jobs.pop(0)
            cb(0)


Clock = _Clock()


class _LabelBase:
    @classmethod
    def register(cls, name, **kwargs):
        pass


class _Widget:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.children = []

    def add_widget(self, w):
        self.children.append(w)

    def clear_widgets(self):
        self.children = []

    def bind(self, **kwargs):
        self._bound = dict(kwargs)

    def open(self):
        self.opened = True

    def dismiss(self):
        self.opened = False


class _BoxLayout(_Widget):
    pass


class _Button(_Widget):
    pass


class _Label(_Widget):
    pass


class _TextInput(_Widget):
    pass


class _ScrollView(_Widget):
    pass


class _Image(_Widget):
    pass


class _Popup(_Widget):
    pass


class _FileChooserIconView(_Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selection = []


class _App:
    @classmethod
    def get_running_app(cls):
        return None


# ---------------------------------------------------------------------------
# android / jnius stubs
# ---------------------------------------------------------------------------

class _AndroidActivityModule:
    """Fake `android.activity` dispatcher."""

    def __init__(self):
        self._bound = {}
        self.bind_calls = 0

    def bind(self, **kwargs):
        self.bind_calls += 1
        for k, v in kwargs.items():
            self._bound[k] = v

    def unbind(self, **kwargs):
        for k in kwargs:
            self._bound.pop(k, None)

    def fire_activity_result(self, code, result, intent):
        cb = self._bound.get("on_activity_result")
        if cb is not None:
            cb(code, result, intent)

    def fire_resume(self):
        cb = self._bound.get("on_resume")
        if cb is not None:
            cb()


class _Uri:
    def __init__(self, value):
        self.value = value

    def toString(self):
        return self.value

    def __repr__(self):
        return "Uri(%s)" % self.value


class _ClipItem:
    def __init__(self, uri):
        self._uri = uri

    def getUri(self):
        return self._uri


class _ClipData:
    def __init__(self, uris):
        self._items = [_ClipItem(u) for u in uris]

    def getItemCount(self):
        return len(self._items)

    def getItemAt(self, i):
        return self._items[i]


class _Intent:
    ACTION_GET_CONTENT = "android.intent.action.GET_CONTENT"
    CATEGORY_OPENABLE = "android.intent.category.OPENABLE"
    EXTRA_ALLOW_MULTIPLE = "android.intent.extra.ALLOW_MULTIPLE"

    def __init__(self, action=None):
        if (action == "android.provider.action.PICK_IMAGES"
                and photo_picker_broken):
            raise Exception(
                "android.content.ActivityNotFoundException: "
                "no Activity found to handle ACTION_PICK_IMAGES"
            )
        self.action = action
        self._data = None
        self._clip = None
        self._extras = {}

    def addCategory(self, cat):
        return self

    def setType(self, t):
        return self

    def putExtra(self, k, v):
        self._extras[k] = v
        return self

    def getData(self):
        return self._data

    def getClipData(self):
        return self._clip

    def toString(self):
        return "Intent@%d" % id(self)


class _Cursor:
    def __init__(self, row):
        self._row = row
        self._pos = -1

    def moveToFirst(self):
        self._pos = 0
        return True

    def getString(self, col):
        return self._row[col]

    def close(self):
        pass


class _Stream:
    def __init__(self, data):
        self._data = data
        self._pos = 0
        self.closed = False

    def read(self, buffer):
        if self._pos >= len(self._data):
            return -1
        n = min(len(buffer), len(self._data) - self._pos)
        buffer[:n] = self._data[self._pos:self._pos + n]
        self._pos += n
        return n

    def close(self):
        self.closed = True


class _Resolver:
    """Fake ContentResolver: key -> {bytes, name, mime}."""

    def __init__(self):
        self.entries = {}

    def add(self, key, data, name="photo.jpg", mime="image/jpeg"):
        self.entries[key] = {
            "bytes": data, "name": name, "mime": mime,
        }

    def query(self, uri, cols, sel, selargs, sort):
        e = self.entries.get(uri.toString())
        if not e:
            return None
        return _Cursor([e["name"]])

    def getType(self, uri):
        e = self.entries.get(uri.toString())
        return e["mime"] if e else None

    def openInputStream(self, uri):
        e = self.entries.get(uri.toString())
        if not e:
            return None
        return _Stream(e["bytes"])


class _FakeActivity:
    def __init__(self, resolver):
        self.resolver = resolver
        self.started = []             # (intent, request_code)
        self.launch_snapshots = []    # (request_code, pending_keys_at_launch)

    def startActivityForResult(self, intent, request_code):
        # Snapshot: was the picker registered BEFORE the launch?
        # (register-before-launch guarantee, verified by tests)
        keys = sorted(bridge_pending_keys())
        self.launch_snapshots.append((request_code, keys))
        self.started.append((intent, request_code))

    def getContentResolver(self):
        return self.resolver


class _PythonActivity:
    mActivity = None


class _Activity:
    RESULT_OK = -1
    RESULT_CANCELED = 0


class _BuildVersion:
    SDK_INT = 34


class _MediaStore:
    ACTION_PICK_IMAGES = "android.provider.action.PICK_IMAGES"
    EXTRA_PICK_IMAGES_MAX = "android.provider.extra.PICK_IMAGES_MAX"


class _OpenableColumns:
    DISPLAY_NAME = "_display_name"


class _Autoclass:
    CLASSES = {
        "org.kivy.android.PythonActivity": _PythonActivity,
        "android.app.Activity": _Activity,
        "android.content.Intent": _Intent,
        "android.os.Build$VERSION": _BuildVersion,
        "android.provider.MediaStore": _MediaStore,
        "android.provider.OpenableColumns": _OpenableColumns,
    }

    def __call__(self, name):
        if name not in self.CLASSES:
            raise ImportError("autoclass(%s) not stubbed" % name)
        return self.CLASSES[name]


# ---------------------------------------------------------------------------
# fake app object used by ImagePicker
# ---------------------------------------------------------------------------

class FakeApp:
    def __init__(self, tmpdir):
        self.input_dir = os.path.join(tmpdir, "input")
        os.makedirs(self.input_dir, exist_ok=True)
        self.errors = []
        self.callbacks = []

    def show_error(self, msg):
        self.errors.append(msg)

    def on_picked(self, paths):
        self.callbacks.append(list(paths))


# ---------------------------------------------------------------------------
# module install / env reset
# ---------------------------------------------------------------------------

def _mkmod(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Module-level mutable state (single source of truth for tests that
# import this module and mutate these attributes directly).
#   dispatcher  -> fake `android.activity` dispatcher (fire_activity_result)
#   activity    -> fake PythonActivity.mActivity (started/resolver)
photo_picker_broken = False
dispatcher = None
activity = None
tmpdir = None


def bridge_pending_keys():
    import main
    return list(main._PickerBridge.get()._pending.keys())


def install():
    """Install all fake modules (idempotent)."""
    if "kivy" in sys.modules:
        return

    _mkmod("kivy")
    _mkmod("kivy.app", App=_App)
    _mkmod("kivy.clock", Clock=Clock)
    _mkmod("kivy.core")
    _mkmod("kivy.core.text", LabelBase=_LabelBase)
    _mkmod("kivy.logger", Logger=Logger)
    _mkmod("kivy.uix")
    _mkmod("kivy.uix.button", Button=_Button)
    _mkmod("kivy.uix.boxlayout", BoxLayout=_BoxLayout)
    _mkmod("kivy.uix.label", Label=_Label)
    _mkmod("kivy.uix.textinput", TextInput=_TextInput)
    _mkmod("kivy.uix.scrollview", ScrollView=_ScrollView)
    _mkmod("kivy.uix.filechooser", FileChooserIconView=_FileChooserIconView)
    _mkmod("kivy.uix.popup", Popup=_Popup)
    _mkmod("kivy.uix.image", Image=_Image)
    _mkmod("kivy.utils", platform="linux")

    _mkmod("android")
    globals()["dispatcher"] = _AndroidActivityModule()
    sys.modules["android.activity"] = dispatcher
    _mkmod("jnius", autoclass=_Autoclass())


def reset_env():
    """Fresh fake Android environment for one test."""
    global Logger, Clock, photo_picker_broken, tmpdir, activity, dispatcher

    Logger = _Logger()
    sys.modules["kivy.logger"].Logger = Logger
    Clock = _Clock()
    sys.modules["kivy.clock"].Clock = Clock

    photo_picker_broken = False
    tmpdir = tempfile.mkdtemp(prefix="mfs_test_")

    dispatcher = _AndroidActivityModule()
    sys.modules["android.activity"] = dispatcher

    resolver = _Resolver()
    activity = _FakeActivity(resolver)
    _PythonActivity.mActivity = activity

    # Reset the bridge singleton + request-code counter + logger refs
    # so every test starts from a clean slate.
    import main
    main._PickerBridge._instance = None
    main.ImagePicker._next_request_code = 2301
    main.Logger = Logger
    main.Clock = Clock
    main._PickerBridge.get().app = None


def wait_thread(thread, timeout=10.0):
    """Join a worker thread with a timeout (never hangs CI)."""
    if thread is None:
        return True
    thread.join(timeout)
    return not thread.is_alive()


def read_file(path):
    with open(path, "rb") as f:
        return f.read()
