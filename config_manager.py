"""
Configuration Manager for Typist Translator
Handles loading, saving, and migrating user preferences to config.json
"""
import os
import json

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
    "use_custom_titlebar": True,
    "minimize_to_tray_on_close": True,
    "start_minimized": False,
    "key_delay_ms": 30,
    "appearance_mode": "System",
    "app_language": "th"   # Interface language: th / en / ja / zh-CN
}

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    """Load configuration from config.json or return defaults with deep merge."""
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
    """Save configuration dictionary to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Config] Error saving config: {e}")
        return False
