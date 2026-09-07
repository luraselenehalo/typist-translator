"""
Live check: the floating windows must not appear in Alt+Tab or the taskbar.

The chip, the toast and the update card are overlays. They were showing up as
three extra "Typist" entries in the Alt+Tab switcher, most of them blank,
because WinForms puts WS_EX_APPWINDOW on every form it shows and APPWINDOW
*beats* WS_EX_TOOLWINDOW - so ORing TOOLWINDOW in was never enough.

This opens the real windows the same way main.py does, then asks Windows what
it actually did with them. The arithmetic alone is covered in test_backend.py;
this is the part that can only be answered by the operating system.

    python test_alttab.py
"""
import ctypes
import functools
import os
import sys
import threading
from ctypes import wintypes

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

print = functools.partial(print, flush=True)  # noqa: A001

import webview

import win_overlay
from overlay_window import ProgressOverlay
from toast_window import ToastHUD
from update_window import UpdatePanel

user32 = ctypes.WinDLL("user32", use_last_error=True)
_GetLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_GetLong.argtypes = [wintypes.HWND, ctypes.c_int]
_GetLong.restype = ctypes.c_ssize_t

GWL_EXSTYLE = -20
GWL_STYLE = -16
GW_OWNER = 4
WS_VISIBLE = 0x10000000

#: Windows the shell creates for us and that are none of our business.
IGNORED_CLASSES = ("IME", "MSCTFIME UI", "GDI+ Hook Window Class")

failures = []


def own_windows():
    """Every top-level window belonging to this process."""
    me = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != me:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in IGNORED_CLASSES or cls.value.startswith(".NET-Broadcast"):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        found.append({
            "hwnd": hwnd,
            "title": title.value,
            "class": cls.value,
            "ex": _GetLong(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF,
            "style": _GetLong(hwnd, GWL_STYLE) & 0xFFFFFFFF,
            "owner": user32.GetWindow(hwnd, GW_OWNER),
        })
        return True

    user32.EnumWindows(collect, 0)
    return found


def in_alt_tab(window):
    """Windows' own rule for switcher membership.

    A visible top-level window is listed when it carries WS_EX_APPWINDOW, or
    when it is unowned and is not a tool window.
    """
    if not window["style"] & WS_VISIBLE:
        return False
    if window["ex"] & win_overlay.WS_EX_APPWINDOW:
        return True
    return not window["owner"] and not window["ex"] & win_overlay.WS_EX_TOOLWINDOW


def describe(window):
    names = []
    for bit, name in (
        (win_overlay.WS_EX_APPWINDOW, "APPWINDOW"),
        (win_overlay.WS_EX_TOOLWINDOW, "TOOLWINDOW"),
        (win_overlay.WS_EX_NOACTIVATE, "NOACTIVATE"),
        (win_overlay.WS_EX_LAYERED, "LAYERED"),
        (win_overlay.WS_EX_TRANSPARENT, "TRANSPARENT"),
    ):
        if window["ex"] & bit:
            names.append(name)
    return ",".join(names) or "-"


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{' - ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def main():
    toast = ToastHUD()
    overlay = ProgressOverlay()
    panel = UpdatePanel()

    main_window = webview.create_window(
        "Typist AltTab Probe", html="<body style='background:#111'></body>",
        width=420, height=200, hidden=False)
    toast.create()
    overlay.create()
    panel.create()

    def on_started():
        try:
            toast.mark_ready()
            overlay.mark_ready()
            panel.mark_ready()

            print("\n[1] After startup - every overlay is parked and hidden")
            for window in own_windows():
                listed = in_alt_tab(window)
                is_probe = window["title"] == "Typist AltTab Probe"
                print(f"      {window['title']!r:28} [{describe(window)}]"
                      f" alt-tab={'YES' if listed else 'no'}")
                if not is_probe:
                    check(f"{window['title']!r} stays out of Alt+Tab", not listed,
                          f"exstyle=0x{window['ex']:08X}")
            check("the main window is still reachable",
                  any(w["title"] == "Typist AltTab Probe" and in_alt_tab(w)
                      for w in own_windows()))

            # The real question: the shell decides when a window is *shown*.
            print("\n[2] While the chip and the update card are on screen")
            overlay.show_working("probe", preview="checking", tag="test",
                                 theme="dark")
            panel.offer("9.9.9", "probe release notes", theme="dark")
            threading.Event().wait(0.7)
            for window in own_windows():
                if window["title"] == "Typist AltTab Probe":
                    continue
                visible = bool(window["style"] & WS_VISIBLE)
                listed = in_alt_tab(window)
                print(f"      {window['title']!r:28} visible={str(visible):5}"
                      f" [{describe(window)}] alt-tab={'YES' if listed else 'no'}")
                check(f"{window['title']!r} stays out of Alt+Tab while shown",
                      not listed, f"exstyle=0x{window['ex']:08X}")
        except Exception as exc:  # noqa: BLE001 - the report matters, not the trace
            import traceback
            traceback.print_exc()
            failures.append(f"probe crashed: {exc}")
        finally:
            for window in (panel, overlay, toast):
                try:
                    window.destroy()
                except Exception:
                    pass
            try:
                main_window.destroy()
            except Exception:
                pass

    print("=== ALT+TAB EXCLUSION PROBE ===")
    webview.start(on_started, private_mode=False)

    print()
    if failures:
        print(f"=== {len(failures)} FAILURE(S) ===")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("=== PASSED: no overlay window is offered to Alt+Tab ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
