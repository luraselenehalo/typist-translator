"""
Backend test suite (V4, WebView architecture).

Covers everything that runs in Python: the API bridge contract, the history
store, the translation core, connection pooling, i18n catalogs, the hotkey
clipboard helper and the floating overlay's placement arithmetic. No window
is opened, so this runs fast and headless.

For the UI itself see test_webview.py, which launches the real window.
"""
import inspect
import json
import re
import sys
import threading
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import about
import api_bridge
import http_pool
import i18n
import translator_core
from api_bridge import Api
from config_guard import ConfigGuard
from config_manager import DEFAULT_CONFIG, load_config, save_config
from history_store import HistoryStore
from hotkey_manager import HotkeyManager, wait_for_clipboard_change
import win_overlay
from toast_window import ToastApi, ToastHUD
from tray_manager import TrayManager

ALL_LANGS = ("th", "en", "ja", "zh-CN")

# The complete set of methods the front end is allowed to call.
EXPECTED_API = {
    "clear_history", "copy_to_clipboard", "delete_history_entry",
    "get_bootstrap", "get_history", "get_language", "minimize_to_tray",
    "minimize_window", "open_link", "quit_app", "search_languages",
    "set_hotkey", "set_service_active", "test_engine", "translate",
    "ui_ready", "update_config",
}


def make_api(config=None):
    cfg = config if config is not None else load_config()
    return Api(config=cfg,
               hotkey_manager=HotkeyManager(config=cfg),
               tray_manager=TrayManager(),
               history=HistoryStore())


def unwrap(result):
    """Every bridge method answers {'ok': bool, ...}; assert ok and return data."""
    assert isinstance(result, dict), f"not a bridge envelope: {result!r}"
    assert result.get("ok") is True, f"bridge call failed: {result.get('error')}"
    return result.get("data")


# =====================================================================
def test_bridge_envelope():
    print("[Backend 1] Bridge envelope and error handling...")
    api = make_api()

    for name in EXPECTED_API:
        method = getattr(api, name, None)
        assert callable(method), f"missing bridge method {name}"

    data = unwrap(api.get_bootstrap())
    assert isinstance(data, dict)

    # A failure must come back as data, never as an exception across the bridge.
    bad = api.update_config("not a dict")
    assert bad["ok"] is False and bad["error"], bad
    print("  -> failures return {ok: false, error} instead of raising")

    # Everything the bridge returns has to survive JSON round-tripping,
    # because that is literally what pywebview does with it.
    encoded = json.dumps(data, ensure_ascii=False)
    assert json.loads(encoded) == data
    print(f"  -> bootstrap is JSON-safe ({len(encoded)} bytes)")


def test_api_surface_is_minimal():
    print("[Backend 2] JS-visible API surface...")
    api = make_api()

    # Replicate webview.util.get_functions so this test fails if an internal
    # object ever becomes reachable from the page again.
    seen = []

    def walk(obj, base="", out=None):
        if id(obj) in seen:
            return out
        seen.append(id(obj))
        if out is None:
            out = {}
        for name in dir(obj):
            try:
                full = f"{base}.{name}" if base else name
                if name.startswith("_"):
                    continue
                attr = getattr(obj, name)
                if not getattr(attr, "_serializable", True):
                    continue
                if inspect.ismethod(attr) or inspect.isfunction(attr):
                    out[full] = True
                elif inspect.isclass(attr) or (
                    isinstance(attr, object) and not callable(attr)
                    and hasattr(attr, "__module__")
                ):
                    walk(attr, full, out)
            except Exception:
                out[f"{full}!error"] = True
        return out

    exposed = set(walk(api))
    assert exposed == EXPECTED_API, (
        f"surface drifted.\n  extra:   {sorted(exposed - EXPECTED_API)}"
        f"\n  missing: {sorted(EXPECTED_API - exposed)}")
    print(f"  -> exactly {len(exposed)} methods reachable from JavaScript")

    seen.clear()
    toast_exposed = set(walk(ToastApi(ToastHUD())))
    assert toast_exposed == {"hide_toast"}, toast_exposed
    print("  -> toast document can only call hide_toast")


def test_bootstrap_payload():
    print("[Backend 3] Bootstrap payload completeness...")
    api = make_api()
    data = unwrap(api.get_bootstrap())

    for key in ("config", "defaults", "catalogs", "uiLanguages", "engines",
                "selectionModes", "hotkeyPresets", "themes",
                "popularLanguages", "history", "serviceActive", "about"):
        assert key in data, f"bootstrap missing {key}"

    assert set(data["catalogs"]) == set(ALL_LANGS), sorted(data["catalogs"])
    assert len(data["engines"]) == len(translator_core.TRANSLATION_ENGINES)
    assert data["selectionModes"] == list(api_bridge.SELECTION_MODES)
    assert len(data["popularLanguages"]) == len(translator_core.POPULAR_LANG_CODES)

    # Every key the UI renders must exist in every catalog.
    reference = set(data["catalogs"]["th"])
    for code in ALL_LANGS:
        assert set(data["catalogs"][code]) == reference, f"{code} catalog differs"

    # Placeholders must line up, or a format() in JS silently drops a value.
    for key, thai in data["catalogs"]["th"].items():
        expected = set(re.findall(r"\{(\w+)\}", thai))
        for code in ALL_LANGS:
            got = set(re.findall(r"\{(\w+)\}", data["catalogs"][code][key]))
            assert got == expected, f"{code}/{key}: {sorted(got)} != {sorted(expected)}"

    print(f"  -> {len(reference)} keys x {len(ALL_LANGS)} languages, placeholders aligned")

    for engine in data["engines"]:
        assert {"id", "name", "needsKey", "badgeFallback", "descFallback"} <= set(engine)
    print(f"  -> {len(data['engines'])} engines, {len(data['popularLanguages'])} popular languages")


def test_config_round_trip():
    print("[Backend 4] Config patching and persistence...")
    original = load_config()
    working = dict(original)
    api = make_api(working)

    updated = unwrap(api.update_config({"selection_mode": "smart"}))
    assert updated["selection_mode"] == "smart"
    assert load_config()["selection_mode"] == "smart", "patch was not persisted"

    # Nested dictionaries merge instead of being replaced wholesale.
    unwrap(api.update_config({"engine_api_keys": {"deepl": "probe-key"}}))
    saved = load_config()
    assert saved["engine_api_keys"]["deepl"] == "probe-key"
    assert "gemini" in saved["engine_api_keys"], "sibling keys were dropped"
    print("  -> nested config patches merge rather than overwrite")

    # Switching engines must invalidate the translation memory. Pick an engine
    # that is genuinely different from whatever the user has configured -
    # patching the current engine is not a change, so nothing would be cleared
    # and the test would pass or fail depending on config.json.
    other = next(e for e in translator_core.TRANSLATION_ENGINES
                 if e != working["translation_engine"])
    translator_core._cache[("google_gtx", "th", "en", "probe")] = ("x", "th", "en")
    unwrap(api.update_config({"translation_engine": other}))
    assert len(translator_core._cache) == 0, "cache survived an engine change"
    print("  -> changing engine clears the translation cache")

    # Interface language flows through to the shared i18n module.
    unwrap(api.update_config({"app_language": "ja"}))
    assert i18n.get_language() == "ja"

    save_config(original)
    i18n.set_language(original.get("app_language", "th"))
    assert load_config()["selection_mode"] == original["selection_mode"]
    print("  -> original config restored")


def test_hotkey_registration():
    print("[Backend 5] Hotkey registration and rollback...")
    original = load_config()
    api = make_api(dict(original))

    good = unwrap(api.set_hotkey("ctrl+alt+f9"))
    assert good["registered"] is True, good
    assert api.config["hotkey"] == "ctrl+alt+f9"

    # An invalid combination must be rejected and the previous one restored,
    # otherwise a typo would leave the app with no working hotkey at all.
    bad = unwrap(api.set_hotkey("ctrl+alt+not_a_key"))
    assert bad["registered"] is False, bad
    assert api.config["hotkey"] == "ctrl+alt+f9", "config changed on a failed register"
    print(f"  -> invalid hotkey rejected: {bad['message'][:60]}")

    empty = unwrap(api.set_hotkey("  "))
    assert empty["registered"] is False
    api._hotkey_mgr.stop()

    save_config(original)
    print("  -> valid hotkey accepted, invalid one rolls back")


def test_history_store():
    print("[Backend 6] History store...")
    store = HistoryStore(max_entries=5)
    for i in range(8):
        store.add(f"ต้นฉบับ {i}", f"translation {i}", "th", "en")

    rows = store.list()
    assert len(rows) == 5, f"cap not enforced: {len(rows)}"
    assert rows[0]["translated"] == "translation 7", "not newest-first"
    assert len({r["id"] for r in rows}) == 5, "ids are not unique"
    for row in rows:
        assert {"id", "original", "translated", "source", "target", "time"} <= set(row)
    print("  -> newest first, unique ids, capped at max_entries")

    assert store.delete(rows[0]["id"]) is True
    assert store.delete(999999) is False
    assert len(store) == 4
    store.clear()
    assert len(store) == 0

    # The hotkey worker writes from its own thread while the UI reads.
    store = HistoryStore()
    errors = []

    def writer():
        try:
            for i in range(200):
                store.add(f"o{i}", f"t{i}", "th", "en")
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(200):
                store.list()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert len(store) == 200
    print("  -> concurrent writes and reads are safe")


def test_translation_paths():
    print("[Backend 7] Translation, cache and connection reuse...")
    translator_core.clear_translation_cache()
    api = make_api(dict(load_config(), translation_engine="google_gtx",
                        swap_lang_a="th", swap_lang_b="en", swap_mode="pair"))

    empty = unwrap(api.translate("   "))
    assert empty["translated"] == "" and empty["failed"] is False

    t0 = time.perf_counter()
    first = unwrap(api.translate("ขอบคุณมากครับ"))
    cold = (time.perf_counter() - t0) * 1000
    assert first["failed"] is False, first
    assert first["translated"], first
    assert first["entry"] is not None, "sandbox translation was not recorded"

    t0 = time.perf_counter()
    second = unwrap(api.translate("ขอบคุณมากครับ"))
    cached = (time.perf_counter() - t0) * 1000
    assert second["translated"] == first["translated"]
    assert cached < 20, f"cache hit took {cached:.1f} ms"
    print(f"  -> network {cold:.0f} ms vs cached {cached:.1f} ms "
          f"=> '{first['translated']}'")

    assert len(api.history) == 2, "each translation should be recorded"

    results = unwrap(api.search_languages("japan"))
    assert any(r["code"] == "ja" for r in results), results
    assert {"code", "flag", "nameTh", "nameEn"} <= set(results[0])

    http_pool.close_all()
    translator_core.translate_google_gtx("หนึ่ง", "th", "en")
    idle = sum(len(v) for v in http_pool._POOL._idle.values())
    assert idle >= 1, "no keep-alive connection was retained"
    http_pool.close_all()
    print("  -> search works and connections are pooled")


def test_translation_failure_is_language_neutral():
    print("[Backend 8] Translation failure signalling...")
    marker = f"{translator_core.TRANSLATION_ERROR_PREFIX} boom"
    assert translator_core.is_translation_error(marker)
    assert translator_core.translation_error_reason(marker) == "boom"
    assert not translator_core.is_translation_error("a normal translation")

    # The sentinel must not depend on the interface language.
    for code in ALL_LANGS:
        i18n.set_language(code)
        assert translator_core.is_translation_error(marker)
    i18n.set_language("th")
    print("  -> failures detected by a language-neutral sentinel")


def test_clipboard_wait():
    print("[Backend 9] Adaptive clipboard wait...")
    import pyperclip

    sentinel = "__SENTINEL__"
    pyperclip.copy(sentinel)

    def writer():
        time.sleep(0.01)
        pyperclip.copy("captured text")

    threading.Thread(target=writer, daemon=True).start()
    t0 = time.perf_counter()
    result = wait_for_clipboard_change(sentinel, timeout=0.6)
    elapsed = (time.perf_counter() - t0) * 1000

    assert result == "captured text", result
    assert elapsed < 60, f"waited {elapsed:.0f} ms for a 10 ms write"
    print(f"  -> returned in {elapsed:.0f} ms (the old code always slept 60 ms)")


def test_overlay_placement():
    """The chip has to land next to the text and stay on the screen."""
    print("[Backend 11] Overlay placement arithmetic...")
    work = (0, 0, 1920, 1040)
    size = (306, 56)

    left, top = win_overlay.place_rect((700, 400, "left"), size, work)
    assert (left, top) == (700, 400), (left, top)

    left, _ = win_overlay.place_rect((700, 400, "center"), size, work)
    assert left == 700 - 153, left

    # Hard against the right edge: pulled back in, never clipped off-screen.
    left, _ = win_overlay.place_rect((1900, 400, "left"), size, work)
    assert left + size[0] <= work[2], left
    assert left == 1920 - 306 - win_overlay.EDGE_MARGIN, left

    # No room underneath the caret, so it flips above it.
    _, top = win_overlay.place_rect((700, 1030, "left"), size, work)
    assert top + size[1] <= work[3], top
    assert top < 1030, top

    # A second monitor to the left has negative coordinates.
    left, top = win_overlay.place_rect((-1500, 300, "left"), size,
                                       (-1920, 0, 0, 1080))
    assert -1920 <= left and left + size[0] <= 0, (left, top)

    print(f"  -> clamped inside the work area from every direction")


def test_overlay_clip():
    print("[Backend 12] Overlay text trimming...")
    assert win_overlay.clip("  hello   world \n again ", 80) == "hello world again"
    assert win_overlay.clip(None, 10) == ""
    long_text = "ก" * 200
    trimmed = win_overlay.clip(long_text, 52)
    assert len(trimmed) == 53 and trimmed.endswith("…"), (len(trimmed), trimmed)
    print("  -> collapses whitespace and ellipsises at the limit")


def test_progress_callbacks():
    """The hotkey workflow reports its stages, and a broken listener cannot
    take translation down with it."""
    print("[Backend 13] Hotkey progress reporting...")
    config = dict(DEFAULT_CONFIG)
    seen = []
    manager = HotkeyManager(config=config,
                            on_progress_callback=lambda stage, **d: seen.append((stage, d)))
    manager._progress("reading")
    manager._progress("translating", text="สวัสดี")
    assert seen == [("reading", {}), ("translating", {"text": "สวัสดี"})], seen

    manager.on_progress_callback = None
    manager._progress("done")           # must not raise without a listener

    def explode(stage, **detail):
        raise RuntimeError("presentation layer is on fire")

    manager.on_progress_callback = explode
    manager._progress("done")           # swallowed, translation carries on
    print("  -> stages delivered; a failing listener is contained")


def test_overlay_is_opt_out():
    print("[Backend 14] Overlay preference...")
    assert DEFAULT_CONFIG["show_progress_overlay"] is True
    for code in ALL_LANGS:
        i18n.set_language(code)
        for key in ("overlay.reading", "overlay.translating", "overlay.slow",
                    "overlay.pasting", "overlay.done", "overlay.failed",
                    "overlay.no_text", "overlay.no_text_hint",
                    "settings.prefs.overlay"):
            assert i18n.t(key) != key, f"{key} missing from {code}"
    i18n.set_language("th")
    print("  -> on by default, translated in all four languages")


def test_about_links():
    """about.py is the single place the author edits, so the link building and
    the empty case both have to behave."""
    print("[Backend 15] About tab identity...")
    payload = about.payload()
    for key in ("appName", "version", "author", "alias", "license", "copyright",
                "links", "builtWith", "needsLinks", "linksFile"):
        assert key in payload, f"about payload missing {key}"
    assert payload["author"], "no author configured"
    assert payload["copyright"].endswith(payload["author"])
    json.dumps(payload)          # has to survive the bridge

    # The "these two handles are one person" line has to read correctly in
    # every interface language, and both names have to actually appear in it.
    if payload["alias"]:
        for code in ALL_LANGS:
            i18n.set_language(code)
            note = i18n.t("about.alias", author=payload["author"],
                          alias=payload["alias"])
            assert payload["author"] in note and payload["alias"] in note, \
                f"{code}: {note!r}"
            assert "{" not in note, f"{code}: unformatted placeholder in {note!r}"
        i18n.set_language("th")

    original = (about.GITHUB_USER, about.GITHUB_REPO, about.FACEBOOK_URL,
                about.CONTACT_EMAIL)
    try:
        # Nothing configured: no links at all, and the page is told to say so.
        about.GITHUB_USER = about.GITHUB_REPO = ""
        about.FACEBOOK_URL = about.CONTACT_EMAIL = ""
        assert about.links() == []
        assert about.payload()["needsLinks"] is True

        # A profile with no repository still gives one usable link.
        about.GITHUB_USER = "octocat"
        ids = [entry["id"] for entry in about.links()]
        assert ids == ["github"], ids
        assert about.github_url() == "https://github.com/octocat"

        # A full repository derives issues and releases from it.
        about.GITHUB_REPO = "typist-translator"
        about.FACEBOOK_URL = "https://facebook.com/example"
        about.CONTACT_EMAIL = "hello@example.com"
        entries = {e["id"]: e["url"] for e in about.links()}
        assert entries["github"].endswith("/octocat/typist-translator")
        assert entries["issues"].endswith("/issues")
        assert entries["releases"].endswith("/releases")
        assert entries["email"] == "mailto:hello@example.com"
        assert about.payload()["needsLinks"] is False
    finally:
        (about.GITHUB_USER, about.GITHUB_REPO, about.FACEBOOK_URL,
         about.CONTACT_EMAIL) = original

    print(f"  -> {payload['appName']} v{payload['version']} by "
          f"{payload['author']}, {payload['license']}")


def test_open_link_is_narrow():
    """The bridge hands strings to the shell, so it only accepts web links."""
    print("[Backend 16] External link guard...")
    api = make_api()
    for bad in ("javascript:alert(1)", "file:///C:/Windows/System32",
                "cmd:/c calc", "", "C:\\Windows\\notepad.exe"):
        result = unwrap(api.open_link(bad))
        assert result["opened"] is False, f"{bad!r} was allowed through"
    print("  -> javascript:, file:, cmd: and bare paths all refused")


def test_tray_follows_language():
    print("[Backend 10] Tray labels follow the interface language...")
    tray = TrayManager()
    labels = {}
    for code in ALL_LANGS:
        i18n.set_language(code)
        labels[code] = [item.text for item in tray._create_menu()]
    i18n.set_language("th")

    assert len({tuple(v) for v in labels.values()}) == len(ALL_LANGS), \
        f"tray labels did not vary by language: {labels}"
    print(f"  -> th={labels['th'][0]!r} ja={labels['ja'][0]!r} zh={labels['zh-CN'][0]!r}")


# =====================================================================
if __name__ == "__main__":
    print("=== BACKEND TEST SUITE (WebView architecture) ===\n")
    # These tests write to the real config.json on purpose - that is what the
    # app itself does - so the guard restores the user's file afterwards.
    with ConfigGuard() as guard:
        test_bridge_envelope()
        test_api_surface_is_minimal()
        test_bootstrap_payload()
        test_config_round_trip()
        test_hotkey_registration()
        test_history_store()
        test_translation_paths()
        test_translation_failure_is_language_neutral()
        test_clipboard_wait()
        test_tray_follows_language()
        test_overlay_placement()
        test_overlay_clip()
        test_progress_callbacks()
        test_overlay_is_opt_out()
        test_about_links()
        test_open_link_is_narrow()
    assert guard.unchanged(), "config.json was left modified after restore"
    print("\n  -> config.json restored byte-for-byte")
    print("\n=== ALL BACKEND TESTS PASSED ===")
