"""
Hotkey Manager Module - V3

Global hotkey listener, keystroke simulation (Ctrl+A / Ctrl+C / Ctrl+V /
Shift+Home), hardened clipboard operations with auto-retry, and the in-place
translation workflow.

Presentation-agnostic on purpose: it reports what it is doing through
callbacks and never touches a window, so the same manager backs both the
WebView UI and any other front end.

    on_translated_callback     a translation finished and was pasted
    on_progress_callback       the workflow moved to a new stage
    on_status_change_callback  the service was paused or resumed

on_progress_callback(stage, **detail) fires on the worker thread with:

    "reading"                            the hotkey fired, text is being read
    "translating", text=<source text>    handed to the engine
    "pasting",     text=<translation>    about to replace the text
    "done",        original=, translated=, source=, target=, engine=, fell_back=
    "undoing"                            putting the original text back
    "undone",      text=<original text>  the translation was reverted
    "failed",      kind=, reason=

``kind`` is one of "no_text", "engine", "crash", "no_undo" (nothing recorded to
revert, or the record expired) or "undo_changed" (the field no longer holds the
translation, so reverting would destroy whatever replaced it).
"""
import ctypes
import threading
import time
import winsound
import pyperclip
import keyboard

import win_input

from translator_core import (is_translation_error, translate_text,
                             translation_error_reason)

# Windows Virtual Key Codes
VK_CONTROL = 0x11
VK_MENU = 0x12     # Alt key
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_HOME = 0x24
VK_A = 0x41
VK_C = 0x43
VK_V = 0x56

KEYEVENTF_KEYUP = 0x0002
user32 = ctypes.windll.user32


def is_modifier_physically_pressed():
    """Check whether Ctrl, Alt, or Shift are still physically held down."""
    return bool(
        (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) or
        (user32.GetAsyncKeyState(VK_MENU) & 0x8000) or
        (user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
    )


def wait_modifiers_released(timeout=0.25):
    """Wait for physical modifier keys to be released before simulating new combos."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not is_modifier_physically_pressed():
            break
        time.sleep(0.015)
    release_modifiers()


def release_modifiers():
    """Release any held modifier keys virtually to prevent combo conflicts."""
    win_input.release_modifiers()


def press_and_release(key_code, modifier_code=None, delay=0.03):
    """Simulate a keypress, with a scan code a game can actually see.

    This used to be ``keybd_event(vk, 0, ...)`` - scan code zero. Ordinary
    windows read the virtual key and were perfectly happy; games read the scan
    code through DirectInput or Raw Input, saw zero, and ignored every
    keystroke this app has ever sent them. See win_input for the detail.
    """
    win_input.press_and_release(key_code, modifier_code, delay=delay)


def type_text(text, delay=0.0):
    """Type text character by character instead of pasting it.

    For text boxes that never implemented Ctrl+V - which is most text boxes
    drawn by a game engine rather than by Windows.
    """
    win_input.type_text(text)


#: How long a translation stays revertable. Long enough to notice a bad
#: translation and react; short enough that Ctrl+Alt+Z pressed much later
#: cannot resurrect text from a conversation the user has moved on from.
UNDO_MEMORY_SECONDS = 300

#: How long to wait after Ctrl+V before putting the user's clipboard back.
#: The target application reads the clipboard when it handles the paste, and
#: Chromium-based apps (Discord, Slack, anything Electron) do that a beat after
#: the keystroke rather than during it.
CLIPBOARD_RESTORE_DELAY = 0.45


def selection_mode_name(config):
    return config.get("selection_mode", "all")


def safe_clipboard_copy(text: str, retries: int = 4, delay: float = 0.025) -> bool:
    """Safely copy text to Windows clipboard with retry backoff against lock conflicts."""
    for attempt in range(retries):
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            time.sleep(delay * (attempt + 1))
    return False


def safe_clipboard_paste(retries: int = 4, delay: float = 0.025) -> str:
    """Safely paste text from Windows clipboard with retry backoff."""
    for attempt in range(retries):
        try:
            return pyperclip.paste()
        except Exception:
            time.sleep(delay * (attempt + 1))
    return ""


def wait_for_clipboard_change(sentinel: str, timeout: float = 0.35,
                              poll: float = 0.008) -> str:
    """Poll the clipboard until the target app has written the copied text.

    The previous code slept a flat 60 ms after Ctrl+C and hoped that was
    enough. Polling returns as soon as the clipboard actually changes -
    usually well under 30 ms - and still waits the full timeout for slow apps,
    so this is both faster in the common case and more reliable in the worst.
    """
    deadline = time.perf_counter() + timeout
    while True:
        current = safe_clipboard_paste(retries=1)
        if current and current != sentinel:
            return current
        if time.perf_counter() >= deadline:
            return current
        time.sleep(poll)


class HotkeyManager:
    def __init__(self, config, on_translated_callback=None,
                 on_status_change_callback=None, on_progress_callback=None):
        self.config = config
        self.on_translated_callback = on_translated_callback
        self.on_status_change_callback = on_status_change_callback
        self.on_progress_callback = on_progress_callback
        
        self.is_active = True
        self._is_processing = False
        self.current_hotkey_ref = None
        self.lock = threading.Lock()

        #: The last translation this manager pasted, so Ctrl+Alt+Z can put the
        #: original back. One slot, not a stack: reverting twice would mean
        #: guessing which of several earlier texts belongs in this field.
        self._last_paste = None

        #: Outcome of the most recent undo-hotkey binding, for the settings UI.
        self.undo_registered = False
        self.undo_error = ""

    def start(self):
        """Register the translate and undo hotkeys."""
        self._register_all()

    def stop(self):
        """Unregister all hotkeys."""
        try:
            if self.current_hotkey_ref:
                try:
                    keyboard.remove_hotkey(self.current_hotkey_ref)
                except Exception:
                    pass
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def undo_hotkey(self) -> str:
        """The configured undo combination, or '' when it is switched off."""
        if not self.config.get("enable_undo", True):
            return ""
        return (self.config.get("undo_hotkey") or "").strip().lower()

    def _register_all(self, translate_key=None):
        """Bind both hotkeys.

        They are registered together because ``keyboard`` has no way to remove
        one binding by name reliably, so every change unhooks everything and
        rebuilds. Registering them separately meant whichever went second
        silently wiped the first.

        ``translate_key`` tries a candidate without committing it. Nothing here
        writes to ``self.config`` - the caller decides whether a combination
        that registered is worth keeping, so a rejected one cannot be left in
        the user's settings.
        """
        with self.lock:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass

            if translate_key is None:
                translate_key = self.config.get("hotkey", "ctrl+alt+t")
            translate_key = translate_key.strip().lower()
            ok, message = True, ""
            try:
                self.current_hotkey_ref = keyboard.add_hotkey(
                    translate_key, self._on_hotkey_triggered, suppress=False)
                print(f"[HotkeyManager] Registered hotkey: {translate_key}")
                message = f"ลงทะเบียนคีย์ลัด '{translate_key}' สำเร็จ"
            except Exception as exc:
                self.current_hotkey_ref = None
                print(f"[HotkeyManager] Failed to register hotkey {translate_key}: {exc}")
                ok, message = False, str(exc)

            undo_key = self.undo_hotkey()
            self.undo_registered = False
            self.undo_error = ""
            # A clash would bind undo over translation and leave the app unable
            # to translate at all, which is far worse than having no undo.
            if undo_key and undo_key == translate_key:
                self.undo_error = "same as the translate hotkey"
                print("[HotkeyManager] Undo hotkey matches the translate hotkey; "
                      "undo is disabled")
            elif undo_key:
                try:
                    keyboard.add_hotkey(undo_key, self._on_undo_triggered,
                                        suppress=False)
                    self.undo_registered = True
                    print(f"[HotkeyManager] Registered undo hotkey: {undo_key}")
                except Exception as exc:
                    self.undo_error = str(exc)
                    print(f"[HotkeyManager] Failed to register undo hotkey "
                          f"{undo_key}: {exc}")

            return ok, message

    def register_hotkey(self, hotkey_str):
        """Try a translate hotkey and rebind both. Does not persist anything."""
        return self._register_all(hotkey_str)

    def set_active(self, active: bool):
        """Toggle service active state."""
        self.is_active = active
        if self.on_status_change_callback:
            self.on_status_change_callback(active)

    def update_config(self, new_config):
        """Update active configuration."""
        before = (self.config.get("hotkey", "").lower().strip(),
                  self.undo_hotkey())
        self.config = new_config
        after = (new_config.get("hotkey", "").lower().strip(),
                 self.undo_hotkey())

        if before != after:
            self._register_all()

    def _progress(self, stage, **detail):
        """Report a stage. Never let the presentation layer break translation."""
        callback = self.on_progress_callback
        if callback is None:
            return
        try:
            callback(stage, **detail)
        except Exception as exc:
            print(f"[HotkeyManager] Progress callback failed at '{stage}': {exc}")

    def _on_hotkey_triggered(self):
        """Triggered immediately when global hotkey is pressed."""
        if not self.is_active:
            print("[HotkeyManager] Hotkey ignored: the service is paused")
            return
        
        if self._is_processing:
            print("[HotkeyManager] Hotkey ignored: a translation is still running")
            return
        
        # Run translation workflow in a background thread to prevent hook freezing
        threading.Thread(target=self._execute_in_place_translation, daemon=True).start()

    def _on_undo_triggered(self):
        """Undo runs even while paused - it repairs, it does not translate."""
        if self._is_processing:
            print("[HotkeyManager] Undo ignored: a translation is still running")
            return
        threading.Thread(target=self._execute_undo, daemon=True).start()

    def _restore_clipboard_later(self, previous, pasted,
                                 delay=CLIPBOARD_RESTORE_DELAY):
        """Give the paste time to land, then put the user's clipboard back.

        Reading the selection means going through the clipboard, which used to
        leave the translation sitting there afterwards - so copying a link,
        translating one message, and pasting the link somewhere else pasted the
        translation instead. The old text was only restored when the
        translation *failed*.

        Guarded twice: nothing happens when there was no text to restore, and
        the write only goes ahead if the clipboard still holds exactly what we
        put there, so anything the user copied in the meantime survives.

        Text only. A clipboard holding an image or files cannot be captured
        this way and is lost - the same as before this existed.

        Switching ``restore_clipboard`` off leaves the translation on the
        clipboard instead, for people who translate in order to paste the
        result somewhere else.
        """
        if not self.config.get("restore_clipboard", True):
            return
        if not previous or previous == pasted:
            return

        def worker():
            time.sleep(delay)
            try:
                if safe_clipboard_paste() == pasted:
                    safe_clipboard_copy(previous)
            except Exception as exc:
                print(f"[HotkeyManager] Could not restore the clipboard: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _select_for_replace(self, selection_mode, key_delay):
        """Select the text a paste would replace, for the given mode."""
        if selection_mode == "line":
            press_and_release(VK_HOME, VK_SHIFT, delay=key_delay)
        else:
            press_and_release(VK_A, VK_CONTROL, delay=key_delay)

    def _execute_undo(self):
        """Put the original text back where the last translation went.

        Deliberately conservative. It re-reads the field and only writes if it
        still contains exactly the translation that was pasted; if the user has
        typed since, or moved to a different box, it refuses rather than
        destroying whatever is there now. Refusing is a much cheaper mistake
        than overwriting.
        """
        self._is_processing = True
        try:
            memory = self._last_paste
            if not memory:
                self._progress("failed", kind="no_undo", reason="")
                return
            if time.time() - memory["at"] > UNDO_MEMORY_SECONDS:
                self._last_paste = None
                self._progress("failed", kind="no_undo", reason="")
                return

            self._progress("undoing")
            wait_modifiers_released(timeout=0.20)
            time.sleep(0.03)
            key_delay = self.config.get("key_delay_ms", 30) / 1000.0

            previous_clipboard = safe_clipboard_paste()

            self._select_for_replace(memory["selection_mode"], key_delay)
            sentinel = f"__TYPIST_UNDO_{time.time()}__"
            safe_clipboard_copy(sentinel)
            time.sleep(0.02)
            press_and_release(VK_C, VK_CONTROL, delay=key_delay)
            current = wait_for_clipboard_change(sentinel, timeout=0.35)

            if current.strip() != memory["translated"].strip():
                if previous_clipboard:
                    safe_clipboard_copy(previous_clipboard)
                print("[HotkeyManager] Undo refused: the text has changed since")
                self._progress("failed", kind="undo_changed", reason="")
                return

            typing = self.config.get("output_mode", "paste") == "type"
            if typing:
                type_text(memory["original"])
            else:
                safe_clipboard_copy(memory["original"])
                time.sleep(0.04)
                press_and_release(VK_V, VK_CONTROL, delay=key_delay)
            time.sleep(0.04)

            # One-shot: the translation it described is no longer on screen.
            self._last_paste = None
            self._restore_clipboard_later(
                previous_clipboard,
                memory["translated"] if typing else memory["original"])

            if self.config.get("sound_effect", True):
                try:
                    winsound.MessageBeep(winsound.MB_OK)
                except Exception:
                    pass

            self._progress("undone", text=memory["original"])
        except win_input.InputBlocked as exc:
            print(f"[HotkeyManager] Undo input refused: {exc}")
            self._progress("failed", kind="blocked", reason=str(exc))
        except Exception as exc:
            print(f"[HotkeyManager] Error during undo: {exc}")
            self._progress("failed", kind="crash", reason=str(exc))
        finally:
            self._is_processing = False

    def _execute_in_place_translation(self):
        """Main translation and replacement sequence."""
        self._is_processing = True
        try:
            # 0. Tell the user something is happening. This comes first: the
            # steps below take anywhere from 300 ms to several seconds, and
            # until this call there was nothing on screen to say the hotkey
            # had even registered.
            self._progress("reading")
            print(f"[HotkeyManager] Hotkey fired ({selection_mode_name(self.config)})")

            # 1. Wait for physical modifier keys to release
            wait_modifiers_released(timeout=0.20)
            time.sleep(0.03)
            
            selection_mode = self.config.get("selection_mode", "all")
            key_delay = self.config.get("key_delay_ms", 30) / 1000.0

            # 2. Perform text selection based on configured mode
            if selection_mode == "all":
                press_and_release(VK_A, VK_CONTROL, delay=key_delay)
            elif selection_mode == "line":
                press_and_release(VK_HOME, VK_SHIFT, delay=key_delay)
            elif selection_mode in ("smart", "selection"):
                pass

            # 3. Copy selected text to clipboard (Ctrl + C)
            old_clipboard = safe_clipboard_paste()

            # Unique sentinel to verify if new text was captured
            sentinel_token = f"__TYPIST_SENTINEL_{time.time()}__"
            safe_clipboard_copy(sentinel_token)
            time.sleep(0.02)

            # Send Ctrl + C, then wait only as long as the app actually needs.
            press_and_release(VK_C, VK_CONTROL, delay=key_delay)
            captured_text = wait_for_clipboard_change(sentinel_token, timeout=0.35)

            # What undo will have to re-select. 'smart' and 'selection' start
            # from whatever the user highlighted, which undo cannot recreate -
            # it falls back to selecting everything and then refuses if that is
            # not exactly the translation.
            effective_mode = "all" if selection_mode == "all" else (
                "line" if selection_mode == "line" else "selection")

            # In 'smart' mode: if sentinel is unchanged, fallback to Ctrl + A
            if selection_mode == "smart" and (captured_text == sentinel_token or not captured_text):
                press_and_release(VK_A, VK_CONTROL, delay=key_delay)
                time.sleep(0.03)
                press_and_release(VK_C, VK_CONTROL, delay=key_delay)
                captured_text = wait_for_clipboard_change(sentinel_token, timeout=0.35)
                effective_mode = "all"

            # If still sentinel or empty, abort cleanly
            if captured_text == sentinel_token or not captured_text or not captured_text.strip():
                if old_clipboard:
                    safe_clipboard_copy(old_clipboard)
                print("[HotkeyManager] Nothing captured - is the caret in a "
                      "text field?")
                self._progress("failed", kind="no_text", reason="")
                return

            original_text = captured_text

            # 4. Perform translation using full configuration
            self._progress("translating", text=original_text)
            outcome = {}
            translated_text, source_lang, target_lang = translate_text(
                original_text,
                config=self.config,
                report=outcome,
            )

            if not translated_text or is_translation_error(translated_text):
                print(f"[HotkeyManager] Translation failed or empty: {translated_text}")
                if old_clipboard:
                    safe_clipboard_copy(old_clipboard)
                self._progress("failed", kind="engine",
                               reason=translation_error_reason(translated_text))
                return

            # 5. Put the translation where the original was.
            self._progress("pasting", text=translated_text)
            if self.config.get("output_mode", "paste") == "type":
                # Typed one character at a time, as WM_CHAR. Slower, and it
                # never touches the clipboard - but it reaches text boxes drawn
                # by a game engine, which mostly never implemented Ctrl+V.
                type_text(translated_text)
                time.sleep(0.04)
            else:
                safe_clipboard_copy(translated_text)
                time.sleep(0.04)
                press_and_release(VK_V, VK_CONTROL, delay=key_delay)
                time.sleep(0.04)

            # 7. Remember enough to undo this, and give the user their
            # clipboard back once the paste has been consumed.
            self._last_paste = {
                "original": original_text,
                "translated": translated_text,
                "selection_mode": effective_mode,
                "at": time.time(),
            }
            self._restore_clipboard_later(
                old_clipboard,
                translated_text if self.config.get("output_mode", "paste")
                != "type" else captured_text)

            # 8. Audio cue if enabled
            if self.config.get("sound_effect", True):
                try:
                    winsound.MessageBeep(winsound.MB_OK)
                except Exception:
                    pass

            # 9. Hand the result to whoever owns the presentation layer.
            # The manager deliberately does not know about toasts or windows:
            # the entry point decides how to notify and where to store it.
            self._progress("done", original=original_text,
                           translated=translated_text,
                           source=source_lang, target=target_lang,
                           engine=outcome.get("engine", ""),
                           fell_back=bool(outcome.get("fell_back")))

            if self.on_translated_callback:
                self.on_translated_callback(
                    original_text=original_text,
                    translated_text=translated_text,
                    source_lang=source_lang,
                    target_lang=target_lang
                )

        except win_input.InputBlocked as exc:
            print(f"[HotkeyManager] Input refused: {exc}")
            self._progress("failed", kind="blocked", reason=str(exc))
        except Exception as e:
            print(f"[HotkeyManager] Error during translation execution: {e}")
            self._progress("failed", kind="crash", reason=str(e))
        finally:
            self._is_processing = False
