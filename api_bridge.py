"""
API Bridge - the contract between the Python backend and the React front end.

Every public method here is callable from JavaScript as
``window.pywebview.api.<name>(...)`` and must therefore:

* accept and return only JSON-serialisable values,
* never raise across the boundary (a Python traceback becomes an unhelpful
  rejected promise in JS), so each entry point returns {"ok": ...} shaped data,
* never block the UI thread for long - anything that touches the network is
  called from JS with await and runs on pywebview's own worker thread.

Events travel the other way (Python -> JS) through ``push_event``, which the
hotkey worker uses to deliver a finished translation without the UI polling.
"""
import json
import threading
import time
import traceback

import about
import i18n
from config_manager import DEFAULT_CONFIG, save_config
from history_store import HistoryStore
from translator_core import (
    LANGUAGES_DB, POPULAR_LANG_CODES, TRANSLATION_ENGINES,
    clear_translation_cache, is_translation_error, search_languages,
    test_engine_connection, translate_text, translation_error_reason,
)

SELECTION_MODES = ("all", "smart", "line", "selection")
HOTKEY_PRESETS = ["ctrl+alt+t", "f8", "f9", "ctrl+q", "alt+t",
                  "ctrl+shift+t", "ctrl+space"]
THEMES = ("System", "Dark", "Light")


def _safe(fn):
    """Wrap a bridge method so exceptions come back as data, not a rejection."""
    def wrapper(*args, **kwargs):
        try:
            return {"ok": True, "data": fn(*args, **kwargs)}
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Api:
    def __init__(self, config, hotkey_manager, tray_manager, history=None):
        # Everything here is underscore-prefixed on purpose: pywebview walks
        # dir(js_api) to build the JS bridge and recurses into public
        # non-callable attributes, which would both expose these internals to
        # the page and make it read WebView2 COM properties off the UI thread.
        self._config = config
        self._hotkey_mgr = hotkey_manager
        self._tray_mgr = tray_manager
        self._history = history or HistoryStore()

        self._window = None
        self._on_quit = None
        self._lock = threading.Lock()

        # Set once the front end has rendered its first interactive frame.
        self._ready = threading.Event()
        self._started_at = time.perf_counter()
        self._ready_ms = None

    # -- Python-side accessors (not reachable from JavaScript) ---------
    @property
    def config(self):
        return self._config

    @property
    def history(self):
        return self._history

    @property
    def ready_ms(self):
        return self._ready_ms

    def wait_until_ready(self, timeout=None):
        """Block until the front end reports its first interactive frame."""
        return self._ready.wait(timeout)

    # -----------------------------------------------------------------
    # Wiring (called from Python, not JS)
    # -----------------------------------------------------------------
    def attach_window(self, window, on_quit=None):
        self._window = window
        self._on_quit = on_quit

    def push_event(self, name, payload=None):
        """Deliver an event to the front end. Safe to call from any thread."""
        window = self._window
        if window is None:
            return
        try:
            message = json.dumps({"name": name, "payload": payload},
                                 ensure_ascii=False)
            window.evaluate_js(
                f"window.__typistEvent && window.__typistEvent({message})")
        except Exception as exc:
            print(f"[Api] Could not push '{name}' event: {exc}")

    # These three are for Python callers only; pywebview skips any attribute
    # marked non-serializable when it builds the JS bridge.
    attach_window._serializable = False
    push_event._serializable = False
    wait_until_ready._serializable = False

    # -----------------------------------------------------------------
    # Bootstrap
    # -----------------------------------------------------------------
    @_safe
    def ui_ready(self):
        """Called by the front end once it has painted its first real frame.

        Gives an honest startup number and lets anything waiting on the UI
        (tests, the launcher) block on a real signal instead of polling the
        page, which would compete with the page's own calls into this API.
        """
        if self._ready_ms is None:
            self._ready_ms = (time.perf_counter() - self._started_at) * 1000
            print(f"[Api] UI interactive in {self._ready_ms:.0f} ms")
        self._ready.set()
        return {"ready": True, "ms": self._ready_ms}

    @_safe
    def get_bootstrap(self):
        """Everything the UI needs to render its first frame, in one call."""
        return {
            "config": dict(self._config),
            "defaults": dict(DEFAULT_CONFIG),
            "catalogs": i18n.CATALOG,
            "uiLanguages": [
                {"code": code, "native": meta["native"],
                 "english": meta["english"], "flag": meta["flag"]}
                for code, meta in i18n.UI_LANGUAGES.items()
            ],
            "engines": [
                {"id": engine_id, "name": meta["name"],
                 "needsKey": bool(meta.get("needs_key")),
                 "badgeFallback": meta.get("badge", ""),
                 "descFallback": meta.get("desc", "")}
                for engine_id, meta in TRANSLATION_ENGINES.items()
            ],
            "selectionModes": list(SELECTION_MODES),
            "hotkeyPresets": list(HOTKEY_PRESETS),
            "themes": list(THEMES),
            "popularLanguages": [self._language_entry(c)
                                 for c in POPULAR_LANG_CODES
                                 if c in LANGUAGES_DB],
            "history": self._history.list(),
            "serviceActive": bool(self._hotkey_mgr.is_active),
            "about": about.payload(),
        }

    @staticmethod
    def _language_entry(code):
        info = LANGUAGES_DB.get(code, {})
        return {"code": code, "flag": info.get("flag", "🌐"),
                "nameTh": info.get("name_th", code),
                "nameEn": info.get("name_en", code)}

    @_safe
    def get_language(self, code):
        return self._language_entry(code)

    # -----------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------
    @_safe
    def update_config(self, patch):
        """Merge a partial config from the UI, persist it, and apply it."""
        if not isinstance(patch, dict):
            raise TypeError("patch must be an object")

        with self._lock:
            engine_changed = ("translation_engine" in patch
                              and patch["translation_engine"]
                              != self._config.get("translation_engine"))
            model_changed = "engine_models" in patch or "openai_base_url" in patch

            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(self._config.get(key), dict):
                    self._config[key].update(value)
                else:
                    self._config[key] = value

            save_config(self._config)
            self._hotkey_mgr.update_config(self._config)

        if engine_changed or model_changed:
            # Cached results belong to the old engine/model pairing.
            clear_translation_cache()

        if "app_language" in patch:
            i18n.set_language(patch["app_language"])
            self._tray_mgr.refresh_labels()

        return dict(self._config)

    @_safe
    def set_hotkey(self, hotkey):
        """Register a new global hotkey. Returns whether it was accepted."""
        cleaned = (hotkey or "").strip().lower()
        if not cleaned:
            return {"registered": False, "message": "empty hotkey"}
        ok, message = self._hotkey_mgr.register_hotkey(cleaned)
        if ok:
            with self._lock:
                self._config["hotkey"] = cleaned
                save_config(self._config)
        else:
            # Put the previously working hotkey back so the app stays usable.
            self._hotkey_mgr.register_hotkey(self._config.get("hotkey", "ctrl+alt+t"))
        return {"registered": ok, "message": message}

    @_safe
    def set_service_active(self, active):
        active = bool(active)
        self._hotkey_mgr.set_active(active)
        self._tray_mgr.set_service_active(active)
        return {"active": active}

    # -----------------------------------------------------------------
    # Translation
    # -----------------------------------------------------------------
    @_safe
    def translate(self, text):
        """Sandbox translation. Runs on pywebview's worker thread."""
        text = (text or "").strip()
        if not text:
            return {"translated": "", "source": "auto", "target": "auto",
                    "failed": False}

        translated, source, target = translate_text(text, config=self._config)
        failed = is_translation_error(translated)

        # A successful sandbox translation is recorded like a hotkey one, so
        # history is a complete record of everything the app translated.
        entry = None
        if not failed and translated:
            entry = self._history.add(text, translated, source, target)

        return {
            "translated": "" if failed else translated,
            "reason": translation_error_reason(translated) if failed else "",
            "source": source,
            "target": target,
            "failed": failed,
            "entry": entry,
        }

    @_safe
    def test_engine(self, engine_id):
        ok, message, latency = test_engine_connection(engine_id, self._config)
        return {"ok": ok, "message": message, "latency": latency}

    @_safe
    def search_languages(self, query, limit=40):
        results = search_languages(query or "", limit=int(limit))
        return [{"code": r["code"], "flag": r["flag"],
                 "nameTh": r["name_th"], "nameEn": r["name_en"]}
                for r in results]

    # -----------------------------------------------------------------
    # History
    # -----------------------------------------------------------------
    @_safe
    def get_history(self):
        return self._history.list()

    @_safe
    def delete_history_entry(self, entry_id):
        return {"deleted": self._history.delete(int(entry_id))}

    @_safe
    def clear_history(self):
        self._history.clear()
        return {"cleared": True}

    # -----------------------------------------------------------------
    # Window / system
    # -----------------------------------------------------------------
    @_safe
    def copy_to_clipboard(self, text):
        import pyperclip
        pyperclip.copy(text or "")
        return {"copied": True}

    @_safe
    def open_link(self, url):
        """Open a link from the About tab in the user's real browser.

        Without this an <a href> would navigate the application window itself
        to the site and there would be no way back - the window has no address
        bar and no Back button.

        Only http, https and mailto are accepted. The page is our own bundle,
        but a bridge method that hands arbitrary strings to the shell is worth
        keeping narrow whatever the caller is.
        """
        import webbrowser

        url = (url or "").strip()
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme not in ("http", "https", "mailto"):
            return {"opened": False, "reason": f"refused scheme {scheme!r}"}
        webbrowser.open(url)
        return {"opened": True}

    @_safe
    def minimize_to_tray(self):
        if self._window is not None:
            self._window.hide()
        return {"hidden": True}

    @_safe
    def minimize_window(self):
        if self._window is not None:
            self._window.minimize()
        return {"minimized": True}

    @_safe
    def quit_app(self):
        if self._on_quit:
            self._on_quit()
        return {"quitting": True}
