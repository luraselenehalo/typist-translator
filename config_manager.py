"""
Configuration Manager for Typist Translator

Reads and writes the user's settings. Two properties matter more than they look:

* **Writes are atomic.** This file holds the user's API keys. Truncating it and
  then writing means a crash, a power cut or the self-update killing the process
  mid-write leaves a zero-length file - and load_config would quietly hand back
  DEFAULT_CONFIG, silently wiping the keys. The new content goes to a temporary
  file that is flushed to disk and only then renamed over the old one, so the
  file on disk is always either entirely the old settings or entirely the new.
* **Settings are found after a move.** Before the installer existed, config.json
  sat beside the application. Installed builds keep it in %APPDATA% so that
  replacing the program directory during an update cannot take it with them, and
  on first run an old file beside the executable is adopted rather than ignored.
"""
import json
import os
import shutil

import paths

DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+t",
    "selection_mode": "all",  # "all" (Ctrl+A), "line" (Shift+Home), "smart", "selection"
    "swap_mode": "pair",      # "pair" (Auto-Swap between Lang A & B) or "fixed" (Fixed Target)
    "swap_lang_a": "th",      # Primary language code
    "swap_lang_b": "en",      # Secondary language code
    "target_language": "auto_swap",  # Legacy / fixed target reference
    
    # Translation Engine Settings
    "translation_engine": "google_gtx",  # "google_gtx", "mymemory", "deepl", "gemini", "openai"
    "engine_api_keys": {
        "deepl": "",
        "gemini": "",
        "openai": "",
        "groq": ""
    },
    "engine_models": {
        "gemini": "gemini-1.5-flash",
        "openai": "gpt-4o-mini"
    },
    "openai_base_url": "https://api.openai.com/v1",
    
    # UI & Experience Settings
    "sound_effect": True,
    "show_toast_notification": True,
    "show_progress_overlay": True,   # "translating..." chip over every window
    "check_for_updates": True,       # look for a new release, and say so
    "use_custom_titlebar": True,
    "minimize_to_tray_on_close": True,
    "start_minimized": False,
    "key_delay_ms": 30,
    "appearance_mode": "System",
    "app_language": "th"   # Interface language: th / en / ja / zh-CN
}

# Beside the sources while developing; under %APPDATA% once installed, so that
# replacing the whole install directory during an update cannot take the user's
# hotkey, language pair and API keys with it.
CONFIG_FILE = paths.user_data("config.json")


def _adopt_legacy_config():
    """Bring settings over from a pre-installer copy, once.

    Versions up to 3.0.0 shipped as a zip that was unpacked anywhere and kept
    config.json beside the app. An installed 3.1.0 looks in %APPDATA% instead,
    so without this an upgrading user silently loses their hotkey, language
    pair and every API key.

    Only the executable's own folder can be searched - nothing records where a
    hand-unzipped copy was put, so those are migrated by the user, not by us.
    """
    if not paths.FROZEN or os.path.exists(CONFIG_FILE):
        return
    legacy = os.path.join(paths.INSTALL_DIR, "config.json")
    if not os.path.isfile(legacy):
        return
    try:
        shutil.copy2(legacy, CONFIG_FILE)
        print(f"[Config] Adopted settings from the previous install: {legacy}")
    except OSError as exc:
        print(f"[Config] Could not adopt {legacy}: {exc}")


def load_config():
    """Load configuration from config.json or return defaults with deep merge."""
    _adopt_legacy_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_CONFIG.copy()
                # Deep merge dictionary fields like engine_api_keys and engine_models
                for k, v in data.items():
                    if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                        config[k] = {**config[k], **v}
                    else:
                        config[k] = v
                return config
        except Exception as e:
            print(f"[Config] Error loading config, using defaults: {e}")
            return DEFAULT_CONFIG.copy()
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config_data):
    """Write the settings so that an interrupted write cannot destroy them.

    Write to a sibling temporary file, force it to disk, then rename it over
    the target. os.replace is atomic on the same volume on Windows, so a reader
    only ever sees the complete old file or the complete new one.
    """
    directory = os.path.dirname(CONFIG_FILE) or "."
    temporary = CONFIG_FILE + ".tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(config_data, handle, indent=4, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())   # rename is only safe once it is on disk
        os.replace(temporary, CONFIG_FILE)
        return True
    except Exception as e:
        print(f"[Config] Error saving config: {e}")
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        return False
