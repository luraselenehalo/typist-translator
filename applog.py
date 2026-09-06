"""
Somewhere for the app to say what happened.

A windowed build has no console: ``sys.stdout`` is ``None``, so every ``print``
in the codebase becomes a silent no-op and an exception during start-up is
completely invisible - the user sees an icon that does nothing and has nothing
to report. This redirects the existing prints to a rotating file and puts a
visible message box in front of a crash that would otherwise be silent.

Nothing else in the project has to change: ``install()`` replaces ``sys.stdout``
and ``sys.stderr``, so the ``print`` calls already scattered through the modules
end up in the log without being rewritten.
"""
import datetime
import os
import sys
import threading
import traceback

import paths

LOG_NAME = "typist.log"
MAX_BYTES = 512 * 1024
KEEP = 2


def log_path() -> str:
    return paths.user_data("logs", LOG_NAME)


class _Tee:
    """Writes to the log file, and to the original stream when there is one."""

    def __init__(self, path, passthrough=None, stamp=True):
        self._path = path
        self._passthrough = passthrough
        self._stamp = stamp
        self._lock = threading.Lock()
        self._at_line_start = True

    def write(self, text):
        if self._passthrough is not None:
            try:
                self._passthrough.write(text)
            except Exception:
                pass
        if not text:
            return len(text)
        with self._lock:
            try:
                self._rotate_if_needed()
                with open(self._path, "a", encoding="utf-8", errors="replace") as f:
                    for piece in text.splitlines(keepends=True):
                        if self._stamp and self._at_line_start and piece.strip():
                            f.write(f"{_now()} {piece}")
                        else:
                            f.write(piece)
                        self._at_line_start = piece.endswith("\n")
            except Exception:
                # Logging must never be the reason the app falls over.
                pass
        return len(text)

    def flush(self):
        if self._passthrough is not None:
            try:
                self._passthrough.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def _rotate_if_needed(self):
        try:
            if os.path.getsize(self._path) < MAX_BYTES:
                return
        except OSError:
            return
        for index in range(KEEP, 0, -1):
            older = f"{self._path}.{index}"
            newer = f"{self._path}.{index - 1}" if index > 1 else self._path
            try:
                if os.path.exists(newer):
                    os.replace(newer, older)
            except OSError:
                return


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def install(header=""):
    """Point stdout and stderr at the log file. Safe to call more than once."""
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return None

    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(path, passthrough=sys.__stdout__)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(path, passthrough=sys.__stderr__)

    print("")
    print(f"===== {header or 'start'} =====")
    return path


def show_crash(exc: BaseException):
    """Put a silent start-up failure in front of the user.

    Without this a windowed build that throws during start-up simply never
    appears, and there is nothing on screen to say why or where to look.
    """
    detail = "".join(traceback.format_exception(type(exc), exc,
                                                exc.__traceback__))
    print(detail)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Typist Translator could not start.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"The full details are in:\n{log_path()}",
            "Typist Translator", 0x10)   # MB_ICONERROR
    except Exception:
        pass
