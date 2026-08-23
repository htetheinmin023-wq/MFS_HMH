"""mfs_verify.py — _PickerBridge core verification suite.

Verifies each of the 7 fix components in main.py:
  1. _PickerBridge class exists (app-lifetime singleton)
  2. app-lifetime activity-result listener (bind-once)
  3. activity-result routing by request_code
  4. lost-result recovery (buffer-before-register + resume scan)
  5. duplicate callback protection
  6. URI copy worker (background thread, UI thread never blocks)
  7. result-status flow (idle/pending/result/copying/done/error/lost)

Runs on the host with stubbed kivy/jnius/android.

Run:  python3 mfs_verify.py
"""

import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _test_stubs as stubs

stubs.install()

import main  # noqa: E402

RESULT_OK = -1

h = stubs.Harness()


def setup_android():
    stubs.reset_env()
    main.platform = "android"
    app = stubs.FakeApp(stubs.tmpdir)
    return app


def complete_pick(picker):
    stubs.wait_thread(picker._copy_thread)
    stubs.Clock.flush()


def test_bridge_class_exists():
    stubs.reset_env()
    ok = hasattr(main, "_PickerBridge")
    ok = ok and callable(getattr(main._PickerBridge, "get", None))
    h.check("1. _PickerBridge class exists with singleton get()", ok)


def test_bridge_singleton_same_instance():
    stubs.reset_env()
    app = stubs.FakeApp(stubs.tmpdir)
    b1 = main._PickerBridge.get(app)
    b2 = main._PickerBridge.get(app)
    ok = b1 is b2
    ok = ok and b1.app is app
    h.check("2. _PickerBridge is a singleton (same instance)", ok)


def test_bind_once_app_lifetime():
    stubs.reset_env()
    app = stubs.FakeApp(stubs.tmpdir)
    bridge = main._PickerBridge.get(app)

    r1 = bridge.bind()
    r2 = bridge.bind()
    r3 = bridge.bind()

    ok = r1 is True and r2 is True and r3 is True
    ok = ok and bridge._bound is True
    # One bridge.bind() = one dispatcher.bind() per event type
    # (on_activity_result + on_resume). Three bridge.bind() calls
    # must still produce exactly 2 dispatcher binds (bound ONCE).
    ok = ok and stubs.dispatcher.bind_calls == 2
    ok = ok and "on_activity_result" in stubs.dispatcher._bound
    ok = ok and "on_resume" in stubs.dispatcher._bound
    h.check("3. listener bound exactly once (app-lifetime)", ok)


def test_bind_guarded_when_android_missing():
    stubs.reset_env()
    app = stubs.FakeApp(stubs.tmpdir)
    saved = sys.modules.pop("android.activity", None)
    try:
        bridge = main._PickerBridge.get(app)
        bridge._bound = False
        r = bridge.bind()
        ok = r is False and bridge._bound is False
    finally:
        sys.modules["android.activity"] = saved
    h.check("4. bind() safe no-op without android.activity", ok)


def test_route_to_pending_picker():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(
        picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    ok = len(app.callbacks) == 1
    ok = ok and picker.status == main._PickerBridge.STATUS_DONE
    h.check("5. activity result routed to its pending picker", ok)


def test_foreign_code_buffered_then_recovered():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    bridge = main._PickerBridge.get(app)
    bridge.bind()  # app-lifetime listener already bound at startup

    # Result arrives BEFORE the picker registers (lost-result race).
    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(
        picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()

    ok = picker.request_code in bridge._buffer

    # Now the picker opens/registers -> buffered result recovered.
    picker.open()
    stubs.Clock.flush()
    complete_pick(picker)

    ok = ok and len(app.callbacks) == 1
    ok = ok and picker.status == main._PickerBridge.STATUS_DONE
    ok = ok and picker.request_code not in bridge._buffer
    h.check("6. lost-result recovery: early result buffered + delivered", ok)


def test_duplicate_callback_ignored():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri

    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    ok = len(app.callbacks) == 1  # consumed exactly once
    ok = ok and len(os.listdir(app.input_dir)) == 1  # one copy only
    ok = ok and any("duplicate result" in line
                    for line in stubs.Logger.lines)
    h.check("7. duplicate callback protected (single processing)", ok)


def test_duplicate_after_forget_ignored():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    # Late duplicate callback after the picker was forgotten.
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()

    ok = len(app.callbacks) == 1
    ok = ok and len(os.listdir(app.input_dir)) == 1
    h.check("8. late duplicate after forget still ignored", ok)


def test_copy_worker_runs_off_ui_thread():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    main_thread = threading.get_ident()
    captured = {}

    orig = picker._copy_uri

    def spy(uri, index):
        captured["ident"] = threading.get_ident()
        captured["thread"] = threading.current_thread().name
        return orig(uri, index)

    picker._copy_uri = spy

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    ok = captured.get("ident") is not None
    ok = ok and captured["ident"] != main_thread  # off the UI thread
    ok = ok and len(app.callbacks) == 1
    h.check("9. URI copy runs on background worker thread", ok)


def test_status_flow_happy_path():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    expected = [
        main._PickerBridge.STATUS_IDLE,   # constructor
        main._PickerBridge.STATUS_PENDING,  # launch
        main._PickerBridge.STATUS_RESULT,   # routed result
        main._PickerBridge.STATUS_COPYING,  # worker started
        main._PickerBridge.STATUS_DONE,     # copy finished
    ]
    ok = picker.status_log == expected
    h.check("10. result-status flow: idle->pending->result->copying->done",
            ok)


def test_status_error_unreadable_uri():
    app = setup_android()
    uri = stubs._Uri("content://missing/1")  # no resolver entry
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    ok = len(app.callbacks) == 0
    ok = ok and picker.status == main._PickerBridge.STATUS_ERROR
    ok = ok and len(app.errors) >= 1
    h.check("11. unreadable URI -> status=error + user message", ok)


def test_resume_recovers_lost_picker():
    app = setup_android()
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()  # launched, but NO result ever arrives

    stubs.dispatcher.fire_resume()
    stubs.Clock.flush()  # run the 1.5s recovery scan

    ok = picker.status == main._PickerBridge.STATUS_LOST
    ok = ok and any("ပျောက်ဆုံး" in e for e in app.errors)
    ok = ok and picker.request_code not in main._PickerBridge.get()._pending
    h.check("12. lost-result recovery: resume scan marks picker lost", ok)


def test_resume_no_false_positive_when_handled():
    app = setup_android()
    uri = stubs._Uri("content://media/1")
    stubs.activity.resolver.add(uri.toString(), b"AAA", "a.jpg")
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    complete_pick(picker)

    stubs.dispatcher.fire_resume()
    stubs.Clock.flush()

    ok = picker.status == main._PickerBridge.STATUS_DONE
    ok = ok and not any("ပျောက်ဆုံး" in e for e in app.errors)
    h.check("13. resume scan does not false-positive on handled result", ok)


def test_register_before_launch():
    app = setup_android()
    picker = main.ImagePicker(app, "T", app.on_picked, multi=False)
    picker.open()

    snap_code, pending_keys = stubs.activity.launch_snapshots[0]
    ok = snap_code == picker.request_code
    ok = ok and picker.request_code in pending_keys  # registered FIRST
    h.check("14. picker registered before startActivityForResult", ok)


TESTS = [
    test_bridge_class_exists,
    test_bridge_singleton_same_instance,
    test_bind_once_app_lifetime,
    test_bind_guarded_when_android_missing,
    test_route_to_pending_picker,
    test_foreign_code_buffered_then_recovered,
    test_duplicate_callback_ignored,
    test_duplicate_after_forget_ignored,
    test_copy_worker_runs_off_ui_thread,
    test_status_flow_happy_path,
    test_status_error_unreadable_uri,
    test_resume_recovers_lost_picker,
    test_resume_no_false_positive_when_handled,
    test_register_before_launch,
]

if __name__ == "__main__":
    print("== mfs_verify.py — _PickerBridge core verification ==")
    for t in TESTS:
        h.try_run(t)
    ok = h.summary("mfs_verify.py")
    sys.exit(0 if ok else 1)
