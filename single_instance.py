"""
One running copy, and one only.

Two things make this necessary rather than nice to have:

* The app registers a **global** hotkey. Two copies means two hooks on the same
  combination, so one keypress runs the whole select-copy-translate-paste
  workflow twice, racing each other over the clipboard.
* The self-update deliberately opens a window of a few seconds with no process
  running, while the Desktop shortcut, the Start Menu entry and the
  ``HKCU\\...\\Run`` value all still point at the app. A click in that window
  would leave a second copy running when the installer relaunches the first.

A named kernel mutex is the right primitive: Windows destroys it when the
process dies, however it dies, so a crash cannot leave a stale lock behind the
way a lock *file* would.
"""
import ctypes
from ctypes import wintypes

# Global\\ would be per-machine; Local\\ (the default) is per-session, which is
# what we want - two different signed-in users may each run their own copy.
MUTEX_NAME = "TypistTranslator.SingleInstance.v1"

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
SW_SHOW = 5

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]


class SingleInstance:
    """Holds the mutex for as long as this process lives."""

    def __init__(self, name=MUTEX_NAME):
        self.name = name
        self._handle = None
        self.already_running = False

    def acquire(self) -> bool:
        """True if we are the only copy. False if another one already has it."""
        try:
            self._handle = kernel32.CreateMutexW(None, True, self.name)
            self.already_running = (
                ctypes.get_last_error() == ERROR_ALREADY_EXISTS)
            if self.already_running:
                # Creating an existing mutex still returns a handle; close ours
                # so the other process's ownership is the only one left.
                self.release()
                return False
            return bool(self._handle)
        except Exception as exc:
            # A failure here must never stop the app from starting - the worst
            # case without the guard is the old behaviour.
            print(f"[SingleInstance] Could not take the lock: {exc}")
            return True

    def release(self):
        if self._handle:
            try:
                kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    def __enter__(self):
        self.acquired = self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()
        return False


def activate_existing(window_title="Typist Translator") -> bool:
    """Bring the copy that is already running to the front.

    Launching the app a second time should feel like clicking its taskbar
    button, not like nothing happened - which is what the user sees if the
    first copy is sitting minimised in the tray.
    """
    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
