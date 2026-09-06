"""
Automated Smoke Test for Typist Translator

Quick end-to-end sanity check of the core pieces: configuration, the
translation engines, global hotkey registration and the API bridge the UI
talks to.

Deeper coverage lives in:
    test_backend.py   the full backend contract, headless
    test_webview.py   the real React window driven through the DOM
"""
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config_manager import load_config, save_config, DEFAULT_CONFIG
from translator_core import translate_text, contains_thai, detect_languages
from hotkey_manager import HotkeyManager


def test_config():
    print("[Test 1] Testing config manager...")
    cfg = load_config()
    assert "hotkey" in cfg, "Config missing hotkey"
    assert "selection_mode" in cfg, "Config missing selection_mode"
    assert "target_language" in cfg, "Config missing target_language"
    print("  -> load_config passed:", cfg["hotkey"], cfg["selection_mode"])


def test_translator():
    print("[Test 2] Testing translator core...")
    # Thai detection
    assert contains_thai("สวัสดี"), "Thai detection failed on 'สวัสดี'"
    assert not contains_thai("Hello World 123"), "Thai detection false positive on English"
    
    # Auto-swap logic
    s1, t1 = detect_languages("สวัสดีวันจันทร์", "auto_swap")
    assert (s1, t1) == ("th", "en"), f"Expected ('th', 'en'), got ({s1}, {t1})"
    
    s2, t2 = detect_languages("Good morning", "auto_swap")
    assert (s2, t2) in [("auto", "th"), ("en", "th")], f"Expected ('auto'/'en', 'th'), got ({s2}, {t2})"

    # Online translation
    res_en, _, _ = translate_text("ขอบคุณมากครับ")
    print(f"  -> Thai to English: 'ขอบคุณมากครับ' => '{res_en}'")
    assert len(res_en) > 0 and "thank" in res_en.lower(), f"Unexpected translation: {res_en}"

    res_th, _, _ = translate_text("Thank you very much")
    print(f"  -> English to Thai: 'Thank you very much' => '{res_th}'")
    assert len(res_th) > 0 and contains_thai(res_th), f"Unexpected translation: {res_th}"
    print("  -> translator_core passed!")


def test_hotkey_registration():
    print("[Test 3] Testing HotkeyManager registration...")
    cfg = load_config()
    mgr = HotkeyManager(config=cfg)
    success, msg = mgr.register_hotkey("ctrl+alt+t")
    assert success, f"Failed to register ctrl+alt+t: {msg}"
    print("  -> Registered ctrl+alt+t successfully:", msg)

    success_f8, msg_f8 = mgr.register_hotkey("f8")
    assert success_f8, f"Failed to register f8: {msg_f8}"
    print("  -> Registered f8 successfully:", msg_f8)
    
    mgr.stop()
    print("  -> hotkey_manager registration passed!")


def test_api_bridge():
    print("[Test 4] Testing the API bridge the UI talks to...")
    from api_bridge import Api
    from history_store import HistoryStore
    from tray_manager import TrayManager

    cfg = load_config()
    hotkey_mgr = HotkeyManager(config=cfg)
    api = Api(config=cfg, hotkey_manager=hotkey_mgr,
              tray_manager=TrayManager(), history=HistoryStore())

    boot = api.get_bootstrap()
    assert boot["ok"] is True, boot
    data = boot["data"]
    assert data["catalogs"] and data["engines"] and data["config"]
    print(f"  -> bootstrap returned {len(data['engines'])} engines, "
          f"{len(data['catalogs'])} interface languages")

    result = api.translate("ทดสอบ")
    assert result["ok"] is True, result
    assert result["data"]["translated"], result
    print(f"  -> translate through the bridge: 'ทดสอบ' => "
          f"'{result['data']['translated']}'")

    assert len(api.history) == 1, "translation was not recorded in history"
    print("  -> history recorded the translation")

    hotkey_mgr.stop()
    print("  -> api_bridge passed!")


if __name__ == "__main__":
    print("=== STARTING AUTOMATED TESTS ===")
    test_config()
    test_translator()
    test_hotkey_registration()
    test_api_bridge()
    print("=== ALL TESTS PASSED SUCCESSFULLY! ===")
