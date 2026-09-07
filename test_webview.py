"""
UI test suite (V4) - drives the real WebView2 window.

Launches the actual React bundle against the real backend and exercises it
through the DOM, then reports startup and interaction timings.

Notes for anyone extending this:

* Wait on ``api.wait_until_ready`` rather than polling ``evaluate_js``. Every
  evaluate_js runs on the WebView2 UI thread, which is the same thread that
  services the page's own calls into the Python API, so a tight poll starves
  the app's bootstrap.
* Measure inside the page with ``performance.now()``. Timing an
  ``evaluate_js`` round trip from Python measures the bridge, not the UI.
"""
import functools
import json
import os
import socket
import sys
import threading
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

print = functools.partial(print, flush=True)  # noqa: A001

import webview

import about
import i18n
from api_bridge import Api
from config_guard import ConfigGuard
from config_manager import load_config, save_config
from history_store import HistoryStore
from hotkey_manager import HotkeyManager
from tray_manager import TrayManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_ENTRY = os.path.join(BASE_DIR, "ui", "dist", "index.html")

failures = []
notes = []


def _free_http_port():
    """A port for pywebview's local file server, picked fresh each launch.

    pywebview serves ui/dist over http and defaults to a fixed port (42001).
    Any other process on the machine can bind that first - and because the
    WSGI server underneath sets SO_REUSEADDR, this app would then happily load
    *its* page into a WebView that has window.pywebview.api attached to it.
    Asking the OS for an unused port each launch removes the guess.

    It also stops the test suites loading the installed copy's bundle instead
    of the one in the checkout, which is how this was noticed.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def check(label, condition, detail=""):
    if condition:
        notes.append(f"  [ok]   {label}")
    else:
        failures.append(f"  [FAIL] {label}{f' - {detail}' if detail else ''}")


def main():
    if not os.path.exists(UI_ENTRY):
        print(f"UI bundle missing: {UI_ENTRY}")
        print("Build it first:  cd ui && npm run build")
        return 1

    original_config = load_config()
    config = dict(original_config)
    config["appearance_mode"] = "Dark"
    i18n.set_language(config.get("app_language", "th"))

    history = HistoryStore()
    history.add("สวัสดีครับ", "Hello", "th", "en")
    history.add("ขอบคุณครับ", "Thank you", "th", "en")

    api = Api(config=config,
              hotkey_manager=HotkeyManager(config=config),
              tray_manager=TrayManager(),
              history=history)

    # pywebview serves local files over http on a port it derives itself, so a
    # copy of the installed app that is already running owns that port - and
    # this suite then loads *its* bundle instead of the one in the checkout,
    # silently, reporting on code that is not here. Ask for a port nothing else
    # will pick.
    window = webview.create_window(
        "Typist Translator", url=UI_ENTRY, js_api=api,
        width=940, height=780, min_size=(720, 560),
        background_color="#0A0E1A")
    api.attach_window(window)

    def js(code, default=None):
        try:
            return window.evaluate_js(code)
        except Exception as exc:
            failures.append(f"  [FAIL] evaluate_js: {exc}")
            return default

    def script():
        try:
            run(js, api, history, window, config)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            failures.append(f"  [FAIL] harness crashed: {exc}")
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    threading.Thread(target=script, daemon=True).start()
    webview.start(private_mode=False, http_port=_free_http_port())

    save_config(original_config)
    i18n.set_language(original_config.get("app_language", "th"))

    print("\n".join(notes))
    if failures:
        print("\n".join(failures))
        print(f"\n=== {len(failures)} UI CHECK(S) FAILED ===")
        return 1
    print("\n=== ALL UI TESTS PASSED ===")
    return 0


def run(js, api, history, window, config):
    print("=== UI TEST SUITE (WebView2 + React) ===\n")

    print("[UI 1] Startup...")
    ready = api.wait_until_ready(timeout=40)
    check("front end signalled ready", ready, "timed out after 40s")
    if not ready:
        print("  root:", js("document.getElementById('root').innerHTML.slice(0,400)"))
        print("  errors:", js("JSON.stringify(window.__typistErrors||[])"))
        return

    startup_ms = api.ready_ms
    print(f"  -> first interactive paint: {startup_ms:.0f} ms")
    check("startup under 4s", startup_ms < 4000, f"{startup_ms:.0f} ms")

    errors = js("JSON.stringify(window.__typistErrors||[])", "[]")
    check("no JavaScript errors during boot", errors in ("[]", None), errors)

    print("\n[UI 2] Rendered content...")
    nav = js("Array.from(document.querySelectorAll('.nav__item'))"
             ".map(n=>n.innerText.replace('\\n',' ').trim())")
    check("five tabs rendered", isinstance(nav, list) and len(nav) == 5, str(nav))
    check("tab labels are translated, not raw keys",
          all("nav." not in label for label in (nav or [])), str(nav))
    print(f"  -> nav: {nav}")

    rows = js("document.querySelectorAll('.history__row').length")
    check("history rendered from the backend", rows == 2, f"got {rows}")

    status = js("document.querySelector('.status-pill').innerText.trim()")
    check("status pill shows the active label",
          status == i18n.t("app.status.active"), f"{status!r}")

    # Whatever engine the user has configured, not a hard-coded one.
    from translator_core import TRANSLATION_ENGINES
    expected = TRANSLATION_ENGINES[config["translation_engine"]]["name"]
    engine = js("document.querySelector('.engine-name').innerText.trim()")
    check("active engine shown", expected in (engine or ""),
          f"{engine!r} does not mention {expected!r}")

    print("\n[UI 3] Tab switching (measured inside the page)...")
    timings = {}
    for index, (name, marker) in {
        1: ("models", ".engine-card"),
        2: ("settings", ".prefs"),
        3: ("guide", ".guide-hero"),
        0: ("home", ".sandbox"),
    }.items():
        elapsed = js(f"""
          (() => {{
            const t0 = performance.now();
            document.querySelectorAll('.nav__item')[{index}].click();
            document.body.offsetHeight;   /* force layout */
            return performance.now() - t0;
          }})()
        """, -1)
        present = js(f"!!document.querySelector('{marker}')", False)
        timings[name] = elapsed
        check(f"{name} page renders", present is True)
        check(f"{name} switch under 100ms", 0 <= elapsed < 100, f"{elapsed} ms")
    print("  -> " + "  ".join(f"{k}:{v:.1f}ms" for k, v in timings.items()))

    print("\n[UI 3b] The page is running this checkout's bundle...")
    # Fingerprint the file on disk and look for it in the loaded page. Without
    # this the suite will happily pass against somebody else's build.
    with open(UI_ENTRY, encoding="utf-8") as handle:
        bundle = handle.read()
    served = js("document.documentElement.outerHTML", "") or ""
    # Sample several places, not one. Two different builds of this app share
    # megabytes of identical vendored React, so a single fingerprint taken from
    # the middle of the file matches a stale bundle by coincidence - which is
    # exactly how this check first passed against the wrong server.
    marks = [bundle[int(len(bundle) * f):int(len(bundle) * f) + 80]
             for f in (0.55, 0.75, 0.9)]
    missing = [i for i, mark in enumerate(marks) if mark not in served]
    check("the window loaded the bundle from ui/dist", not missing,
          f"{len(missing)}/3 fingerprints absent from {len(served)} chars at "
          f"{js('location.href', '?')} - rebuild with 'cd ui && npm run build', "
          f"and close any running copy of the app")

    print("\n[UI 3c] Undo hotkey control...")
    js("document.querySelectorAll('.nav__item')[2].click()", None)
    undo_value = js("""
      (() => {
        const inputs = [...document.querySelectorAll('.settings__undo input')];
        return inputs.length ? inputs[0].value : null;
      })()
    """, None)
    check("undo hotkey field is on the settings page", undo_value is not None)
    check("undo hotkey shows the configured combination",
          undo_value == config.get("undo_hotkey", "ctrl+alt+z"),
          f"showed {undo_value!r}")
    labels = js("""
      [...document.querySelectorAll('.checkrow span')].map((s) => s.textContent)
    """, [])
    check("the clipboard preference is offered",
          any("clipboard" in text.lower() or "คัดลอก" in text for text in labels),
          f"{labels}")
    js("document.querySelectorAll('.nav__item')[3].click()", None)
    steps = js("document.querySelectorAll('.guide-step__title').length", 0)
    check("undo is explained in the guide", steps == 4,
          f"the guide should have four steps, found {steps}")

    print("\n[UI 4] About tab...")
    js("document.querySelectorAll('.nav__item')[4].click()")
    time.sleep(0.4)
    check("about page renders", js("!!document.querySelector('.about-hero')") is True)
    title = js("document.querySelector('.about-hero__title').innerText.trim()")
    check("about page names the app", title == about.APP_NAME, f"{title!r}")
    by = js("document.querySelector('.about-hero__by').innerText")
    check("about page credits the author", about.AUTHOR in (by or ""), f"{by!r}")
    alias = js("document.querySelector('.about-hero__alias')?.innerText || ''")
    check("about page links the author's two handles",
          (about.ALIAS in (alias or "") and about.AUTHOR in (alias or ""))
          if about.ALIAS else alias == "", f"{alias!r}")
    licensed = js("document.querySelector('.about-license').innerText")
    check("about page states the licence", about.LICENSE in (licensed or ""),
          f"{licensed!r}")
    chips = js("document.querySelectorAll('.about-tech__chip').length")
    check("about page lists the stack", chips == len(about.BUILT_WITH), str(chips))
    shown = js("document.querySelectorAll('.about-link').length")
    empty = js("!!document.querySelector('.about-links__empty')")
    check("links section matches what about.py configures",
          shown == len(about.links()) and (empty is True) == (shown == 0),
          f"{shown} links, empty note={empty}")
    print(f"  -> {title} by {about.AUTHOR}, {about.LICENSE}, "
          f"{shown} link(s) configured")

    print("\n[UI 5] Sandbox translation round trip...")
    js("document.querySelectorAll('.nav__item')[0].click()")
    time.sleep(0.3)
    js("""
      const ta = document.querySelector('.sandbox__pane .textarea');
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, 'ขอบคุณมากครับ');
      ta.dispatchEvent(new Event('input', {bubbles: true}));
      document.querySelector('.sandbox__actions .btn--primary').click();
      null;
    """)

    # The busy state has to be visible while the request is in flight: a
    # sweep over the source text and a shimmer where the result will land.
    time.sleep(0.25)
    check("source text shows a scanning sweep while translating",
          js("!!document.querySelector('.sandbox__field.is-busy .scanline')") is True)
    check("output pane shows a shimmer placeholder while translating",
          js("document.querySelectorAll('.skeleton .skeleton__bar').length") == 3,
          str(js("document.querySelectorAll('.skeleton .skeleton__bar').length")))

    time.sleep(4.0)
    check("busy animation is gone once the translation lands",
          js("!!document.querySelector('.scanline')") is False)
    output = js("document.querySelectorAll('.textarea')[1].value")
    check("sandbox produced a translation",
          bool(output) and output != "ขอบคุณมากครับ", f"{output!r}")
    check("sandbox translation was recorded in history",
          js("document.querySelectorAll('.history__row').length") == 3,
          str(js("document.querySelectorAll('.history__row').length")))
    print(f"  -> 'ขอบคุณมากครับ' -> {output!r}")

    print("\n[UI 6] Events pushed from a background thread...")
    entry = history.add("ทดสอบ push", "push test", "th", "en")
    api.push_event("translated", entry)
    time.sleep(0.8)
    check("pushed history entry appeared",
          js("document.querySelectorAll('.history__row').length") == 4,
          str(js("document.querySelectorAll('.history__row').length")))

    api.push_event("status", {"active": False})
    time.sleep(0.5)
    paused = js("document.querySelector('.status-pill').className")
    check("pushed status event updated the pill",
          "status-pill--paused" in (paused or ""), f"{paused!r}")
    api.push_event("status", {"active": True})
    time.sleep(0.3)

    print("\n[UI 7] Interface language switches without a reload...")
    js("document.querySelectorAll('.nav__item')[2].click()")
    time.sleep(0.4)
    for code, expected in (("ja", "ホーム"), ("zh-CN", "主页"), ("en", "Home"),
                           ("th", "หน้าหลัก")):
        js(f"""
          (() => {{
            const select = document.querySelector('.settings__control');
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLSelectElement.prototype, 'value').set;
            setter.call(select, {json.dumps(code)});
            select.dispatchEvent(new Event('change', {{bubbles: true}}));
          }})()
        """)
        time.sleep(0.6)
        label = js("document.querySelectorAll('.nav__item')[0].innerText"
                   ".replace('\\n',' ').trim()")
        check(f"UI switched to {code}", expected in (label or ""), f"{label!r}")
    print("  -> switched through ja / zh-CN / en / th with no reload")

    print("\n[UI 8] Theme switching...")
    for mode, expected in (("Light", "light"), ("Dark", "dark")):
        js(f"""
          (() => {{
            const selects = document.querySelectorAll('.settings__control');
            const themeSelect = selects[selects.length - 1];
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLSelectElement.prototype, 'value').set;
            setter.call(themeSelect, {json.dumps(mode)});
            themeSelect.dispatchEvent(new Event('change', {{bubbles: true}}));
          }})()
        """)
        time.sleep(0.5)
        theme = js("document.documentElement.getAttribute('data-theme')")
        check(f"theme {mode} applied", theme == expected, f"{theme!r}")

    print("\n[UI 9] Language picker...")
    js("document.querySelectorAll('.nav__item')[0].click()")
    time.sleep(0.4)
    js("document.querySelectorAll('.stat-card')[1]"
       ".querySelectorAll('.btn')[0].click()")
    time.sleep(0.8)
    check("picker opened", js("!!document.querySelector('.modal')") is True)
    rows = js("document.querySelectorAll('.lang-row').length")
    check("picker listed languages", (rows or 0) > 5, f"{rows} rows")
    js("""
      const input = document.querySelector('.modal .input');
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, 'japan');
      input.dispatchEvent(new Event('input', {bubbles: true}));
      null;
    """)
    time.sleep(0.9)
    found = js("Array.from(document.querySelectorAll('.lang-row__meta'))"
               ".some(n => n.innerText.includes('[ja]'))")
    check("picker search found Japanese", found is True)
    js("document.querySelector('.modal-backdrop').dispatchEvent("
       "new MouseEvent('mousedown', {bubbles: true}))")
    time.sleep(0.4)
    check("picker closed", js("!!document.querySelector('.modal')") is False)
    print(f"  -> {rows} languages listed, search and close work")


if __name__ == "__main__":
    # This drives the real app, which persists settings as the user clicks.
    # The guard keeps config.json byte-identical no matter what the run does.
    with ConfigGuard() as guard:
        exit_code = main()
    assert guard.unchanged(), "config.json was left modified after restore"
    print("  -> config.json restored"
          f" ({'the run had modified it' if guard.was_modified else 'untouched'})")
    sys.exit(exit_code)
