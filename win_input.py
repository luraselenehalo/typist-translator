"""
Keyboard synthesis that games can actually see.

Three different things read the keyboard on Windows, and they do not read the
same field of the same event:

* **Ordinary windows** - Edit controls, browsers, Electron apps like Discord -
  take ``WM_KEYDOWN``/``WM_CHAR`` off their message queue and use the
  **virtual key code**.
* **Games** almost always use DirectInput or Raw Input (``WM_INPUT``), and
  those read the **scan code** - the number the physical key sends. Most of
  them ignore the virtual key entirely.
* **Text fields inside games** usually take typed characters from ``WM_CHAR``,
  which is a third path again, and often the only one that works when the
  engine has not implemented Ctrl+A or Ctrl+V.

The old code called ``keybd_event(vk, 0, ...)`` - scan code **zero**. That is
fine for the first group and invisible to the second, which is exactly the
reported symptom: the app worked in Discord, LINE and Word, and did nothing at
all in a game.

Everything here is plain user-mode ``SendInput``. Nothing is injected into
another process, no memory is read or written, and no driver is involved -
which is both a design constraint and the reason this can sit alongside a game
without pretending to be a cheat. It also means an anti-cheat that filters
injected input (they can all see the ``LLKHF_INJECTED`` flag) will still ignore
it, and no amount of cleverness here changes that.
"""
import ctypes
import time
from ctypes import wintypes

# A private handle. Setting argtypes on the shared ctypes.windll.user32 changes
# it for every library in the process - pywebview included - and that has
# already broken this app once.
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC_EX = 4

ERROR_ACCESS_DENIED = 5

#: Stamped into dwExtraInfo on everything this module sends, so our own
#: keyboard hook can tell our synthetic keys from the user's real ones.
SIGNATURE = 0x54595053  # 'TYPS'

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    # All three are declared even though only the keyboard one is used: INPUT
    # has to be the full 40 bytes SendInput expects, and the mouse variant is
    # what makes it that size.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
user32.MapVirtualKeyExW.restype = wintypes.UINT
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


class InputBlocked(Exception):
    """Windows refused the keystroke, and said why.

    The usual cause is UIPI: a process at a lower integrity level cannot send
    input to a window belonging to a higher one. If the game runs as
    administrator and this app does not, every keystroke is discarded and
    ``SendInput`` reports ERROR_ACCESS_DENIED - which is worth saying out loud
    rather than looking broken.
    """


def foreground_layout():
    """The keyboard layout of whatever window has focus.

    Virtual key to scan code is layout-dependent, and the layout that matters
    is the target's, not ours - a Thai layout active in the game maps some keys
    differently from the English one this process happens to be using.
    """
    try:
        thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                                 None)
        return user32.GetKeyboardLayout(thread)
    except Exception:
        return user32.GetKeyboardLayout(0)


#: Keys that live on the E0 side of the keyboard and must carry
#: KEYEVENTF_EXTENDEDKEY. MAPVK_VK_TO_VSC_EX is documented to report these with
#: 0xE0 in the high byte, and on this machine it simply does not - VK_HOME
#: comes back as plain 0x47, which is the *numeric keypad* 7. Sending that
#: without the extended flag turns Shift+Home into Shift+Numpad7, i.e. types a
#: "7" instead of selecting the line. So the mapping is checked, and this set
#: is the backstop.
EXTENDED_KEYS = frozenset((
    0x03,  # VK_CANCEL
    0x21, 0x22,              # PageUp, PageDown
    0x23, 0x24,              # End, Home
    0x25, 0x26, 0x27, 0x28,  # arrows
    0x2C, 0x2D, 0x2E,        # PrintScreen, Insert, Delete
    0x5B, 0x5C, 0x5D,        # LWin, RWin, Apps
    0x6F,                    # Divide (numpad /)
    0x90,                    # NumLock
    0xA3, 0xA5,              # RControl, RMenu
))


def scan_code(vk, layout=None):
    """(scan, is_extended) for a virtual key."""
    mapped = user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC_EX,
                                     layout if layout is not None
                                     else foreground_layout())
    extended = (mapped >> 8) == 0xE0 or vk in EXTENDED_KEYS
    return mapped & 0xFF, extended


def _key_event(vk, scan, flags):
    """One keyboard event carrying *both* the virtual key and the scan code.

    Deliberately not KEYEVENTF_SCANCODE. That flag tells Windows to ignore wVk
    and derive the key from the scan code and the active layout, which would
    make correctness depend on which keyboard layout the target happens to have
    - and this app's users are typing Thai, so that layout is frequently not
    the English one.

    Supplying both fields and neither flag serves both readers at once: the
    message-queue path (Discord, Word, browsers) takes wVk exactly as it did
    before, and DirectInput/Raw Input consumers - games - read wScan, which
    used to be zero and is why they saw nothing at all.
    """
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0,
                          dwExtraInfo=SIGNATURE)
    return event


def _send(events):
    """Hand a batch to Windows, and complain properly if it is refused.

    One SendInput call for the whole batch, not one per key: events sent
    together are guaranteed not to be interleaved with the user's own typing,
    which is what stops a stray physical keypress landing in the middle of a
    Ctrl+A and turning it into something else.
    """
    if not events:
        return
    array = (INPUT * len(events))(*events)
    ctypes.set_last_error(0)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        error = ctypes.get_last_error()
        if error == ERROR_ACCESS_DENIED:
            raise InputBlocked(
                "Windows blocked the keystroke. The window you are typing into "
                "is running with higher privileges than this app - start "
                "Typist Translator as administrator, or run that program "
                "normally.")
        raise InputBlocked(f"SendInput accepted {sent} of {len(events)} events "
                           f"(error {error})")


#: How long a key is held down, in seconds.
#:
#: A game reads the keyboard once per frame, so a press that goes down and back
#: up between two polls is never observed at all. One frame is 33 ms at 30 fps,
#: 17 ms at 60 - and a game that is dropping frames is exactly the situation
#: where a user is most likely to be typing rather than playing. 60 ms clears a
#: 30 fps frame with room for a spike, and is still imperceptible: the whole
#: Ctrl+A / Ctrl+C / Ctrl+V sequence costs under a fifth of a second.
DEFAULT_HOLD = 0.06

#: The pause between one keystroke finishing and the next starting. Small: this
#: is only there so an application that processes keys asynchronously is not
#: handed the next one mid-flight.
DEFAULT_GAP = 0.02


def press_and_release(key_code, modifier_code=None, delay=None, hold=None,
                      gap=None):
    """Tap a key, optionally holding one modifier, with real scan codes.

    ``hold`` is how long the key stays down and ``gap`` is the pause afterwards.
    They used to be the same number, which forced a bad trade: long enough for a
    game to notice meant a needlessly slow sequence everywhere else.

    ``delay`` is the old single-knob argument, kept so existing callers and
    tests keep working; it sets the gap, and only raises the hold if it asks for
    more than the default.
    """
    if hold is None:
        hold = DEFAULT_HOLD if delay is None else max(delay, DEFAULT_HOLD)
    if gap is None:
        gap = DEFAULT_GAP if delay is None else delay

    layout = foreground_layout()
    down, up = [], []

    if modifier_code:
        scan, extended = scan_code(modifier_code, layout)
        flags = KEYEVENTF_EXTENDEDKEY if extended else 0
        down.append(_key_event(modifier_code, scan, flags))
        up.insert(0, _key_event(modifier_code, scan, flags | KEYEVENTF_KEYUP))

    scan, extended = scan_code(key_code, layout)
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0

    # The modifier goes down in the same batch as the key. Sending it
    # separately leaves a window in which the user's own typing can land
    # between the two and be swallowed by a modifier meant for us.
    _send(down + [_key_event(key_code, scan, flags)])
    time.sleep(hold)
    _send([_key_event(key_code, scan, flags | KEYEVENTF_KEYUP)] + up)
    time.sleep(gap)


#: Both sides of every modifier, explicitly. Releasing the side-agnostic
#: VK_CONTROL/VK_MENU/VK_SHIFT does *not* work: the scan code decides which
#: physical key the event describes, and those virtual keys map to the
#: left-hand scan codes - measured, the hook reports 0xA2/0xA4/0xA0. So a user
#: holding the RIGHT Ctrl, or AltGr (which is right Alt, and is how several
#: European layouts type everyday characters), kept holding it through the
#: whole translation and turned the app's Ctrl+A into Ctrl+Ctrl+A.
MODIFIER_KEYS = (
    0xA0, 0xA1,  # LShift, RShift
    0xA2, 0xA3,  # LControl, RControl
    0xA4, 0xA5,  # LMenu, RMenu (AltGr)
    0x5B, 0x5C,  # LWin, RWin
)


def release_modifiers():
    """Let go of every modifier that is actually down.

    Only the keys really being held are touched. Sending a key-up for
    something that was never pressed is usually harmless but not always - a
    game watching for the *transition* can react to it - and there is no
    reason to send it.

    One batch, and key-*up* only, so the target never sees a half-released
    state and can never read this as the start of a new chord.
    """
    layout = foreground_layout()
    events = []
    for vk in MODIFIER_KEYS:
        if not (user32.GetAsyncKeyState(vk) & 0x8000):
            continue
        scan, extended = scan_code(vk, layout)
        flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if extended else 0)
        events.append(_key_event(vk, scan, flags))
    try:
        _send(events)
    except InputBlocked:
        # Nothing useful to do here; the caller's first real keystroke will
        # raise and be reported properly.
        pass
    return [event.ki.wVk for event in events]


def type_text(text, chunk=16, chunk_pause=0.004):
    """Type text as characters rather than pasting it.

    ``KEYEVENTF_UNICODE`` posts the character itself instead of a key position,
    so it needs no keyboard layout and can produce Thai, Japanese or Chinese on
    a machine set to any layout. It arrives as ``WM_CHAR``, which is how game
    text fields take input - so this reaches boxes that never implemented
    Ctrl+V, which is most of them.

    It is slower than pasting and it cannot be undone by the target's own
    Ctrl+Z as one step, so it is the fallback, not the default.

    Characters outside the BMP are two UTF-16 code units; both are sent as
    ordinary events and Windows recombines them.
    """
    units = text.encode("utf-16-le")
    events = []
    for index in range(0, len(units), 2):
        code = units[index] | (units[index + 1] << 8)
        events.append(_key_event(0, code, KEYEVENTF_UNICODE))
        events.append(_key_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

    # In batches: one enormous SendInput can overflow the target's input queue
    # and silently drop the tail, and a pause lets a game's per-frame reader
    # keep up.
    for start in range(0, len(events), chunk * 2):
        _send(events[start:start + chunk * 2])
        if chunk_pause:
            time.sleep(chunk_pause)


# =====================================================================
# Diagnostics
# =====================================================================
def foreground_process():
    """(pid, executable name) of the window that has focus, for diagnostics.

    "It does not work in my game" is unanswerable without this. Knowing the
    process lets the app say which application refused the keystroke.
    """
    pid = wintypes.DWORD()
    hwnd = user32.GetForegroundWindow()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    if pid.value:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid.value)
        if handle:
            try:
                buffer = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(512)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                       ctypes.byref(size)):
                    name = buffer.value.rsplit("\\", 1)[-1]
            finally:
                kernel32.CloseHandle(handle)
    return pid.value, name
