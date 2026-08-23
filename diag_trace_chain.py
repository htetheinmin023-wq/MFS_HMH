"""diag_trace_chain.py — end-to-end picker trace chain diagnostic.

Simulates the full production flow on Android with stubs:
    _open_android -> bridge.launch -> startActivityForResult
    -> on_activity_result -> _route -> _on_bridge_result
    -> _parse_intent -> _copy_worker (bg thread) -> _finish_copy
    -> callback -> result screen

and asserts every hop of the chain (15 checks), printing a trace
diagram with PASS markers and counting exceptions.

Run:  python3 diag_trace_chain.py
"""

import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _test_stubs as stubs

stubs.install()

import main  # noqa: E402

RESULT_OK = -1
h = stubs.Harness()

TRACE = []


def hop(name, cond, detail=""):
    """Record one trace-chain hop: PASS/FAIL marker."""
    h.check(name, cond, detail)
    TRACE.append((name, bool(cond)))


def run_chain():
    stubs.reset_env()
    main.platform = "android"
    app = stubs.FakeApp(stubs.tmpdir)

    uri = stubs._Uri("content://media/trace1")
    stubs.activity.resolver.add(
        uri.toString(), b"\x89PNG-trace-bytes", "trace.png", "image/png")

    # ---- app startup: bridge binds once ----
    bridge = main._PickerBridge.get(app)
    bridge.bind()
    hop("startup: app-lifetime listener bound",
        bridge._bound and stubs.dispatcher.bind_calls == 2)

    # ---- _open_android ----
    picker = main.ImagePicker(app, "Trace", app.on_picked, multi=False)
    picker.open()
    hop("_open_android: launched via bridge",
        len(stubs.activity.started) == 1
        and stubs.activity.started[0][1] == picker.request_code)

    snap_code, pending_keys = stubs.activity.launch_snapshots[0]
    hop("bridge.launch: registered before startActivityForResult",
        snap_code == picker.request_code
        and picker.request_code in pending_keys)

    hop("_open_android: status -> pending",
        picker.status == main._PickerBridge.STATUS_PENDING)

    # ---- activity result arrives (user picked an image) ----
    main_thread = threading.get_ident()
    worker_ident = {"id": None}
    orig_copy = picker._copy_uri

    def spy(uri_, index_):
        worker_ident["id"] = threading.get_ident()
        return orig_copy(uri_, index_)

    # Spy installed BEFORE firing so the worker thread always sees it.
    picker._copy_uri = spy

    intent = stubs._Intent("x")
    intent._data = uri
    stubs.dispatcher.fire_activity_result(
        picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    hop("on_activity_result -> _route: routed to picker",
        main._PickerBridge.STATUS_RESULT in picker.status_log)

    # Status transitions are recorded in status_log; the live status
    # may already have advanced if the (very fast) copy worker finished
    # inside the flush loop — assert on the recorded flow instead.
    hop("_on_bridge_result: status -> copying",
        main._PickerBridge.STATUS_COPYING in picker.status_log
        and picker._copy_thread is not None)

    # ---- copy worker (background) ----
    deadline = time.time() + 5.0
    while worker_ident["id"] is None and time.time() < deadline:
        time.sleep(0.005)
    hop("_copy_worker: URI copy on background thread",
        worker_ident["id"] is not None
        and worker_ident["id"] != main_thread)

    stubs.wait_thread(picker._copy_thread)
    hop("_copy_worker: completed", picker._copy_thread is not None
        and not picker._copy_thread.is_alive())

    # ---- _finish_copy on Kivy thread ----
    stubs.Clock.flush()
    hop("_finish_copy: status -> done",
        picker.status == main._PickerBridge.STATUS_DONE)

    hop("callback: result screen got the image",
        len(app.callbacks) == 1 and len(app.callbacks[0]) == 1)

    path = app.callbacks[0][0] if app.callbacks else None
    hop("file copied to app storage with exact bytes",
        path is not None and os.path.exists(path)
        and stubs.read_file(path) == b"\x89PNG-trace-bytes")

    hop("bridge cleaned up (forget)",
        picker.request_code not in bridge._pending)

    # ---- duplicate protection at the chain end ----
    stubs.dispatcher.fire_activity_result(
        picker.request_code, RESULT_OK, intent)
    stubs.Clock.flush()
    hop("duplicate callback at chain end ignored",
        len(app.callbacks) == 1
        and any("duplicate result" in line for line in stubs.Logger.lines))

    # ---- full status flow ----
    expected = [
        main._PickerBridge.STATUS_IDLE,
        main._PickerBridge.STATUS_PENDING,
        main._PickerBridge.STATUS_RESULT,
        main._PickerBridge.STATUS_COPYING,
        main._PickerBridge.STATUS_DONE,
    ]
    hop("status flow: idle->pending->result->copying->done",
        picker.status_log == expected)

    # ---- trace markers appear in log order ----
    log = "\n".join(stubs.Logger.lines)
    markers = [
        "app-lifetime listener bound",
        "picker_bridge: launched code=%d" % picker.request_code,
        "status=result",
        "status=copying",
        "status=done",
        "%d file(s) ready" % 1,
    ]
    pos = -1
    ordered = True
    for m in markers:
        p = log.find(m)
        if p < 0 or p <= pos:
            ordered = False
            break
        pos = p
    hop("trace log markers in correct order", ordered)

    return app, picker


if __name__ == "__main__":
    print("== diag_trace_chain.py — full picker trace chain ==")
    h.try_run(run_chain)
    ok = h.summary("diag_trace_chain.py")

    # Trace diagram
    print()
    print("Full flow trace:")
    for name, passed in TRACE:
        print("  %s %s" % ("[OK]" if passed else "[X ]", name))
    print("_open_android -> bridge -> route -> handle -> copy -> "
          "scan_selected -> face_scan -> result screen")

    sys.exit(0 if ok else 1)
