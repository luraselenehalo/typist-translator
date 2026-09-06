"""
Typist Translator - Main Entry Point

Architecture
------------
    React (ui/dist/index.html)          rendered by WebView2
              |  window.pywebview.api   -> api_bridge.Api
              |  window.__typistEvent   <- Api.push_event
    Python backend
        hotkey_manager   global hotkey + select/copy/translate/paste workflow
        overlay_window   "translating..." chip pinned above every window
        toast_window     the result notification in the corner
        win_overlay      Win32 shared by both floating windows
        translator_core  five engines, language detection, translation memory
        http_pool        keep-alive connections
        history_store    translation history (written from the hotkey thread)
        tray_manager     system tray icon
        i18n             interface language catalogs, shared with the front end
        about            author, links and version, for the About tab

Only the presentation layer is web. Everything that talks to Windows - the
keyboard hook, clipboard injection, the tray icon and the floating windows -
runs in Python.
"""
import os
import sys

# Ensure UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import webview

import i18n
from api_bridge import Api
from config_manager import load_config
from history_store import HistoryStore
from hotkey_manager import HotkeyManager
from overlay_window import ProgressOverlay, clip
from toast_window import ToastHUD
from tray_manager import TrayManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_ENTRY = os.path.join(BASE_DIR, "ui", "dist", "index.html")
ICON_ICO = os.path.join(BASE_DIR, "icon.ico")

# Windows groups taskbar buttons by AppUserModelID. Without one, a script run
# by python.exe inherits Python's identity - Python's icon, and Python's
# taskbar group. Setting our own gives the app its own button and lets the
# user pin it.
APP_USER_MODEL_ID = "ResinCore.TypistTranslator.4"

WINDOW_WIDTH = 940
WINDOW_HEIGHT = 780
MIN_WIDTH = 720
MIN_HEIGHT = 560

# How much of the text fits on the overlay chip's second line.
PREVIEW_CHARS = 52

# The chip's tag has room for one word. Full names are in TRANSLATION_ENGINES;
# these are just short enough to fit, and unambiguous - "Google Translate" and
# "Google Gemini AI" would both shorten to "Google".
ENGINE_SHORT_NAMES = {
    "google_gtx": "Google",
    "mymemory": "MyMemory",
    "deepl": "DeepL",
    "gemini": "Gemini",
    "openai": "LLM",
}


def _set_app_identity():
    """Claim a distinct taskbar identity before any window is created."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID)
    except Exception as exc:
        print(f"[Main] Could not set AppUserModelID: {exc}")


def _resolved_theme(config):
    """'System' resolved against Windows' own light/dark setting."""
    mode = config.get("appearance_mode", "System")
    if mode in ("Dark", "Light"):
        return mode.lower()
    try:
        import darkdetect
        return "dark" if darkdetect.isDark() else "light"
    except Exception:
        return "light"


def main():
    print("[Main] Starting Typist Translator (WebView UI)...")
    _set_app_identity()

    if not os.path.exists(UI_ENTRY):
        print(f"[Main] UI bundle missing: {UI_ENTRY}")
        print("[Main] Build it first:  cd ui && npm install && npm run build")
        return 1

    config = load_config()
    i18n.set_language(config.get("app_language", i18n.DEFAULT_LANGUAGE))

    history = HistoryStore()
    hotkey_mgr = HotkeyManager(config=config)
    state = {"quitting": False}

    # --- tray ------------------------------------------------------------
    def on_show_window():
        window = state.get("window")
        if window is None:
            return
        try:
            window.show()
            window.restore()
            window.on_top = True
            window.on_top = False
        except Exception:
            pass

    def on_toggle_service(active):
        hotkey_mgr.set_active(active)

    def on_quit():
        shutdown()

    tray_mgr = TrayManager(on_show_window=on_show_window,
                           on_toggle_service=on_toggle_service,
                           on_quit=on_quit)

    api = Api(config=config, hotkey_manager=hotkey_mgr,
              tray_manager=tray_mgr, history=history)

    toast = ToastHUD()
    overlay = ProgressOverlay()

    def engine_name():
        engine_id = config.get("translation_engine", "")
        return ENGINE_SHORT_NAMES.get(engine_id, engine_id)

    # --- hotkey callbacks ------------------------------------------------
    def on_text_translated(original_text, translated_text, source_lang, target_lang):
        """Runs on the hotkey worker thread."""
        entry = history.add(original_text, translated_text, source_lang, target_lang)
        api.push_event("translated", entry)
        if config.get("show_toast_notification", True):
            toast.show(original_text, translated_text, source_lang, target_lang,
                       theme=_resolved_theme(config))

    def on_progress(stage, **detail):
        """Drive the floating chip from the hotkey worker thread.

        The overlay is the only feedback the user gets between pressing the
        hotkey and the text changing, so it reports every stage - including
        the failures, which used to happen in complete silence.
        """
        if not config.get("show_progress_overlay", True):
            return
        theme = _resolved_theme(config)
        if stage == "reading":
            overlay.show_working(i18n.t("overlay.reading"), preview="",
                                 tag=engine_name(), theme=theme)
        elif stage == "translating":
            overlay.update(label=i18n.t("overlay.translating"),
                           preview=clip(detail.get("text"), PREVIEW_CHARS))
        elif stage == "pasting":
            overlay.update(label=i18n.t("overlay.pasting"),
                           preview=clip(detail.get("text"), PREVIEW_CHARS))
        elif stage == "done":
            overlay.finish(True, i18n.t("overlay.done"),
                           preview=clip(detail.get("translated"), PREVIEW_CHARS))
        elif stage == "failed":
            if detail.get("kind") == "no_text":
                label, reason = (i18n.t("overlay.no_text"),
                                 i18n.t("overlay.no_text_hint"))
            else:
                label, reason = (i18n.t("overlay.failed"),
                                 clip(detail.get("reason"), PREVIEW_CHARS))
            overlay.finish(False, label, preview=reason)

    def on_status_changed(active):
        tray_mgr.set_service_active(active)
        api.push_event("status", {"active": bool(active)})

    hotkey_mgr.on_translated_callback = on_text_translated
    hotkey_mgr.on_status_change_callback = on_status_changed
    hotkey_mgr.on_progress_callback = on_progress

    # --- windows ---------------------------------------------------------
    window = webview.create_window(
        "Typist Translator",
        url=UI_ENTRY,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        background_color="#0A0E1A" if _resolved_theme(config) == "dark" else "#F4F6FB",
        hidden=bool(config.get("start_minimized", False)),
        text_select=False,
    )
    state["window"] = window
    toast.create()
    overlay.create()

    def shutdown():
        if state["quitting"]:
            return
        state["quitting"] = True
        print("[Main] Shutting down...")
        try:
            hotkey_mgr.stop()
        except Exception:
            pass
        try:
            tray_mgr.stop()
        except Exception:
            pass
        try:
            import http_pool
            http_pool.close_all()
        except Exception:
            pass
        overlay.destroy()
        toast.destroy()
        try:
            window.destroy()
        except Exception:
            pass

    api.attach_window(window, on_quit=shutdown)

    def on_closing():
        """X button: hide to tray instead of exiting, when configured to."""
        if config.get("minimize_to_tray_on_close", True) and not state["quitting"]:
            window.hide()
            return False
        shutdown()
        return True

    window.events.closing += on_closing

    def on_started():
        hotkey_mgr.start()
        tray_mgr.start()
        toast.mark_ready()
        overlay.mark_ready()
        print("[Main] Typist Translator running successfully.")

    webview.start(on_started, private_mode=False, debug=_debug_enabled(),
                  icon=ICON_ICO if os.path.exists(ICON_ICO) else None)
    shutdown()
    return 0


def _debug_enabled():
    return os.environ.get("TYPIST_DEBUG", "").lower() in ("1", "true", "yes")


if __name__ == "__main__":
    sys.exit(main())
