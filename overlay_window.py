"""
Progress overlay - the "it is working" HUD for the global hotkey.

When the hotkey fires, the user is looking at *another* application: their chat
box, their document. Everything then happens off-screen - a clipboard round
trip and a network call that can take a second or three on a slow engine - and
until now nothing at all appeared until the text had already been replaced. On
a slow engine that reads as "the hotkey did nothing".

This puts a small chip next to the text being translated, floating above every
window, for exactly as long as the work takes.

Showing it without disturbing the app the user is typing in - and letting
clicks fall straight through it to that app - is handled by ``win_overlay``,
which documents the Windows quirks involved.

Fading is done with layered-window alpha from Python rather than CSS opacity.
The window is opaque (a transparent WebView2 surface makes pywebview warn about
cross-thread COM access), so a CSS fade would only fade the chip against its
own background.
"""
import json
import threading
import time

import webview

import i18n
import win_overlay as win
from win_overlay import clip   # re-exported: main.py trims previews with it

TITLE = "Typist Progress"

# Logical (CSS) size of the chip. The document lays itself out to fill the
# window, so the physical size is just this scaled by the monitor DPI.
CHIP_W = 306
CHIP_H = 56

FADE_IN_MS = 110
FADE_OUT_MS = 190

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root {
    --bg:#ffffff; --fg:#0f172a; --muted:#94a3b8; --accent:#4f46e5;
    --soft:#eef2ff; --ok:#10b981; --bad:#ef4444; --track:#e6eaf3;
  }
  html[data-theme="dark"] {
    --bg:#151b2b; --fg:#f1f5f9; --muted:#7c8aa5; --accent:#a5b4fc;
    --soft:#232c46; --ok:#34d399; --bad:#f87171; --track:#26314a;
  }
  * { box-sizing:border-box; }
  html, body {
    margin:0; height:100%; overflow:hidden; background:var(--bg);
    font-family:'Segoe UI', system-ui, 'Noto Sans Thai', 'Noto Sans JP',
                'Noto Sans SC', sans-serif;
    user-select:none; cursor:default;
  }
  #chip {
    height:100%; padding:7px 12px 0; color:var(--fg); background:var(--bg);
    border:1.5px solid var(--accent); border-radius:8px;
    display:flex; flex-direction:column; gap:1px;
  }
  #chip.working { animation:breathe 1.7s ease-in-out infinite; }
  #chip.done  { border-color:var(--ok); }
  #chip.error { border-color:var(--bad); }
  @keyframes breathe {
    0%,100% { border-color:var(--accent); }
    50%     { border-color:var(--soft); }
  }

  .row { display:flex; align-items:center; gap:8px; }
  .grow { flex:1; }

  /* ---- state indicator: a spinning ring that becomes a tick or a cross -- */
  .orb { width:17px; height:17px; flex:none; border-radius:50%; position:relative;
         transition:background .18s ease-out; }
  .working .orb {
    background:conic-gradient(from 0deg, rgba(127,127,127,0) 0deg,
                              var(--accent) 300deg, rgba(127,127,127,0) 360deg);
    -webkit-mask:radial-gradient(circle at 50% 50%, #0000 54%, #000 56%);
            mask:radial-gradient(circle at 50% 50%, #0000 54%, #000 56%);
    animation:spin .8s linear infinite;
  }
  .done  .orb { background:var(--ok); }
  .error .orb { background:var(--bad); }
  @keyframes spin { to { transform:rotate(360deg); } }

  .mark { position:absolute; inset:0; display:grid; place-items:center;
          font-size:11px; font-weight:800; color:#fff; line-height:1;
          opacity:0; transform:scale(.3);
          transition:opacity .16s ease-out,
                     transform .34s cubic-bezier(.34,1.7,.64,1); }
  .done .mark, .error .mark { opacity:1; transform:none; }

  .label { font-size:12px; font-weight:700; white-space:nowrap;
           overflow:hidden; text-overflow:ellipsis; }
  .done  .label { color:var(--ok); }
  .error .label { color:var(--bad); }

  .tag { font-size:9.5px; font-weight:700; padding:2px 6px; border-radius:6px;
         background:var(--soft); color:var(--accent); white-space:nowrap;
         font-variant-numeric:tabular-nums; }
  .tag:empty { display:none; }   /* no empty pill when there is nothing to say */

  /* ---- the text being translated, shimmering while the engine works ----- */
  .preview { font-size:11.5px; font-weight:600; line-height:1.4; color:var(--muted);
             white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .working .preview {
    background:linear-gradient(100deg, var(--muted) 22%, var(--fg) 42%,
                               var(--muted) 62%);
    background-size:260% 100%;
    -webkit-background-clip:text; background-clip:text; color:transparent;
    animation:sweep 1.5s linear infinite;
  }
  @keyframes sweep {
    from { background-position:190% 0; } to { background-position:-90% 0; }
  }

  /* ---- indeterminate progress bar --------------------------------------- */
  #track { margin:auto -12px 0; height:3px; background:var(--track);
           position:relative; overflow:hidden; }
  #bar { position:absolute; top:0; bottom:0; left:0; width:38%;
         background:var(--accent); }
  .working #bar { animation:indet 1.05s cubic-bezier(.65,.05,.36,1) infinite; }
  .done  #bar { left:0; width:100%; background:var(--ok); }
  .error #bar { left:0; width:100%; background:var(--bad); }
  @keyframes indet {
    0%   { left:-42%; width:42%; }
    55%  { width:58%; }
    100% { left:100%; width:32%; }
  }

  /* ---- entrance (replayed on every show) -------------------------------- */
  .enter .row, .enter .preview { animation:rise .30s cubic-bezier(.2,.9,.25,1) both; }
  .enter .preview { animation-delay:.045s; }
  @keyframes rise {
    from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:none; }
  }
</style></head>
<body>
  <div id="chip" class="working">
    <div class="row">
      <span class="orb"><span class="mark" id="mark"></span></span>
      <span class="label" id="label"></span>
      <span class="grow"></span>
      <span class="tag" id="tag"></span>
    </div>
    <div class="preview" id="preview"></div>
    <div id="track"><div id="bar"></div></div>
  </div>
<script>
  const chip = document.getElementById('chip');
  const label = document.getElementById('label');
  const preview = document.getElementById('preview');
  const tag = document.getElementById('tag');
  const mark = document.getElementById('mark');
  let ticker = null, startedAt = 0, slowLabel = '', slowShown = false;

  function setState(state) {
    chip.classList.remove('working', 'done', 'error');
    chip.classList.add(state);
  }

  /* The elapsed counter is the honest answer to "is it stuck?". It only
     appears once the wait is long enough to be worth reporting. */
  function startTicker() {
    startedAt = Date.now();
    slowShown = false;
    clearInterval(ticker);
    ticker = setInterval(() => {
      const seconds = (Date.now() - startedAt) / 1000;
      if (seconds >= 1.4) tag.textContent = seconds.toFixed(1) + 's';
      if (seconds >= 6 && !slowShown && slowLabel) {
        slowShown = true;
        label.textContent = slowLabel;
      }
    }, 100);
  }

  window.overlayShow = (d) => {
    document.documentElement.dataset.theme = d.theme || 'light';
    slowLabel = d.slow || '';
    label.textContent = d.label || '';
    preview.textContent = d.preview || '';
    tag.textContent = d.tag || '';
    mark.textContent = '';
    setState('working');
    chip.classList.remove('enter');
    void chip.offsetWidth;          /* restart the entrance animation */
    chip.classList.add('enter');
    startTicker();
  };

  /* Update in place - no entrance replay, so the chip does not jump when the
     workflow moves from reading the text to translating it. */
  window.overlayUpdate = (d) => {
    if (d.label !== undefined) label.textContent = d.label;
    if (d.preview !== undefined) preview.textContent = d.preview;
    if (d.tag !== undefined && d.tag !== null) tag.textContent = d.tag;
  };

  window.overlayFinish = (d) => {
    clearInterval(ticker);
    ticker = null;
    setState(d.ok ? 'done' : 'error');
    mark.textContent = d.ok ? '\\u2713' : '\\u2715';
    label.textContent = d.label || '';
    if (d.preview !== undefined && d.preview !== null) preview.textContent = d.preview;
    if (d.tag !== undefined && d.tag !== null) tag.textContent = d.tag;
  };
</script>
</body></html>
"""


# =====================================================================
# Overlay
# =====================================================================
class ProgressOverlay:
    """Owns the reusable chip window. Every method is safe from any thread."""

    def __init__(self):
        self._window = None
        self._hwnd = None
        self._scale = 1.0
        self._ready = False
        self._lock = threading.Lock()
        self._generation = 0        # invalidates fades from a previous run

    # -- lifecycle ----------------------------------------------------
    def create(self):
        """Create the chip window, parked off-screen. Call before start().

        Deliberately *not* ``hidden=True``. pywebview implements that as
        ``Opacity = 0; Show(); Hide()``, and a WebView2 that has been through
        WinForms' Hide() never composites again unless WinForms shows it - so
        the chip would come back as a blank white rectangle every time. Born
        visible but 4000 px off-screen, it paints once and keeps painting;
        ``mark_ready`` then takes it off screen with SetWindowPos, which the
        renderer is happy to recover from.
        """
        self._window = webview.create_window(
            TITLE,
            html=_HTML,
            width=CHIP_W,
            height=CHIP_H,
            # WinForms enforces MinimumSize, and pywebview defaults it to
            # 200x100 - without this the chip would be stuck 34 px too tall.
            min_size=(CHIP_W, CHIP_H),
            x=win.PARK_X, y=win.PARK_Y,
            frameless=True,
            easy_drag=False,
            on_top=True,
            resizable=False,
            focus=False,
        )
        return self._window

    def mark_ready(self):
        """Style the window and park it. Call once webview.start() is running."""
        try:
            self._hwnd = win.find_window(TITLE)
            if not self._hwnd:
                print("[Overlay] Window handle not found; overlay disabled.")
                return
            # Click-through: the chip lands right where the user is typing, so
            # a click aimed at that text box has to reach it.
            win.apply_overlay_styles(self._hwnd, click_through=True)
            win.set_alpha(self._hwnd, 0)
            win.round_corners(self._hwnd)
            self._scale = win.dpi_scale(self._hwnd)
            # Hidden with SetWindowPos, never Form.Hide(), for the reason in
            # create(). Hiding hands activation to the next window in z-order,
            # which is the main window.
            win.hide(self._hwnd)
            self._ready = True
        except Exception as exc:
            print(f"[Overlay] Could not initialise: {exc}")

    def destroy(self):
        self._ready = False
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    @property
    def hwnd(self):
        return self._hwnd

    @property
    def ready(self):
        return self._ready

    # -- the three things the hotkey workflow reports -----------------
    def show_working(self, label, preview="", tag="", theme="light"):
        """Place the chip next to the text and start the working animation."""
        if not self._ready:
            return
        with self._lock:
            self._generation += 1
            try:
                self._position()
                self._evaluate("overlayShow", {
                    "label": label,
                    "preview": preview,
                    "tag": tag,
                    "theme": theme,
                    "slow": i18n.t("overlay.slow"),
                })
                self._fade_to(255, FADE_IN_MS, self._generation)
            except Exception as exc:
                print(f"[Overlay] show failed: {exc}")

    def update(self, label=None, preview=None, tag=None):
        """Change the wording without replaying the entrance animation."""
        if not self._ready or not self._visible():
            return
        payload = {}
        if label is not None:
            payload["label"] = label
        if preview is not None:
            payload["preview"] = preview
        if tag is not None:
            payload["tag"] = tag
        if not payload:
            return
        try:
            self._evaluate("overlayUpdate", payload)
        except Exception as exc:
            print(f"[Overlay] update failed: {exc}")

    def finish(self, ok, label, preview=None, tag=None, hold_ms=None):
        """Settle into the success or failure state, then fade out."""
        if not self._ready or not self._visible():
            return
        if hold_ms is None:
            hold_ms = 620 if ok else 2400
        with self._lock:
            self._generation += 1
            generation = self._generation
            try:
                self._evaluate("overlayFinish", {
                    "ok": bool(ok), "label": label,
                    "preview": preview, "tag": tag,
                })
            except Exception as exc:
                print(f"[Overlay] finish failed: {exc}")

        def close_later():
            time.sleep(hold_ms / 1000.0)
            if generation == self._generation:
                self._fade_to(0, FADE_OUT_MS, generation, hide_after=True)

        threading.Thread(target=close_later, daemon=True).start()

    def hide(self):
        """Take the chip away immediately, cancelling any pending fade."""
        with self._lock:
            self._generation += 1
        self._hide_now()

    # -- internals ----------------------------------------------------
    def _evaluate(self, function, payload):
        self._window.evaluate_js(
            f"window.{function} && window.{function}("
            f"{json.dumps(payload, ensure_ascii=False)})")

    def _position(self):
        width = int(CHIP_W * self._scale)
        height = int(CHIP_H * self._scale)
        anchor = win.focus_anchor(width, height)
        work = win.monitor_work_area(anchor[0], anchor[1])
        left, top = win.place_rect(anchor, (width, height), work)
        win.show_at(self._hwnd, left, top, width, height)

    def _visible(self):
        return win.is_visible(self._hwnd)

    def _hide_now(self):
        if self._hwnd:
            try:
                win.set_alpha(self._hwnd, 0)
                win.hide(self._hwnd)
            except Exception:
                pass

    def _fade_to(self, target, duration_ms, generation, hide_after=False):
        win.fade(self._hwnd, target, duration_ms,
                 still_current=lambda: generation == self._generation,
                 on_finished=self._hide_now if hide_after else None)
