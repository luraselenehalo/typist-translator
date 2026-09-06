"""
Floating Toast HUD - WebView edition.

A second, frameless, always-on-top pywebview window parked at the bottom-right
of the screen. It is created once and then reused: showing a toast is a
SetWindowPos plus a small ``evaluate_js`` call, so there is no window
construction on the hotkey path.

It goes through ``win_overlay`` rather than pywebview's ``window.show()``,
which calls ``Form.Activate()`` and stole keyboard focus from whatever the
user was typing in - for the whole time the toast was up, right after a
translation had been pasted, so their next keypress went nowhere.

The markup is inlined here rather than built by Vite because it is a single
tiny document with no React in it - loading a whole bundle for a 100 px
notification would cost more than it saves.
"""
import json
import threading

import webview

import i18n
import win_overlay as win
from translator_core import LANGUAGES_DB

TOAST_WIDTH = 400
TOAST_HEIGHT = 118

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root {
    --bg: #ffffff; --fg: #0f172a; --muted: #94a3b8; --accent: #4f46e5;
    --ok: #10b981; --soft: #ecfdf5; --okText: #047857; --border: #e4e8f0;
  }
  html[data-theme="dark"] {
    --bg: #151b2b; --fg: #f1f5f9; --muted: #64748b; --accent: #a5b4fc;
    --ok: #10b981; --soft: #052e22; --okText: #6ee7b7; --border: #253045;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; height: 100%; background: var(--bg); overflow: hidden;
    font-family: 'Segoe UI', system-ui, 'Noto Sans Thai', 'Noto Sans JP',
                 'Noto Sans SC', sans-serif;
    user-select: none; cursor: pointer;
  }
  #card {
    height: 100%; padding: 12px 16px 10px;
    background: var(--bg); color: var(--fg);
    border: 1.5px solid var(--ok); border-radius: 12px;
    display: flex; flex-direction: column; gap: 3px;
    transform: translateY(38px); opacity: 0;
    transition: transform .34s cubic-bezier(.34,1.56,.64,1), opacity .28s ease-out,
                border-color .2s ease-out;
  }
  #card.in { transform: none; opacity: 1; }
  #card.hold { border-color: var(--accent); }
  .top { display: flex; align-items: center; gap: 7px; }
  .check { color: var(--ok); font-weight: 700; font-size: 14px; }
  .route { font-size: 12px; font-weight: 700; flex: 1;
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tag { font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 6px;
         background: var(--soft); color: var(--okText); white-space: nowrap; }
  .trans { font-size: 12.5px; font-weight: 700; color: var(--accent);
           line-height: 1.4; overflow: hidden;
           display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .orig { font-size: 10px; color: var(--muted); white-space: nowrap;
          overflow: hidden; text-overflow: ellipsis; }
  #track { margin-top: auto; height: 3px; border-radius: 2px;
           background: var(--border); overflow: hidden; }
  #bar { height: 100%; width: 100%; background: var(--ok); transform-origin: left; }
</style></head>
<body>
  <div id="card">
    <div class="top">
      <span class="check">&#10003;</span>
      <span class="route" id="route"></span>
      <span class="tag">Typist HUD</span>
    </div>
    <div class="trans" id="trans"></div>
    <div class="orig" id="orig"></div>
    <div id="track"><div id="bar"></div></div>
  </div>
<script>
  const card = document.getElementById('card');
  const bar = document.getElementById('bar');
  let hideTimer = null, held = false, remaining = 0, startedAt = 0;

  function startCountdown(ms) {
    remaining = ms; startedAt = Date.now();
    bar.style.transition = 'none';
    bar.style.transform = 'scaleX(1)';
    void bar.offsetWidth;
    bar.style.transition = `transform ${ms}ms linear`;
    bar.style.transform = 'scaleX(0)';
    clearTimeout(hideTimer);
    hideTimer = setTimeout(dismiss, ms);
  }

  window.showToast = (data) => {
    document.documentElement.dataset.theme = data.theme || 'light';
    document.getElementById('route').textContent = data.route;
    document.getElementById('trans').textContent = '\\u201c' + data.translated + '\\u201d';
    document.getElementById('orig').textContent = data.original;
    held = false;
    card.classList.remove('hold');
    card.classList.remove('in');
    void card.offsetWidth;
    card.classList.add('in');
    startCountdown(data.duration || 2600);
  };

  function dismiss() {
    clearTimeout(hideTimer);
    card.classList.remove('in');
    setTimeout(() => { if (window.pywebview) window.pywebview.api.hide_toast(); }, 260);
  }

  // Hovering holds the toast open; clicking dismisses it now.
  document.body.addEventListener('mouseenter', () => {
    if (!card.classList.contains('in')) return;
    held = true;
    clearTimeout(hideTimer);
    remaining = Math.max(600, remaining - (Date.now() - startedAt));
    const width = bar.getBoundingClientRect().width;
    bar.style.transition = 'none';
    bar.style.transform = `scaleX(${width / bar.parentElement.offsetWidth})`;
    card.classList.add('hold');
  });
  document.body.addEventListener('mouseleave', () => {
    if (!held) return;
    held = false;
    card.classList.remove('hold');
    startCountdown(remaining);
  });
  document.body.addEventListener('click', dismiss);
</script>
</body></html>
"""


class ToastApi:
    """Exposed to the toast document so it can ask to be hidden."""

    def __init__(self, hud):
        # Private: pywebview recurses into public attributes when building the
        # JS bridge, and walking a Window would reach WebView2 COM properties
        # that throw when touched off the UI thread.
        self._hud = hud

    def hide_toast(self):
        self._hud.hide()
        return True


class ToastHUD:
    """Owns the reusable toast window. Safe to call from any thread."""

    def __init__(self):
        self._window = None
        self._hwnd = None
        self._scale = 1.0
        self._api = ToastApi(self)
        self._lock = threading.Lock()
        self._ready = False

    def create(self):
        """Create the toast window, parked off-screen. Call before start().

        Not ``hidden=True``: pywebview implements that with WinForms' Hide(),
        and a WebView2 that has been hidden that way comes back as a blank
        white rectangle. win_overlay has the details.
        """
        self._window = webview.create_window(
            "Typist Toast",
            html=_HTML,
            js_api=self._api,
            width=TOAST_WIDTH,
            height=TOAST_HEIGHT,
            min_size=(TOAST_WIDTH, TOAST_HEIGHT),
            x=win.PARK_X, y=win.PARK_Y,
            frameless=True,
            easy_drag=False,
            on_top=True,
            resizable=False,
            focus=False,
        )
        return self._window

    def mark_ready(self):
        self._hwnd = win.find_window("Typist Toast")
        if not self._hwnd:
            print("[ToastHUD] Window handle not found; toast disabled.")
            return
        # No click-through here: hovering holds the toast open and clicking
        # dismisses it, so it has to receive the mouse. WS_EX_NOACTIVATE alone
        # keeps it from ever taking focus.
        win.apply_overlay_styles(self._hwnd, click_through=False)
        win.round_corners(self._hwnd)
        self._scale = win.dpi_scale(self._hwnd)
        win.hide(self._hwnd)
        self._ready = True

    def hide(self):
        if self._hwnd:
            try:
                win.hide(self._hwnd)
            except Exception:
                pass

    def show(self, original, translated, source_lang, target_lang,
             theme="light", duration_ms=2600):
        if self._window is None or not self._ready:
            return
        src = LANGUAGES_DB.get(source_lang, {}).get("flag", "🌐")
        tgt = LANGUAGES_DB.get(target_lang, {}).get("flag", "🌐")
        payload = {
            "route": f"{i18n.t('toast.success')}   {src} → {tgt}",
            "translated": _clip(translated, 90),
            "original": i18n.t("toast.original", text=_clip(original, 70)),
            "theme": theme,
            "duration": int(duration_ms),
        }
        width = int(TOAST_WIDTH * self._scale)
        height = int(TOAST_HEIGHT * self._scale)
        left, top = win.bottom_right(width, height)
        with self._lock:
            try:
                win.show_at(self._hwnd, left, top, width, height)
                self._window.evaluate_js(
                    f"window.showToast({json.dumps(payload, ensure_ascii=False)})")
            except Exception as exc:
                print(f"[ToastHUD] Could not show toast: {exc}")

    def destroy(self):
        self._ready = False
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


def _clip(text, limit):
    return win.clip(text, limit)
