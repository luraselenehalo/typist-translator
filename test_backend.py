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
import win_input
import win_overlay
from toast_window import ToastApi, ToastHUD
from tray_manager import TrayManager

ALL_LANGS = ("th", "en", "ja", "zh-CN")

# The complete set of methods the front end is allowed to call.
EXPECTED_API = {
    "clear_history", "copy_to_clipboard", "delete_history_entry",
    "check_for_updates", "dismiss_whats_new", "get_bootstrap", "get_history",
    "get_language", "minimize_to_tray", "minimize_window", "open_link",
    "quit_app", "search_languages", "set_hotkey", "set_service_active",
    "set_undo_hotkey", "test_engine", "translate", "ui_ready", "update_config",
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
                "popularLanguages", "history", "serviceActive", "about",
                "whatsNew"):
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

    # Connection reuse needs one real request. Google's gtx endpoint is
    # unofficial and rate-limits by IP, so a developer who has just run this
    # suite a few times gets a 429 - which says nothing about the pool. Any
    # answered request proves the point, so fall back to the other free engine
    # and only give up if the whole network is unavailable.
    http_pool.close_all()
    reached = None
    for attempt in (lambda: translator_core.translate_google_gtx("หนึ่ง", "th", "en"),
                    lambda: translator_core.translate_mymemory("หนึ่ง", "th", "en")):
        try:
            attempt()
            reached = True
            break
        except Exception as exc:
            print(f"     (engine unavailable: {str(exc)[:60]})")
    if reached:
        idle = sum(len(v) for v in http_pool._POOL._idle.values())
        assert idle >= 1, "no keep-alive connection was retained"
        print("  -> search works and connections are pooled")
    else:
        print("  -> search works; pooling not checked (no engine reachable)")
    http_pool.close_all()


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
# Engine fallback
# =====================================================================
def test_fallback_reaches_a_second_free_engine():
    """Google failing must reach MyMemory, not Google again.

    The old code fell back to Google unconditionally - so when Google was the
    chosen engine, which is the default, a rate-limited endpoint failed twice
    and gave up with MyMemory sitting there unused.
    """
    print("[TEST] engine fallback chain")
    translator_core.clear_translation_cache()
    translator_core.reset_engine_cooldowns()
    calls = []

    def dead_google(text, source, target):
        calls.append("google_gtx")
        raise RuntimeError("429 rate limited")

    def live_mymemory(text, source, target):
        calls.append("mymemory")
        return ("MYMEMORY", source, target)

    original = (translator_core.translate_google_gtx,
                translator_core.translate_mymemory)
    translator_core.translate_google_gtx = dead_google
    translator_core.translate_mymemory = live_mymemory
    try:
        report = {}
        text, _src, _tgt = translator_core.translate_text(
            "สวัสดี", config={"translation_engine": "google_gtx"}, report=report)
    finally:
        (translator_core.translate_google_gtx,
         translator_core.translate_mymemory) = original
        translator_core.clear_translation_cache()
        translator_core.reset_engine_cooldowns()

    assert text == "MYMEMORY", f"fallback did not produce a translation: {text!r}"
    assert calls == ["google_gtx", "mymemory"], f"wrong chain: {calls}"
    assert report["engine"] == "mymemory", report
    assert report["fell_back"] is True, report
    print(f"  -> {' -> '.join(calls)}, reported engine={report['engine']}")


def test_fallback_never_spends_money():
    """A failure must not silently bill the user's DeepL or OpenAI account."""
    print("[TEST] fallbacks are key-less engines only")
    for engine in ("google_gtx", "mymemory", "deepl", "gemini", "openai"):
        chain = translator_core.engine_chain(engine)
        assert chain[0] == engine, f"{engine} is not tried first: {chain}"
        for fallback in chain[1:]:
            assert fallback in translator_core.FREE_FALLBACKS, \
                f"{engine} would fall back to the paid engine {fallback}"
        assert len(chain) == len(set(chain)), f"duplicate attempt in {chain}"
    print("  -> every chain tries the choice first, then free engines only")


def test_missing_api_key_is_not_an_attempt():
    """A keyed engine with no key falls straight through to a free one."""
    print("[TEST] a keyless paid engine falls through")
    translator_core.clear_translation_cache()
    translator_core.reset_engine_cooldowns()
    seen = []

    def google(text, source, target):
        seen.append("google_gtx")
        return ("GOOGLE", source, target)

    original = translator_core.translate_google_gtx
    translator_core.translate_google_gtx = google
    try:
        report = {}
        text, _s, _t = translator_core.translate_text(
            "hello", config={"translation_engine": "deepl",
                             "engine_api_keys": {"deepl": ""}}, report=report)
    finally:
        translator_core.translate_google_gtx = original
        translator_core.clear_translation_cache()
        translator_core.reset_engine_cooldowns()

    assert text == "GOOGLE", text
    assert seen == ["google_gtx"], seen
    assert any("deepl" in err for err in report["errors"]), report
    print(f"  -> deepl skipped ({report['errors'][0]}), google answered")


def test_failed_engine_goes_to_the_back():
    """A dead engine must not be retried first on every later translation."""
    print("[TEST] engine cooldown")
    translator_core.clear_translation_cache()
    translator_core.reset_engine_cooldowns()
    order = []

    def dead_google(text, source, target):
        order.append("google_gtx")
        raise RuntimeError("still down")

    def live_mymemory(text, source, target):
        order.append("mymemory")
        return ("OK", source, target)

    original = (translator_core.translate_google_gtx,
                translator_core.translate_mymemory)
    translator_core.translate_google_gtx = dead_google
    translator_core.translate_mymemory = live_mymemory
    try:
        cfg = {"translation_engine": "google_gtx"}
        translator_core.translate_text("one", config=cfg)
        first_round = list(order)
        order.clear()
        translator_core.translate_text("two", config=cfg)
        second_round = list(order)
    finally:
        (translator_core.translate_google_gtx,
         translator_core.translate_mymemory) = original
        translator_core.clear_translation_cache()
        translator_core.reset_engine_cooldowns()

    assert first_round == ["google_gtx", "mymemory"], first_round
    assert second_round == ["mymemory"], \
        f"the dead engine was tried first again: {second_round}"
    print(f"  -> round 1 {first_round}, round 2 {second_round}")


# =====================================================================
# Clipboard and undo
# =====================================================================
class FakeDesktop:
    """Stands in for the focused text box and the Windows clipboard.

    Every call the hotkey manager makes to the real desktop is redirected
    here, so the paste and undo sequences can be exercised end to end without
    a single synthetic keystroke reaching the machine running the tests.
    """

    def __init__(self, field=""):
        self.field = field
        self.selected = False
        self.clipboard = ""

    def press_and_release(self, key_code, modifier_code=None, delay=0.03):
        import hotkey_manager as hm
        if modifier_code == hm.VK_CONTROL and key_code == hm.VK_A:
            self.selected = True
        elif modifier_code == hm.VK_SHIFT and key_code == hm.VK_HOME:
            self.selected = True
        elif modifier_code == hm.VK_CONTROL and key_code == hm.VK_C:
            if self.selected:
                self.clipboard = self.field
        elif modifier_code == hm.VK_CONTROL and key_code == hm.VK_V:
            self.field = self.clipboard if self.selected else self.field + self.clipboard
            self.selected = False

    def copy(self, text, retries=4, delay=0.025):
        self.clipboard = text
        return True

    def paste(self, retries=4, delay=0.025):
        return self.clipboard

    def wait_for_change(self, sentinel, timeout=0.35, poll=0.008):
        return self.clipboard

    def install(self, monkey):
        import hotkey_manager as hm
        monkey(hm, "press_and_release", self.press_and_release)
        monkey(hm, "safe_clipboard_copy", self.copy)
        monkey(hm, "safe_clipboard_paste", self.paste)
        monkey(hm, "wait_for_clipboard_change", self.wait_for_change)
        monkey(hm, "wait_modifiers_released", lambda timeout=0.25: None)


class _Patcher:
    """Minimal monkeypatch with automatic restore."""

    def __init__(self):
        self._undo = []

    def __call__(self, module, name, value):
        self._undo.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        for module, name, original in reversed(self._undo):
            setattr(module, name, original)
        return False


def _manager(**overrides):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({"sound_effect": False, "key_delay_ms": 0})
    cfg.update(overrides)
    return HotkeyManager(config=cfg)


def test_clipboard_is_given_back():
    """A translation must not eat what the user had copied.

    Reading the selection goes through the clipboard, and the old code only
    restored it when the translation *failed* - so copying a link, translating
    one message and pasting the link somewhere else pasted the translation.
    """
    print("[TEST] the clipboard survives a translation")
    with _Patcher() as monkey:
        desktop = FakeDesktop()
        desktop.install(monkey)
        manager = _manager()

        desktop.clipboard = "https://example.com/important"
        manager._restore_clipboard_later("https://example.com/important",
                                         "the translation", delay=0.01)
        desktop.clipboard = "the translation"
        time.sleep(0.20)
        assert desktop.clipboard == "https://example.com/important", \
            f"clipboard not restored: {desktop.clipboard!r}"

        # ...but never over something copied in the meantime.
        manager._restore_clipboard_later("old value", "the translation",
                                         delay=0.01)
        desktop.clipboard = "something the user copied just now"
        time.sleep(0.20)
        assert desktop.clipboard == "something the user copied just now", \
            f"clobbered a newer clipboard: {desktop.clipboard!r}"

        # Opting out leaves the translation there on purpose.
        manager.config["restore_clipboard"] = False
        desktop.clipboard = "the translation"
        manager._restore_clipboard_later("old value", "the translation",
                                         delay=0.01)
        time.sleep(0.15)
        assert desktop.clipboard == "the translation", desktop.clipboard
    print("  -> restored, never clobbers a newer copy, and is opt-out")


def test_undo_restores_the_original():
    print("[TEST] undo puts the original text back")
    with _Patcher() as monkey:
        desktop = FakeDesktop(field="Hello, nice to work with you.")
        desktop.install(monkey)
        manager = _manager()
        stages = []
        manager.on_progress_callback = lambda stage, **d: stages.append(stage)
        manager._last_paste = {
            "original": "สวัสดีครับ ยินดีที่ได้ร่วมงานกันครับ",
            "translated": "Hello, nice to work with you.",
            "selection_mode": "all",
            "at": time.time(),
        }
        manager._execute_undo()
        assert desktop.field == "สวัสดีครับ ยินดีที่ได้ร่วมงานกันครับ", \
            f"undo did not restore: {desktop.field!r}"
        assert "undone" in stages, stages
        assert manager._last_paste is None, "undo memory was not consumed"

        stages.clear()
        manager._execute_undo()
        assert stages == ["failed"], stages
    print("  -> original restored, memory consumed, second press is a no-op")


def test_undo_refuses_when_the_text_moved_on():
    """Refusing is a far cheaper mistake than overwriting."""
    print("[TEST] undo refuses to overwrite newer text")
    import hotkey_manager as hm
    with _Patcher() as monkey:
        desktop = FakeDesktop(field="Hello, nice to work with you. And more!")
        desktop.install(monkey)
        manager = _manager()
        failures = []
        manager.on_progress_callback = lambda stage, **d: (
            failures.append(d.get("kind")) if stage == "failed" else None)
        manager._last_paste = {
            "original": "ต้นฉบับ",
            "translated": "Hello, nice to work with you.",
            "selection_mode": "all",
            "at": time.time(),
        }
        manager._execute_undo()
        assert desktop.field == "Hello, nice to work with you. And more!", \
            f"undo destroyed newer text: {desktop.field!r}"
        assert failures == ["undo_changed"], failures

        # An expired record is refused too, without touching the field.
        manager._last_paste = {
            "original": "ต้นฉบับ",
            "translated": "Hello, nice to work with you. And more!",
            "selection_mode": "all",
            "at": time.time() - hm.UNDO_MEMORY_SECONDS - 1,
        }
        failures.clear()
        manager._execute_undo()
        assert failures == ["no_undo"], failures
        assert desktop.field == "Hello, nice to work with you. And more!"
    print("  -> refused on changed text and on an expired record")


def test_undo_hotkey_does_not_unbind_translation():
    """Both hotkeys must survive a rebind - one used to wipe the other."""
    print("[TEST] both hotkeys stay bound")
    manager = _manager(hotkey="ctrl+alt+t", undo_hotkey="ctrl+alt+z")
    manager.start()
    try:
        assert manager.current_hotkey_ref is not None, "translate hotkey lost"
        assert manager.undo_registered, f"undo not bound: {manager.undo_error}"

        # A clash must lose the *undo* binding, never the translation.
        manager.update_config({**manager.config, "undo_hotkey": "ctrl+alt+t"})
        assert manager.current_hotkey_ref is not None, "translate hotkey lost"
        assert not manager.undo_registered, "undo bound over the translate key"

        # Emptying the field switches undo off cleanly.
        manager.update_config({**manager.config, "undo_hotkey": ""})
        assert manager.current_hotkey_ref is not None
        assert not manager.undo_registered
    finally:
        manager.stop()
    print("  -> translate survives a clash and an empty undo hotkey")


def test_overlay_windows_stay_out_of_alt_tab():
    """WS_EX_APPWINDOW has to be cleared, not merely out-voted.

    WinForms sets it on every form it shows and it beats WS_EX_TOOLWINDOW, so
    the chip, the toast and the update card appeared in Alt+Tab as three empty
    "Typist" entries.
    """
    print("[TEST] overlay windows are excluded from Alt+Tab")
    written = {}
    with _Patcher() as monkey:
        # WinForms leaves the window carrying APPWINDOW and a caption.
        start = win_overlay.WS_EX_APPWINDOW | 0x00000100
        monkey(win_overlay, "_GetWindowLong", lambda hwnd, index: start)
        monkey(win_overlay, "_SetWindowLong",
               lambda hwnd, index, value: written.update(style=value))
        hidden = []
        monkey(win_overlay, "hide", lambda hwnd: hidden.append(hwnd))

        win_overlay.apply_overlay_styles(1234, click_through=False)
        style = written["style"]
        assert not style & win_overlay.WS_EX_APPWINDOW, \
            f"APPWINDOW survived: 0x{style:08X}"
        assert style & win_overlay.WS_EX_TOOLWINDOW, f"0x{style:08X}"
        assert style & win_overlay.WS_EX_NOACTIVATE, f"0x{style:08X}"
        assert not style & win_overlay.WS_EX_TRANSPARENT, f"0x{style:08X}"
        assert hidden == [1234], "the window was not re-hidden for the shell"

        win_overlay.apply_overlay_styles(1234, click_through=True)
        style = written["style"]
        assert style & win_overlay.WS_EX_TRANSPARENT, f"0x{style:08X}"
        assert style & win_overlay.WS_EX_LAYERED, f"0x{style:08X}"
        assert not style & win_overlay.WS_EX_APPWINDOW, f"0x{style:08X}"
    print("  -> APPWINDOW cleared, TOOLWINDOW and NOACTIVATE set")


# =====================================================================
# Keyboard synthesis
# =====================================================================
def test_keystrokes_carry_a_real_scan_code():
    """The bug that made the app useless in every game.

    ``keybd_event(vk, 0, ...)`` sends scan code zero. Measured with a
    WH_KEYBOARD_LL hook, that zero propagates verbatim to the hook, to
    WM_KEYDOWN's lParam and to Raw Input's MakeCode - so DirectInput and Raw
    Input consumers, which is to say games, saw "key 0" and ignored every
    keystroke. Ordinary windows read the virtual key instead and were fine,
    which is exactly why this looked like it worked everywhere that mattered.
    """
    print("[TEST] synthesised keys carry a real scan code")
    for name, vk in (("A", 0x41), ("C", 0x43), ("V", 0x56), ("Ctrl", 0x11)):
        scan, extended = win_input.scan_code(vk)
        assert scan != 0, f"{name} still maps to scan code 0"
        assert not extended, f"{name} should not be an extended key"

    scan, _ = win_input.scan_code(0x41)
    event = win_input._key_event(0x41, scan, 0)
    assert event.ki.wScan == scan != 0, "the event dropped the scan code"
    assert event.ki.wVk == 0x41, "the event dropped the virtual key"
    # Both fields populated and no KEYEVENTF_SCANCODE: the message-queue path
    # reads wVk exactly as before, and games read wScan.
    assert not event.ki.dwFlags & win_input.KEYEVENTF_SCANCODE, \
        "forcing scan-code interpretation makes correctness depend on the " \
        "target's keyboard layout, which for this app is often Thai"
    print(f"  -> A=0x{scan:02X}, virtual key preserved, no layout dependency")


def test_extended_keys_are_flagged():
    """Home without the extended flag is numpad 7, which types a digit."""
    print("[TEST] extended keys carry the E0 flag")
    for name, vk in (("Home", 0x24), ("End", 0x23), ("Left", 0x25),
                     ("Delete", 0x2E), ("RControl", 0xA3), ("RMenu", 0xA5)):
        _scan, extended = win_input.scan_code(vk)
        assert extended, f"{name} was not flagged as an extended key"
    for name, vk in (("A", 0x41), ("LControl", 0xA2), ("LShift", 0xA0)):
        _scan, extended = win_input.scan_code(vk)
        assert not extended, f"{name} was wrongly flagged as extended"
    print("  -> Home, End, arrows, Delete and the right-hand modifiers")


def test_both_sides_of_every_modifier_are_released():
    """Releasing VK_CONTROL only lets go of the LEFT one.

    Measured: sending a key-up for the side-agnostic VK_CONTROL arrives at the
    hook as 0xA2 (left), because the scan code decides which physical key the
    event describes. Someone holding right Ctrl - or AltGr, which is right Alt
    and is how several European layouts type everyday characters - kept holding
    it straight through the translation.
    """
    print("[TEST] modifier release covers both sides")
    for vk in (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
        assert vk in win_input.MODIFIER_KEYS, f"0x{vk:02X} is not released"
    assert 0x11 not in win_input.MODIFIER_KEYS, \
        "the side-agnostic VK_CONTROL only ever releases the left key"
    print("  -> left and right Shift, Ctrl and Alt, plus both Windows keys")


def test_key_hold_clears_a_slow_frame():
    """A press shorter than one frame can fall between two input polls.

    A game samples the keyboard once a frame. 33 ms is one frame at 30 fps,
    and a game dropping frames is exactly when someone stops playing and starts
    typing.
    """
    print("[TEST] keys are held long enough for a 30 fps game")
    assert win_input.DEFAULT_HOLD >= 0.033, \
        f"a {win_input.DEFAULT_HOLD * 1000:.0f} ms hold fits inside a 30 fps frame"
    assert win_input.DEFAULT_GAP < win_input.DEFAULT_HOLD, \
        "the gap between keystrokes should be shorter than the hold"
    print(f"  -> hold {win_input.DEFAULT_HOLD * 1000:.0f} ms, "
          f"gap {win_input.DEFAULT_GAP * 1000:.0f} ms")


def test_corner_notification_follows_the_active_screen():
    """The toast used to be pinned to the primary monitor.

    Plenty of people keep a game on a second screen, and a notification about
    that game on the other monitor is a notification nobody sees.
    """
    print("[TEST] the toast lands on the screen in use")
    import inspect
    source = inspect.getsource(win_overlay.bottom_right)
    assert "monitor_work_area(0, 0)" not in source, \
        "bottom_right is still hard-coded to the primary monitor"
    assert "foreground_work_area" in source

    left, top = win_overlay.bottom_right(300, 60)
    area = win_overlay.foreground_work_area()
    assert area[0] <= left < area[2] and area[1] <= top < area[3], \
        f"({left}, {top}) is outside the work area {area}"
    print(f"  -> placed at {left},{top} inside {area}")


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
        test_fallback_reaches_a_second_free_engine()
        test_fallback_never_spends_money()
        test_missing_api_key_is_not_an_attempt()
        test_failed_engine_goes_to_the_back()
        test_clipboard_is_given_back()
        test_undo_restores_the_original()
        test_undo_refuses_when_the_text_moved_on()
        test_undo_hotkey_does_not_unbind_translation()
        test_overlay_windows_stay_out_of_alt_tab()
        test_keystrokes_carry_a_real_scan_code()
        test_extended_keys_are_flagged()
        test_both_sides_of_every_modifier_are_released()
        test_key_hold_clears_a_slow_frame()
        test_corner_notification_follows_the_active_screen()
        test_about_links()
        test_open_link_is_narrow()
    assert guard.unchanged(), "config.json was left modified after restore"
    print("\n  -> config.json restored byte-for-byte")
    print("\n=== ALL BACKEND TESTS PASSED ===")
