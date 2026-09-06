"""
The update notification: a card that slides in at the bottom-right.

Built the same way as ``toast_window.py`` - a second frameless WebView parked
off-screen and shown with ``win_overlay`` rather than pywebview's ``show()``,
which would steal keyboard focus from whatever the user is typing in.

Three differences from the toast:

* it does not dismiss itself, because it is asking a question;
* the progress bar is driven from Python as a real percentage while the
  installer downloads, instead of running a countdown;
* it stays clickable. ``WS_EX_NOACTIVATE`` keeps it from taking focus while
  still delivering mouse events, which is exactly what is wanted: press a
  button without losing your place in the sentence you were typing.
"""
import json
import threading

import webview

import i18n
import win_overlay as win

TITLE = "Typist Update"
CARD_W = 400
CARD_H = 188
# While downloading there are no buttons, so the card shrinks to fit rather
# than leaving a block of empty space where they were.
CARD_H_BUSY = 112

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root {
    --bg:#ffffff; --fg:#0f172a; --muted:#64748b; --accent:#4f46e5;
    --accent-fg:#ffffff; --soft:#eef2ff; --border:#e4e8f0; --ok:#10b981;
    --bad:#ef4444; --track:#e6eaf3;
  }
  html[data-theme="dark"] {
    --bg:#151b2b; --fg:#f1f5f9; --muted:#8b9ab4; --accent:#6366f1;
    --accent-fg:#ffffff; --soft:#232c46; --border:#28324a; --ok:#34d399;
    --bad:#f87171; --track:#26314a;
  }
  * { box-sizing:border-box; }
  html, body {
    margin:0; height:100%; overflow:hidden; background:var(--bg);
    font-family:'Segoe UI', system-ui, 'Noto Sans Thai', 'Noto Sans JP',
                'Noto Sans SC', sans-serif;
    user-select:none; color:var(--fg);
  }
  #card {
    height:100%; padding:14px 16px 12px; display:flex; flex-direction:column;
    border:1.5px solid var(--accent); border-radius:10px; background:var(--bg);
    transform:translateY(30px); opacity:0;
    transition:transform .34s cubic-bezier(.34,1.5,.64,1), opacity .26s ease-out;
  }
  #card.in { transform:none; opacity:1; }

  .head { display:flex; align-items:center; gap:9px; }
  .spark { font-size:16px; }
  .title { font-size:13.5px; font-weight:800; flex:1;
           white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .tag { font-size:10px; font-weight:700; padding:2px 7px; border-radius:6px;
         background:var(--soft); color:var(--accent); white-space:nowrap; }
  .tag:empty { display:none; }   /* no empty pill when there is nothing to say */

  .body { font-size:11.5px; color:var(--muted); line-height:1.55; margin-top:7px;
          overflow:hidden; display:-webkit-box; -webkit-line-clamp:3;
          -webkit-box-orient:vertical; }

  #track { margin-top:10px; height:5px; border-radius:3px; background:var(--track);
           overflow:hidden; display:none; }
  #bar { height:100%; width:0%; background:var(--accent); border-radius:3px;
         transition:width .18s linear; }
  #card.busy #track, #card.done #track, #card.error #track { display:block; }
  #card.done #bar { width:100% !important; background:var(--ok); }
  #card.error #bar { width:100% !important; background:var(--bad); }

  .actions { margin-top:auto; padding-top:11px; display:flex; align-items:center;
             gap:8px; }
  button { font:inherit; font-size:11.5px; font-weight:700; cursor:pointer;
           border-radius:7px; padding:7px 13px; border:1px solid var(--border);
           background:transparent; color:var(--muted);
           transition:background .15s, color .15s, transform .1s; }
  button:hover { background:var(--soft); color:var(--fg); }
  button:active { transform:scale(.97); }
  button.primary { background:var(--accent); color:var(--accent-fg);
                   border-color:var(--accent); }
  button.primary:hover { filter:brightness(1.08); }
  .grow { flex:1; }
  #card.busy .actions, #card.done .actions { display:none; }
</style></head>
<body>
  <div id="card">
    <div class="head">
      <span class="spark" id="icon">\\u2728</span>
      <span class="title" id="title"></span>
      <span class="tag" id="tag"></span>
    </div>
    <div class="body" id="body"></div>
    <div id="track"><div id="bar"></div></div>
    <div class="actions">
      <button class="primary" id="go"></button>
      <button id="later"></button>
      <span class="grow"></span>
      <button id="skip"></button>
    </div>
  </div>
<script>
  const card = document.getElementById('card');
  const el = (id) => document.getElementById(id);

  function setState(name) {
    card.classList.remove('busy', 'done', 'error');
    if (name) card.classList.add(name);
  }

  window.updateShow = (d) => {
    document.documentElement.dataset.theme = d.theme || 'light';
    el('icon').textContent = d.icon || '\\u2728';
    el('title').textContent = d.title || '';
    el('tag').textContent = d.tag || '';
    el('body').textContent = d.body || '';
    el('go').textContent = d.go || '';
    el('later').textContent = d.later || '';
    el('skip').textContent = d.skip || '';
    el('bar').style.width = '0%';
    setState(d.state || '');
    card.classList.remove('in');
    void card.offsetWidth;
    card.classList.add('in');
  };

  window.updateProgress = (percent, label) => {
    setState('busy');
    el('bar').style.width = Math.max(0, Math.min(100, percent)) + '%';
    if (label !== undefined) el('body').textContent = label;
  };

  window.updateFinish = (d) => {
    setState(d.ok ? 'done' : 'error');
    el('icon').textContent = d.ok ? '\\u2713' : '\\u2715';
    if (d.title !== undefined) el('title').textContent = d.title;
    if (d.body !== undefined) el('body').textContent = d.body;
    if (!d.ok) {
      card.classList.remove('error');
      void card.offsetWidth;
      card.classList.add('error');
      el('go').textContent = d.go || '';
      el('later').textContent = d.later || '';
      el('skip').textContent = d.skip || '';
    }
  };

  const send = (choice) => {
    if (window.pywebview) window.pywebview.api.choose(choice);
  };
  el('go').addEventListener('click', () => send('install'));
  el('later').addEventListener('click', () => send('later'));
  el('skip').addEventListener('click', () => send('skip'));
</script>
</body></html>
"""


class UpdateApi:
    """The three buttons. Everything else is private so pywebview cannot see it."""

    def __init__(self, panel):
        self._panel = panel

    def choose(self, action):
        self._panel.handle_choice(action)
        return True


class UpdatePanel:
    """Owns the notification window. Safe to call from any thread."""

    def __init__(self, on_choice=None):
        self._window = None
        self._hwnd = None
        self._scale = 1.0
        self._ready = False
        self._lock = threading.Lock()
        self._api = UpdateApi(self)
        self.on_choice = on_choice

    # -- lifecycle ----------------------------------------------------
    def create(self):
        """Create the window off-screen. Call before webview.start()."""
        self._window = webview.create_window(
            TITLE, html=_HTML, js_api=self._api,
            width=CARD_W, height=CARD_H,
            # WinForms enforces MinimumSize, so this has to allow the shorter
            # busy card - otherwise the window refuses to shrink and the
            # progress state keeps a block of empty space where the buttons were.
            min_size=(CARD_W, CARD_H_BUSY),
            x=win.PARK_X, y=win.PARK_Y,
            frameless=True, easy_drag=False, on_top=True,
            resizable=False, focus=False)
        return self._window

    def mark_ready(self):
        self._hwnd = win.find_window(TITLE)
        if not self._hwnd:
            print("[Update] Notification window not found; updates will be silent.")
            return
        # Not click-through: this card has buttons. NOACTIVATE still keeps it
        # from stealing focus from whatever the user is typing in.
        win.apply_overlay_styles(self._hwnd, click_through=False)
        win.round_corners(self._hwnd)
        self._scale = win.dpi_scale(self._hwnd)
        win.hide(self._hwnd)
        self._ready = True

    def destroy(self):
        self._ready = False
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    @property
    def ready(self):
        return self._ready

    # -- showing ------------------------------------------------------
    def offer(self, version, notes, theme="light"):
        """Tell the user a new version exists, and ask what to do."""
        self._show({
            "icon": "✨",
            "title": i18n.t("update.available.title", version=version),
            "tag": f"v{version}",
            "body": _summarise(notes) or i18n.t("update.available.body"),
            "go": i18n.t("update.action.install"),
            "later": i18n.t("update.action.later"),
            "skip": i18n.t("update.action.skip"),
            "state": "",
            "theme": theme,
        })

    def progress(self, received, total):
        if not self._visible():
            return
        percent = (received / total * 100) if total else 0
        label = i18n.t("update.downloading",
                       done=f"{received / 1048576:.1f}",
                       total=f"{total / 1048576:.1f}" if total else "?")
        self._resize(CARD_H_BUSY)
        self._evaluate("updateProgress", percent, label)

    def installing(self):
        if not self._visible():
            return
        self._resize(CARD_H_BUSY)
        self._evaluate("updateFinish", {
            "ok": True,
            "title": i18n.t("update.installing.title"),
            "body": i18n.t("update.installing.body"),
        })

    def failed(self, reason, theme="light"):
        """Say what went wrong, and leave the buttons so it can be retried."""
        self._show({
            "icon": "✕",
            "title": i18n.t("update.failed.title"),
            "tag": "",
            "body": reason or i18n.t("update.failed.body"),
            "go": i18n.t("update.action.retry"),
            "later": i18n.t("update.action.later"),
            "skip": i18n.t("update.action.page"),
            "state": "error",
            "theme": theme,
        })

    def hide(self):
        if self._hwnd:
            try:
                win.hide(self._hwnd)
            except Exception:
                pass

    def handle_choice(self, action):
        if self.on_choice:
            try:
                self.on_choice(action)
            except Exception as exc:
                print(f"[Update] choice handler failed: {exc}")

    # -- internals ----------------------------------------------------
    def _show(self, payload):
        if not self._ready:
            return
        with self._lock:
            try:
                self._place(CARD_H)
                self._evaluate("updateShow", payload)
            except Exception as exc:
                print(f"[Update] Could not show the notification: {exc}")

    def _resize(self, logical_height):
        """Keep the card anchored to the corner as its height changes."""
        with self._lock:
            try:
                self._place(logical_height)
            except Exception:
                pass

    def _place(self, logical_height):
        width = int(CARD_W * self._scale)
        height = int(logical_height * self._scale)
        left, top = win.bottom_right(width, height)
        win.show_at(self._hwnd, left, top, width, height)

    def _visible(self):
        return self._ready and win.is_visible(self._hwnd)

    def _evaluate(self, function, *args):
        try:
            encoded = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
            self._window.evaluate_js(
                f"window.{function} && window.{function}({encoded})")
        except Exception as exc:
            print(f"[Update] {function} failed: {exc}")


def _summarise(notes, limit=150):
    """The first meaningful line or two of a release body.

    Release notes are Markdown with headings, badges and collapsed sections;
    the card has room for about three lines, so take the prose and leave the
    decoration behind.
    """
    if not notes:
        return ""
    lines = []
    for raw in str(notes).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---", "|", "<", "```", ">")):
            continue
        line = line.replace("**", "").replace("`", "").lstrip("-* ").strip()
        if line:
            lines.append(line)
        if sum(len(x) for x in lines) > limit:
            break
    text = " ".join(lines)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
