"""ui_full_test.py — MFS HMH UI/flow regression suite.

Verifies the ImagePicker public behavior is intact after the
_PickerBridge refactor: sequential single picks, Photo Picker (API 33+)
with GET_CONTENT fallback, multi getData+ClipData merge with dedup,
cancel path, multi<2 guidance, desktop FileChooser fallback, and error
handling. Runs on the host with stubbed kivy/jnius/android.

Run:  python3 ui_full_test.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _test_stubs as stubs

stubs.install()

import main  # noqa: E402

RESULT_OK = -1
RESULT_CANCELED = 0

h = stubs.Harness()


def setup_android(sdk=34, broken_photo_picker=False):
    stubs.reset_env()
    main.platform = "android"
    stubs._BuildVersion.SDK_INT = sdk
    stubs.photo_picker_broken = broken_photo_picker
    app = stubs.FakeApp(stubs.tmpdir)
    return app


def make_intent(uris, data=None, multi=True):
    """Build an _Intent: data + clip (multi) or just data (single)."""
    intent = stubs._Intent("android.provider.action.PICK_IMAGES")
    if data is not None:
        intent._data = data
    if multi and uris:
        intent._clip = stubs._ClipData(uris)
    return intent


def complete_pick(picker):
    """Wait for the copy worker and flush scheduled callbacks."""
    stubs.wait_thread(picker._copy_thread)
    stubs.Clock.flush()


def fire(code, result_code, intent):
    stubs.dispatcher.fire_activity_result(code, result_code, intent)
    stubs.Clock.flush()


def test_api33_photo_picker_single():
    app = setup_android(sdk=34)
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    ok = len(stubs.activity.started) == 1
    intent, code = stubs.activity.started[0]
    ok = ok and intent.action == stubs._MediaStore.ACTION_PICK_IMAGES
    ok = ok and stubs._MediaStore.EXTRA_PICK_IMAGES_MAX not in intent._extras
    ok = ok and code == picker.request_code
    # Register-before-launch: pending already contains the code at launch.
    snap = stubs.activity.launch_snapshots[0]
    ok = ok and picker.request_code in snap[1]
    h.check("api33 photo picker single pick launched", ok)


def test_api33_photo_picker_multi_max():
    app = setup_android(sdk=34)
    picker = main.ImagePicker(app, "T", app.on_picked, multi=True)
    picker.open()

    intent, _ = stubs.activity.started[0]
    ok = intent.action == stubs._MediaStore.ACTION_PICK_IMAGES
    ok = ok and intent._extras.get(
        stubs._MediaStore.EXTRA_PICK_IMAGES_MAX) == 20
    h.check("api33 photo picker multi sets max=20", ok)


def test_photo_picker_fallback_get_content():
    app = setup_android(sdk=34, broken_photo_picker=True)
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent, _ = stubs.activity.started[0]
    ok = intent.action == stubs._Intent.ACTION_GET_CONTENT
    h.check("photo picker fallback to GET_CONTENT", ok)


def test_api32_get_content_multi():
    app = setup_android(sdk=32)
    picker = main.ImagePicker(app, "T", app.on_picked, multi=True)
    picker.open()

    intent, _ = stubs.activity.started[0]
    ok = intent.action == stubs._Intent.ACTION_GET_CONTENT
    ok = ok and intent._extras.get(stubs._Intent.EXTRA_ALLOW_MULTIPLE) is True
    h.check("api32 GET_CONTENT multi with EXTRA_ALLOW_MULTIPLE", ok)


def test_single_pick_copy_and_callback():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(
        uri.toString(), b"\xff\xd8photo1", "a.jpg", "image/jpeg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = make_intent([uri], data=uri, multi=False)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    ok = len(app.callbacks) == 1 and len(app.callbacks[0]) == 1
    path = app.callbacks[0][0] if ok else ""
    ok = ok and os.path.exists(path) and stubs.read_file(path) == b"\xff\xd8photo1"
    ok = ok and picker.status == main._PickerBridge.STATUS_DONE
    h.check("single pick copies URI and calls callback", ok)


def test_multi_getdata_plus_clipdata_merge():
    app = setup_android()
    u1 = stubs._Uri("content://media/1")
    u2 = stubs._Uri("content://media/2")
    u3 = stubs._Uri("content://media/3")
    r = stubs.activity.resolver
    r.add(u1.toString(), b"AAA", "a.jpg")
    r.add(u2.toString(), b"BBB", "b.jpg")
    r.add(u3.toString(), b"CCC", "c.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=True)
    picker.open()

    intent = make_intent([u2, u3], data=u1, multi=True)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    ok = len(app.callbacks) == 1 and len(app.callbacks[0]) == 3
    h.check("multi merges getData + ClipData (3 files)", ok)


def test_dedup_same_uri_getdata_and_clip():
    # Same URI reported by both getData() and ClipData (a real Android
    # quirk) must be copied only once.
    app = setup_android()
    u1 = stubs._Uri("content://media/1")
    r = stubs.activity.resolver
    r.add(u1.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = make_intent([u1], data=u1, multi=True)  # same URI twice
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    ok = len(app.callbacks) == 1 and len(app.callbacks[0]) == 1
    ok = ok and len(os.listdir(app.input_dir)) == 1  # one copy on disk
    h.check("duplicate URI in getData+ClipData deduped to 1 file", ok)


def test_cancel_no_callback():
    app = setup_android()
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    fire(picker.request_code, RESULT_CANCELED, None)

    ok = len(app.callbacks) == 0
    ok = ok and picker.status == main._PickerBridge.STATUS_CANCELED
    ok = ok and len(os.listdir(app.input_dir)) == 0
    h.check("cancel produces no callback/files", ok)


def test_ok_intent_none_error():
    app = setup_android()
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    fire(picker.request_code, RESULT_OK, None)

    ok = len(app.callbacks) == 0
    ok = ok and picker.status == main._PickerBridge.STATUS_ERROR
    ok = ok and len(app.errors) >= 1
    h.check("RESULT_OK with None intent -> error, no callback", ok)


def test_multi_less_than_2_guidance():
    app = setup_android()
    u1 = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(u1.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=True)
    picker.open()

    intent = make_intent([u1], data=u1, multi=True)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    ok = len(app.callbacks) == 0
    ok = ok and any("ပုံ ၂ ပုံ ရွေးပေးပါ" in e for e in app.errors)
    ok = ok and picker.status == main._PickerBridge.STATUS_ERROR
    h.check("multi with 1 file shows 2-images guidance", ok)


def test_sequential_single_picks():
    app = setup_android()
    u1 = stubs._Uri("content://media/1")
    u2 = stubs._Uri("content://media/2")
    r = stubs.activity.resolver
    r.add(u1.toString(), b"AAA", "a.jpg")
    r.add(u2.toString(), b"BBB", "b.jpg")

    p1 = main.ImagePicker(app, "Img 1/2", app.on_picked, multi=False)
    p1.open()
    fire(p1.request_code, RESULT_OK, make_intent([u1], data=u1, multi=False))
    complete_pick(p1)

    p2 = main.ImagePicker(app, "Img 2/2", app.on_picked, multi=False)
    p2.open()
    fire(p2.request_code, RESULT_OK, make_intent([u2], data=u2, multi=False))
    complete_pick(p2)

    ok = len(app.callbacks) == 2
    ok = ok and p1.status == main._PickerBridge.STATUS_DONE
    ok = ok and p2.status == main._PickerBridge.STATUS_DONE
    ok = ok and len(os.listdir(app.input_dir)) == 2
    h.check("sequential single picks (blend/swap flow) both complete", ok)


def test_desktop_fallback_chooser():
    stubs.reset_env()
    main.platform = "linux"
    app = stubs.FakeApp(stubs.tmpdir)
    src = os.path.join(stubs.tmpdir, "src.jpg")
    with open(src, "wb") as f:
        f.write(b"JPEGDATA")

    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    ok = picker.popup is not None and getattr(picker.popup, "opened", False)
    picker.chooser.selection = [src]
    picker._fallback_select(None)

    ok = ok and len(app.callbacks) == 1 and len(app.callbacks[0]) == 1
    ok = ok and stubs.read_file(app.callbacks[0][0]) == b"JPEGDATA"
    ok = ok and picker.status == main._PickerBridge.STATUS_DONE
    h.check("desktop FileChooser fallback copies and calls callback", ok)


def test_open_android_error_shows_error():
    app = setup_android()
    stubs._PythonActivity.mActivity = None  # breaks launch
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    ok = len(app.errors) >= 1
    ok = ok and picker.status == main._PickerBridge.STATUS_ERROR
    h.check("picker launch failure -> error dialog, status=error", ok)


def test_extension_via_display_name():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"DATA", "photo.PNG",
                                "image/png")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = make_intent([uri], data=uri, multi=False)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    path = app.callbacks[0][0] if app.callbacks else ""
    ok = path.endswith(".png")
    h.check("extension resolved from DISPLAY_NAME (photo.PNG -> .png)", ok)


def test_extension_via_mime_fallback():
    # DISPLAY_NAME has no usable extension -> MIME type decides.
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"DATA", "photo",
                                "image/webp")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = make_intent([uri], data=uri, multi=False)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    path = app.callbacks[0][0] if app.callbacks else ""
    ok = path.endswith(".webp")
    h.check("extension resolved from MIME when name has no ext", ok)


def test_extension_default_jpg():
    # Neither DISPLAY_NAME nor MIME map -> safe ".jpg" fallback.
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"DATA", "photo",
                                "application/octet-stream")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = make_intent([uri], data=uri, multi=False)
    fire(picker.request_code, RESULT_OK, intent)
    complete_pick(picker)

    path = app.callbacks[0][0] if app.callbacks else ""
    ok = path.endswith(".jpg")
    h.check("unmapped name+MIME -> safe .jpg fallback", ok)


TESTS = [
    test_api33_photo_picker_single,
    test_api33_photo_picker_multi_max,
    test_photo_picker_fallback_get_content,
    test_api32_get_content_multi,
    test_single_pick_copy_and_callback,
    test_multi_getdata_plus_clipdata_merge,
    test_dedup_same_uri_getdata_and_clip,
    test_cancel_no_callback,
    test_ok_intent_none_error,
    test_multi_less_than_2_guidance,
    test_sequential_single_picks,
    test_desktop_fallback_chooser,
    test_open_android_error_shows_error,
    test_extension_via_display_name,
    test_extension_via_mime_fallback,
    test_extension_default_jpg,
]

if __name__ == "__main__":
    print("== ui_full_test.py — UI/flow regression ==")
    for t in TESTS:
        h.try_run(t)
    ok = h.summary("ui_full_test.py")
    sys.exit(0 if ok else 1)
