"""
Win32 plumbing shared by the floating windows (progress chip, toast HUD).

The rule both of them have to obey: never take focus. They appear while the
user is typing in another application, and the hotkey workflow that put them
there is about to send Ctrl+A / Ctrl+C / Ctrl+V to whatever is focused. A
window that activates itself would swallow those keystrokes, and after the
translation it would swallow the user's next keypress too.

pywebview's own ``window.show()`` cannot be used for this: it calls
``Form.Show()`` followed by ``Form.Activate()``, which is exactly focus theft.
Everything here drives the HWND directly instead.

Two Windows quirks worth knowing, both measured rather than assumed:

* A WebView2 that has been through WinForms' ``Hide()`` never composites
  again until WinForms shows it - it comes back as a blank white rectangle.
  So these windows are created *visible but off-screen* and are hidden with
  ``SetWindowPos(SWP_HIDEWINDOW)``, which the renderer recovers from.
* Click-through needs ``WS_EX_TRANSPARENT`` *and* ``WS_EX_LAYERED`` together.
  With WS_EX_TRANSPARENT alone, WindowFromPoint still returns the window's own
  WebView2 child and the click is swallowed.
"""
import ctypes
import threading
import time
from ctypes import wintypes

# A PRIVATE user32 handle, not ctypes.windll.user32.
#
# ctypes.windll caches one object per DLL for the whole process, and argtypes
# set on it are shared with every other module. Declaring them on the cached
# instance made pywebview's own SetWindowPos calls fail ("argument 5: NoneType
# cannot be interpreted as an integer"), which left the WebView2 child unsized
# and every overlay painted blank white. WinDLL builds a fresh instance, so
# these prototypes stay ours.
user32 = ctypes.WinDLL("user32", use_last_error=True)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


# 64-bit handles do not survive ctypes' default c_int return type.
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF,
                                              ctypes.c_ubyte, wintypes.DWORD]
user32.GetLayeredWindowAttributes.argtypes = [wintypes.HWND,
                                              ctypes.POINTER(wintypes.COLORREF),
                                              ctypes.POINTER(ctypes.c_ubyte),
                                              ctypes.POINTER(wintypes.DWORD)]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND

_GetWindowLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_SetWindowLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLong.restype = ctypes.c_ssize_t
_SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_SetWindowLong.restype = ctypes.c_ssize_t

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
LWA_ALPHA = 0x00000002
MONITOR_DEFAULTTONEAREST = 2

# Placement
CARET_GAP = 22        # px below the caret, clear of most text cursors
EDGE_MARGIN = 12
BOTTOM_INSET = 118    # how far above a window's bottom edge to sit in fallback

# The window is parked here between appearances, far outside any real desktop.
PARK_X = -4000
PARK_Y = -4000


# =====================================================================
# Window handling
# =====================================================================
#: How long to wait for a pywebview window to actually exist.
HWND_WAIT_SECONDS = 6.0


def find_window(title, timeout=0.0, poll=0.02):
    """The handle for a window title, optionally waiting for it to appear."""
    deadline = time.perf_counter() + timeout
    while True:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        if time.perf_counter() >= deadline:
            return None
        time.sleep(poll)


def wait_for_window(window, title, timeout=HWND_WAIT_SECONDS):
    """Block until pywebview has actually shown ``window``, then find its HWND.

    pywebview runs its ``start`` callback as soon as the GUI loop is up, which
    is not the same moment as the secondary windows being realised - so looking
    the window up by title straight away is a race.

    It was first written as a timed poll, and that is not good enough: on a
    loaded machine the poll ran out and the chip, the toast and the update card
    were left disabled for the entire session, with the only sign being one
    line printed to a console a windowed app does not have. Waiting on
    pywebview's own ``shown`` event waits for the actual thing instead of
    guessing how long it takes.
    """
    try:
        window.events.shown.wait(timeout)
    except Exception:
        # Older pywebview, or a window that never gets the event. Fall back to
        # the poll rather than giving up.
        return find_window(title, timeout=timeout)
    # The event fires as the window is shown; the handle is there by now, but
    # allow a beat for it to be registered under its title.
    return find_window(title, timeout=2.0)


def apply_overlay_styles(hwnd, click_through=False):
    """Never activate, never show in the taskbar, optionally pass clicks on.

    ``click_through`` is for windows the user should be able to click *past* -
    the progress chip sits right where they are typing. The toast is meant to
    be clickable, so it leaves it off.

    ``WS_EX_APPWINDOW`` has to be cleared, not merely out-voted. WinForms sets
    it on every form it shows, and it *beats* WS_EX_TOOLWINDOW: a window
    carrying both is still listed. Leaving it on put the chip, the toast and
    the update card in Alt+Tab and on the taskbar as three extra "Typist"
    entries with nothing in them.
    """
    style = _GetWindowLong(hwnd, GWL_EXSTYLE)
    style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    style &= ~WS_EX_APPWINDOW
    if click_through:
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    _SetWindowLong(hwnd, GWL_EXSTYLE, style)
    # The shell samples these styles when a window is shown, so a window that
    # is already visible keeps the taskbar button it was given at birth. Every
    # caller creates its window visible - hiding it here is what makes the
    # change stick, and each of them parks the window off-screen immediately
    # afterwards anyway.
    hide(hwnd)


def make_layered(hwnd, alpha=255):
    """Opt into layered-window alpha so the window can be faded from Python."""
    _SetWindowLong(hwnd, GWL_EXSTYLE,
                   _GetWindowLong(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED)
    set_alpha(hwnd, alpha)


def show_at(hwnd, left, top, width, height):
    """Show at a position without ever touching the foreground window."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(left), int(top),
                        int(width), int(height),
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)


def hide(hwnd):
    """Hide with SetWindowPos, never Form.Hide() - see the module docstring."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_HIDEWINDOW | SWP_NOACTIVATE)


def is_visible(hwnd):
    return bool(hwnd and user32.IsWindowVisible(hwnd))


def set_alpha(hwnd, alpha):
    user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, int(alpha))),
                                      LWA_ALPHA)


def get_alpha(hwnd):
    alpha = ctypes.c_ubyte(0)
    try:
        user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), None)
    except Exception:
        return 0
    return alpha.value


def fade(hwnd, target, duration_ms, still_current, on_finished=None):
    """Tween layered alpha on a worker thread.

    A handful of SetLayeredWindowAttributes calls, and none of them touch the
    WebView2 UI thread, so this cannot slow the hotkey path down.
    ``still_current`` is called before every step: return False to abandon the
    fade, which is how a newly triggered translation cancels the old one's.
    """
    def run():
        steps = max(1, int(duration_ms / 16))
        start = get_alpha(hwnd)
        for step in range(1, steps + 1):
            if not still_current():
                return
            try:
                set_alpha(hwnd, start + (target - start) * (step / steps))
            except Exception:
                return
            time.sleep(0.016)
        if on_finished and still_current():
            on_finished()

    threading.Thread(target=run, daemon=True).start()


def dpi_scale(hwnd):
    try:
        return user32.GetDpiForWindow(hwnd) / 96.0
    except Exception:
        return 1.0


def round_corners(hwnd):
    """Windows 11 rounded corners.

    Cheaper and better looking than a transparent WebView2 surface: the OS
    draws the rounding and the drop shadow, and pywebview stops warning about
    cross-thread WebView2 property access.
    """
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        preference = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference), ctypes.sizeof(preference))
    except Exception:
        pass


# =====================================================================
# Placement
# =====================================================================
def monitor_work_area(x, y):
    """(left, top, right, bottom) usable area of the monitor holding (x, y)."""
    try:
        handle = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                         MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if handle and user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            work = info.rcWork
            return work.left, work.top, work.right, work.bottom
    except Exception:
        pass
    return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def focus_anchor(chip_width, chip_height):
    """Best guess at where the text being translated is, in screen pixels.

    Returns ``(x, y, align, source)``. ``y`` is where the top of the chip
    should go and ``align`` says whether ``x`` is the chip's left edge or its
    centre. ``source`` names which rule fired, which is what the diagnostics
    print.

    The rules, in order of how much they actually know:

    1. The caret rectangle, when the focused control publishes one. Exact.
    2. The focused child control, when it is a real sub-window rather than one
       big client area. Its bottom-left is right under the text.
    3. Otherwise the window is a single Chromium/Electron surface (Discord,
       LINE, Slack, a browser) and Windows will not say where the caret is. It
       is a chat app, so the box being typed in is near the bottom: centre the
       chip horizontally and sit it above the bottom edge. A guess, but a
       consistent one, and always over the window the user is looking at.
    """
    foreground = user32.GetForegroundWindow()
    if not foreground:
        _, _, right, bottom = monitor_work_area(0, 0)
        return (right - chip_width - EDGE_MARGIN,
                bottom - chip_height - EDGE_MARGIN, "left", "screen")

    gui = GUITHREADINFO()
    gui.cbSize = ctypes.sizeof(GUITHREADINFO)
    thread_id = user32.GetWindowThreadProcessId(foreground, None)
    focused = None
    if thread_id and user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui)):
        caret = gui.rcCaret
        if gui.hwndCaret and (caret.bottom - caret.top) > 0:
            point = wintypes.POINT(caret.left, caret.bottom)
            if user32.ClientToScreen(gui.hwndCaret, ctypes.byref(point)):
                return (point.x - 6, point.y + CARET_GAP, "left", "caret")
        focused = gui.hwndFocus

    window = wintypes.RECT()
    user32.GetWindowRect(foreground, ctypes.byref(window))

    if focused and focused != foreground:
        control = wintypes.RECT()
        if user32.GetWindowRect(focused, ctypes.byref(control)):
            control_area = ((control.right - control.left) *
                            (control.bottom - control.top))
            window_area = max(1, (window.right - window.left) *
                              (window.bottom - window.top))
            if 0 < control_area < window_area * 0.6:
                return (control.left, control.bottom + 8, "left", "control")

    centre_x = (window.left + window.right) // 2
    return (centre_x, window.bottom - BOTTOM_INSET, "center", "window")


def place_rect(anchor, size, work):
    """Clamp a chip of ``size`` near ``anchor`` into the ``work`` rectangle.

    Pure arithmetic, kept apart from the Win32 calls so it can be tested
    without a window on screen.
    """
    x, y, align = anchor[0], anchor[1], anchor[2]
    width, height = size
    work_left, work_top, work_right, work_bottom = work

    left = x - width // 2 if align == "center" else x
    top = y
    if top + height > work_bottom:
        # No room below the text: sit above it instead of hanging off-screen.
        above = y - height - CARET_GAP - 4
        top = above if above >= work_top else work_bottom - height

    left = max(work_left + EDGE_MARGIN,
               min(left, work_right - width - EDGE_MARGIN))
    top = max(work_top + EDGE_MARGIN,
              min(top, work_bottom - height - EDGE_MARGIN))
    return int(left), int(top)


def foreground_work_area():
    """Usable area of the monitor holding whatever window has focus.

    Not the primary monitor. Plenty of people keep a game on a second screen
    and chat on the first, and a notification about that game belongs on the
    screen they are looking at. On a single-monitor machine this answers
    exactly what monitor_work_area(0, 0) did.
    """
    try:
        handle = user32.MonitorFromWindow(user32.GetForegroundWindow(),
                                          MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if handle and user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            work = info.rcWork
            return work.left, work.top, work.right, work.bottom
    except Exception:
        pass
    return monitor_work_area(0, 0)


def bottom_right(width, height, margin_x=24, margin_y=64):
    """Where a corner notification goes, on the screen the user is using."""
    left, top, right, bottom = foreground_work_area()
    return (max(left, right - width - margin_x),
            max(top, bottom - height - margin_y))


def clip(text, limit):
    """One line of at most ``limit`` characters, ellipsised."""
    text = " ".join((text or "").replace("\n", " ").replace("\r", " ").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
