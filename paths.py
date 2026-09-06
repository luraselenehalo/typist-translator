"""
Where things live, whether the app runs from source or from a frozen .exe.

Two kinds of file, and they must not be confused:

* **Resources** - the UI bundle, the icons. Read-only, shipped with the app. When frozen
  they are unpacked into PyInstaller's temporary ``sys._MEIPASS`` directory, which is a
  different place every launch and is deleted on exit.
* **User data** - ``config.json`` and anything else the app writes. It holds the user's
  hotkey, language pair and API keys, so it has to survive an update that replaces every
  file in the install directory. That rules out keeping it next to the executable.

Running from source, both answer the project folder, so development behaves exactly as
before and the test suites keep pointing at the repository's own ``config.json``.
"""
import os
import sys

#: True when running from a PyInstaller build rather than from .py sources.
FROZEN = bool(getattr(sys, "frozen", False))

#: The folder the sources live in. Also the fallback for everything else.
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

#: The folder holding the running executable, once frozen. Where the installer puts the
#: app, and what an updater replaces.
INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else PROJECT_DIR

APP_FOLDER_NAME = "TypistTranslator"


def resource_dir() -> str:
    """Where the bundled read-only files were unpacked."""
    if FROZEN:
        # onefile unpacks to _MEIPASS; onedir sets it to the executable's folder.
        return getattr(sys, "_MEIPASS", INSTALL_DIR)
    return PROJECT_DIR


def resource(*parts) -> str:
    """Path to a file that ships with the app, e.g. resource('ui', 'dist', 'index.html')."""
    return os.path.join(resource_dir(), *parts)


def user_data_dir() -> str:
    """Where the app may write, and where its settings survive an update.

    ``%APPDATA%\\TypistTranslator`` once installed; the project folder when running from
    source, so a checkout keeps using the ``config.json`` that sits beside it.
    """
    if not FROZEN:
        return PROJECT_DIR
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    directory = os.path.join(base, APP_FOLDER_NAME)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        # An unwritable APPDATA is not worth crashing over; fall back to the exe folder
        # and let the caller fail on the actual read or write instead.
        return INSTALL_DIR
    return directory


def user_data(*parts) -> str:
    """Path to a file the app owns and writes, e.g. user_data('config.json')."""
    return os.path.join(user_data_dir(), *parts)


def describe() -> dict:
    """Everything above in one dictionary, for diagnostics and the About tab."""
    return {
        "frozen": FROZEN,
        "executable": sys.executable,
        "installDir": INSTALL_DIR,
        "resourceDir": resource_dir(),
        "userDataDir": user_data_dir(),
    }
