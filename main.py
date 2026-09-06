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
import subprocess
import sys
import threading
import time

# Ensure UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import webview

import about
import applog
import i18n
import paths
import single_instance
import update_state
import updater
from api_bridge import Api
from config_manager import load_config
from history_store import HistoryStore
from hotkey_manager import HotkeyManager
from overlay_window import ProgressOverlay, clip
from toast_window import ToastHUD
from tray_manager import TrayManager
from update_window import UpdatePanel

UI_ENTRY = paths.resource("ui", "dist", "index.html")
ICON_ICO = paths.resource("icon.ico")

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

# Long enough after start-up that the check never competes with the first paint
# or the user's first hotkey press.
UPDATE_CHECK_DELAY_SECONDS = 60

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


class UpdateFlow:
    """Check, offer, download, hand over.

    Everything here runs on background threads so a slow or unreachable GitHub
    can never stall the window, and every step is wrapped: a failed update has
    to leave a working application behind.
    """

    def __init__(self, config, panel, theme_of, on_quit):
        self._config = config
        self._panel = panel
        self._theme_of = theme_of
        self._on_quit = on_quit
        self._offer = None
        self._busy = False

    # -- checking -----------------------------------------------------
    def start_background_check(self):
        if not self._config.get("check_for_updates", True):
            return
        threading.Thread(target=self._delayed_check, daemon=True).start()

    def _delayed_check(self):
        time.sleep(UPDATE_CHECK_DELAY_SECONDS)
        self.check(force=False, announce_when_current=False)

    def check(self, force=False, announce_when_current=True):
        """Returns a small dict the Settings tab can show. Never raises."""
        try:
            found = updater.check(force=force)
        except updater.UpdateError as exc:
            print(f"[Update] check failed: {exc}")
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            print(f"[Update] check failed unexpectedly: {exc}")
            return {"status": "error", "message": str(exc)}

        if not found:
            return {"status": "current", "version": about.VERSION}

        self._offer = found
        print(f"[Update] {found['version']} is available")
        try:
            self._panel.offer(found["version"], found.get("notes", ""),
                              theme=self._theme_of())
        except Exception as exc:
            print(f"[Update] could not show the notification: {exc}")
        return {"status": "available", "version": found["version"]}

    # -- the buttons on the card --------------------------------------
    def on_choice(self, action):
        if action == "later":
            self._panel.hide()
        elif action == "skip":
            if self._offer:
                update_state.write(skipped_version=self._offer["version"])
            self._panel.hide()
        elif action == "page":
            self._open_releases()
            self._panel.hide()
        elif action == "install":
            if self._busy:
                return
            threading.Thread(target=self._install, daemon=True).start()

    def _open_releases(self):
        try:
            import webbrowser
            webbrowser.open(updater.RELEASES_PAGE)
        except Exception:
            pass

    # -- downloading and handing over ---------------------------------
    def _install(self):
        self._busy = True
        try:
            offer = self._offer
            if not offer:
                return
            if not updater.can_self_install():
                # A copy run from source or unzipped by hand has nothing for
                # the installer to upgrade. Say so instead of doing nothing.
                self._panel.failed(i18n.t("update.portable_only"),
                                   theme=self._theme_of())
                return

            installer = updater.download(offer["asset"], on_progress=self._progress)
            update_state.write(pending_version=offer["version"],
                               pending_installer=installer,
                               pending_notes=offer.get("notes", "")[:8000],
                               latest_seen=offer["version"])
            self._panel.installing()
            time.sleep(1.2)          # let the user read it before we vanish

            command = updater.install_command(
                installer, language=self._config.get("app_language", "en"))
            print(f"[Update] handing over to {command[0]}")
            # DETACHED so the installer outlives us: it has to wait for this
            # process to exit before it can replace the files we are running.
            subprocess.Popen(
                command,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                close_fds=True)
            time.sleep(0.4)
            self._on_quit()
        except updater.UpdateError as exc:
            print(f"[Update] {exc}")
            self._panel.failed(str(exc), theme=self._theme_of())
        except Exception as exc:
            print(f"[Update] unexpected failure: {exc}")
            self._panel.failed(str(exc), theme=self._theme_of())
        finally:
            self._busy = False

    def _progress(self, received, total):
        try:
            self._panel.progress(received, total)
        except Exception:
            pass


def _consume_whats_new():
    """If this launch followed an update, hand the notes to the UI once.

    The relaunch comes from the installer with --updated, but the flag alone is
    not trusted: the recorded pending version has to actually match what is
    running now, so a stale marker cannot pop the panel open forever.
    """
    state = update_state.read()
    pending = state.get("pending_version") or ""
    just_updated = "--updated" in sys.argv or (
        pending and pending == about.VERSION)
    if not just_updated:
        return None
    notes = state.get("pending_notes") if "pending_notes" in state else ""
    update_state.clear_pending()
    update_state.write(launched_version=about.VERSION)
    return {"version": about.VERSION, "notes": notes or ""}


def main():
    print("[Main] Starting Typist Translator (WebView UI)...")

    # One copy only. Two would put two hooks on the same global hotkey, so a
    # single keypress would run the whole workflow twice and the two copies
    # would race over the clipboard.
    guard = single_instance.SingleInstance()
    if not guard.acquire():
        print("[Main] Already running - bringing the existing window forward.")
        single_instance.activate_existing()
        return 0

    _set_app_identity()

    if not os.path.exists(UI_ENTRY):
        print(f"[Main] UI bundle missing: {UI_ENTRY}")
        print("[Main] Build it first:  cd ui && npm install && npm run build")
        return 1

    config = load_config()
    i18n.set_language(config.get("app_language", i18n.DEFAULT_LANGUAGE))
    whats_new = _consume_whats_new()
    if whats_new:
        print(f"[Main] Updated to {whats_new['version']}")

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
              tray_manager=tray_mgr, history=history, whats_new=whats_new)

    toast = ToastHUD()
    overlay = ProgressOverlay()
    update_panel = UpdatePanel()
    updates = UpdateFlow(config=config, panel=update_panel,
                         theme_of=lambda: _resolved_theme(config),
                         on_quit=lambda: shutdown())
    update_panel.on_choice = updates.on_choice
    api.attach_updates(updates)

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
    update_panel.create()

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
        update_panel.destroy()
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
        update_panel.mark_ready()
        updates.start_background_check()
        print("[Main] Typist Translator running successfully.")

    webview.start(on_started, private_mode=False, debug=_debug_enabled(),
                  icon=ICON_ICO if os.path.exists(ICON_ICO) else None)
    shutdown()
    return 0


def _debug_enabled():
    return os.environ.get("TYPIST_DEBUG", "").lower() in ("1", "true", "yes")


if __name__ == "__main__":
    sys.exit(main())
