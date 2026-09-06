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
    "done",        original=, translated=, source=, target=
    "failed",      kind=, reason=        kind is "no_text" | "engine" | "crash"
"""
import ctypes
import threading
import time
import winsound
import pyperclip
import keyboard

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
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


def press_and_release(key_code, modifier_code=None, delay=0.03):
    """Simulate key press and release with an optional modifier."""
    if modifier_code:
        user32.keybd_event(modifier_code, 0, 0, 0)
        time.sleep(delay)
    
    user32.keybd_event(key_code, 0, 0, 0)
    time.sleep(delay)
    user32.keybd_event(key_code, 0, KEYEVENTF_KEYUP, 0)
    
    if modifier_code:
        time.sleep(delay)
        user32.keybd_event(modifier_code, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(delay)


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
        
    def start(self):
        """Register hotkey listener."""
        self.register_hotkey(self.config.get("hotkey", "ctrl+alt+t"))

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

    def register_hotkey(self, hotkey_str):
        """Safely register a new hotkey string (e.g. 'ctrl+alt+t', 'f8')."""
        with self.lock:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            
            cleaned_hotkey = hotkey_str.strip().lower()
            try:
                self.current_hotkey_ref = keyboard.add_hotkey(
                    cleaned_hotkey, 
                    self._on_hotkey_triggered,
                    suppress=False
                )
                print(f"[HotkeyManager] Registered hotkey: {cleaned_hotkey}")
                return True, f"ลงทะเบียนคีย์ลัด '{cleaned_hotkey}' สำเร็จ"
            except Exception as e:
                print(f"[HotkeyManager] Failed to register hotkey {cleaned_hotkey}: {e}")
                return False, str(e)

    def set_active(self, active: bool):
        """Toggle service active state."""
        self.is_active = active
        if self.on_status_change_callback:
            self.on_status_change_callback(active)

    def update_config(self, new_config):
        """Update active configuration."""
        old_hotkey = self.config.get("hotkey", "").lower().strip()
        new_hotkey = new_config.get("hotkey", "").lower().strip()
        self.config = new_config
        
        if old_hotkey != new_hotkey:
            self.register_hotkey(new_hotkey)

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

            # In 'smart' mode: if sentinel is unchanged, fallback to Ctrl + A
            if selection_mode == "smart" and (captured_text == sentinel_token or not captured_text):
                press_and_release(VK_A, VK_CONTROL, delay=key_delay)
                time.sleep(0.03)
                press_and_release(VK_C, VK_CONTROL, delay=key_delay)
                captured_text = wait_for_clipboard_change(sentinel_token, timeout=0.35)

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
            translated_text, source_lang, target_lang = translate_text(
                original_text, 
                config=self.config
            )

            if not translated_text or is_translation_error(translated_text):
                print(f"[HotkeyManager] Translation failed or empty: {translated_text}")
                self._progress("failed", kind="engine",
                               reason=translation_error_reason(translated_text))
                return

            # 5. Place translated text into clipboard
            safe_clipboard_copy(translated_text)
            self._progress("pasting", text=translated_text)
            time.sleep(0.04)

            # 6. Paste into the active text box (Ctrl + V)
            press_and_release(VK_V, VK_CONTROL, delay=key_delay)
            time.sleep(0.04)

            # 7. Audio cue if enabled
            if self.config.get("sound_effect", True):
                try:
                    winsound.MessageBeep(winsound.MB_OK)
                except Exception:
                    pass

            # 8. Hand the result to whoever owns the presentation layer.
            # The manager deliberately does not know about toasts or windows:
            # the entry point decides how to notify and where to store it.
            self._progress("done", original=original_text,
                           translated=translated_text,
                           source=source_lang, target=target_lang)

            if self.on_translated_callback:
                self.on_translated_callback(
                    original_text=original_text,
                    translated_text=translated_text,
                    source_lang=source_lang,
                    target_lang=target_lang
                )

        except Exception as e:
            print(f"[HotkeyManager] Error during translation execution: {e}")
            self._progress("failed", kind="crash", reason=str(e))
        finally:
            self._is_processing = False
