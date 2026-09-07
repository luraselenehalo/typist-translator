"""
Translator Core Module - V2
Handles multi-engine translation (Google GTX, MyMemory, DeepL, Gemini AI, OpenAI/Groq),
universal language script detection for custom language pairs, 100+ languages database,
and resilient auto-fallback mechanisms.
"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

from http_pool import fetch_json

# =====================================================================
# Translation memory cache
# =====================================================================
# Pressing the hotkey on the same phrase twice, re-running a sandbox test, or
# re-translating a message that was pasted back is common. Serving those from
# memory turns a ~300 ms network round trip into a no-op.
TRANSLATION_CACHE_SIZE = 256
MAX_CACHEABLE_CHARS = 2000

_cache = OrderedDict()
_cache_lock = threading.Lock()


def _cache_signature(engine: str, cfg: dict) -> str:
    """Config values that change what an engine returns for the same input."""
    models = cfg.get("engine_models", {}) or {}
    if engine == "gemini":
        return "gemini:" + str(models.get("gemini", ""))
    if engine == "openai":
        return "openai:%s:%s" % (models.get("openai", ""), cfg.get("openai_base_url", ""))
    return engine


def _cache_get(key):
    with _cache_lock:
        value = _cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
        return value


def _cache_put(key, value):
    if len(key[-1]) > MAX_CACHEABLE_CHARS:
        return
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > TRANSLATION_CACHE_SIZE:
            _cache.popitem(last=False)


def clear_translation_cache():
    """Drop every memoised translation (call when engine settings change)."""
    with _cache_lock:
        _cache.clear()


# =====================================================================
# Engine cooldown
# =====================================================================
#: How long an engine is moved to the back of the queue after it fails.
#: A rate-limited endpoint stays rate-limited for minutes, and without this
#: every single translation would pay that engine's timeout again before
#: reaching the one that actually works.
ENGINE_COOLDOWN_SECONDS = 90

_cooldown = {}
_cooldown_lock = threading.Lock()


def _mark_engine_failed(engine):
    with _cooldown_lock:
        _cooldown[engine] = time.time() + ENGINE_COOLDOWN_SECONDS


def _mark_engine_working(engine):
    with _cooldown_lock:
        _cooldown.pop(engine, None)


def _engine_in_cooldown(engine) -> bool:
    with _cooldown_lock:
        until = _cooldown.get(engine, 0)
        if until and until <= time.time():
            del _cooldown[engine]
            return False
        return bool(until)


def reset_engine_cooldowns():
    """Forget every recorded failure (call when engine settings change)."""
    with _cooldown_lock:
        _cooldown.clear()


# A language-neutral sentinel so callers can detect a failed translation
# without matching a localised message.
TRANSLATION_ERROR_PREFIX = "[TRANSLATE_ERROR]"


def is_translation_error(text) -> bool:
    """True when translate_text returned a failure marker instead of a result."""
    return bool(text) and str(text).startswith(TRANSLATION_ERROR_PREFIX)


def translation_error_reason(text) -> str:
    """The underlying reason from a failure marker, for display."""
    if not is_translation_error(text):
        return ""
    return str(text)[len(TRANSLATION_ERROR_PREFIX):].strip()

# Comprehensive 100+ Languages Database
LANGUAGES_DB = {
    "th": {"code": "th", "name_th": "ไทย", "name_en": "Thai", "flag": "🇹🇭"},
    "en": {"code": "en", "name_th": "อังกฤษ", "name_en": "English", "flag": "🇬🇧"},
    "ja": {"code": "ja", "name_th": "ญี่ปุ่น", "name_en": "Japanese", "flag": "🇯🇵"},
    "zh-CN": {"code": "zh-CN", "name_th": "จีน (ตัวย่อ)", "name_en": "Chinese (Simplified)", "flag": "🇨🇳"},
    "zh-TW": {"code": "zh-TW", "name_th": "จีน (ตัวเต็ม)", "name_en": "Chinese (Traditional)", "flag": "🇹🇼"},
    "ko": {"code": "ko", "name_th": "เกาหลี", "name_en": "Korean", "flag": "🇰🇷"},
    "de": {"code": "de", "name_th": "เยอรมัน", "name_en": "German", "flag": "🇩🇪"},
    "fr": {"code": "fr", "name_th": "ฝรั่งเศส", "name_en": "French", "flag": "🇫🇷"},
    "es": {"code": "es", "name_th": "สเปน", "name_en": "Spanish", "flag": "🇪🇸"},
    "ru": {"code": "ru", "name_th": "รัสเซีย", "name_en": "Russian", "flag": "🇷🇺"},
    "vi": {"code": "vi", "name_th": "เวียดนาม", "name_en": "Vietnamese", "flag": "🇻🇳"},
    "id": {"code": "id", "name_th": "อินโดนีเซีย", "name_en": "Indonesian", "flag": "🇮🇩"},
    "ms": {"code": "ms", "name_th": "มาเลย์", "name_en": "Malay", "flag": "🇲🇾"},
    "it": {"code": "it", "name_th": "อิตาลี", "name_en": "Italian", "flag": "🇮🇹"},
    "pt": {"code": "pt", "name_th": "โปรตุเกส", "name_en": "Portuguese", "flag": "🇵🇹"},
    "ar": {"code": "ar", "name_th": "อาหรับ", "name_en": "Arabic", "flag": "🇸🇦"},
    "hi": {"code": "hi", "name_th": "ฮินดี", "name_en": "Hindi", "flag": "🇮🇳"},
    "nl": {"code": "nl", "name_th": "ดัตช์", "name_en": "Dutch", "flag": "🇳🇱"},
    "pl": {"code": "pl", "name_th": "โปแลนด์", "name_en": "Polish", "flag": "🇵🇱"},
    "tr": {"code": "tr", "name_th": "ตุรกี", "name_en": "Turkish", "flag": "🇹🇷"},
    "sv": {"code": "sv", "name_th": "สวีเดน", "name_en": "Swedish", "flag": "🇸🇪"},
    "da": {"code": "da", "name_th": "เดนมาร์ก", "name_en": "Danish", "flag": "🇩🇰"},
    "no": {"code": "no", "name_th": "นอร์เวย์", "name_en": "Norwegian", "flag": "🇳🇴"},
    "fi": {"code": "fi", "name_th": "ฟินแลนด์", "name_en": "Finnish", "flag": "🇫🇮"},
    "el": {"code": "el", "name_th": "กรีก", "name_en": "Greek", "flag": "🇬🇷"},
    "cs": {"code": "cs", "name_th": "เช็ก", "name_en": "Czech", "flag": "🇨🇿"},
    "hu": {"code": "hu", "name_th": "ฮังการี", "name_en": "Hungarian", "flag": "🇭🇺"},
    "ro": {"code": "ro", "name_th": "โรมาเนีย", "name_en": "Romanian", "flag": "🇷🇴"},
    "uk": {"code": "uk", "name_th": "ยูเครน", "name_en": "Ukrainian", "flag": "🇺🇦"},
    "he": {"code": "he", "name_th": "ฮีบรู", "name_en": "Hebrew", "flag": "🇮🇱"},
    "tl": {"code": "tl", "name_th": "ตากาล็อก (ฟิลิปปินส์)", "name_en": "Tagalog (Filipino)", "flag": "🇵🇭"},
    "my": {"code": "my", "name_th": "พม่า", "name_en": "Burmese", "flag": "🇲🇲"},
    "lo": {"code": "lo", "name_th": "ลาว", "name_en": "Lao", "flag": "🇱🇦"},
    "km": {"code": "km", "name_th": "เขมร", "name_en": "Khmer", "flag": "🇰🇭"},
    "ta": {"code": "ta", "name_th": "ทมิฬ", "name_en": "Tamil", "flag": "🇮🇳"},
    "fa": {"code": "fa", "name_th": "เปอร์เซีย", "name_en": "Persian", "flag": "🇮🇷"},
    "ur": {"code": "ur", "name_th": "อูรดู", "name_en": "Urdu", "flag": "🇵🇰"},
    "bn": {"code": "bn", "name_th": "เบงกาลี", "name_en": "Bengali", "flag": "🇧🇩"},
    "bg": {"code": "bg", "name_th": "บัลแกเรีย", "name_en": "Bulgarian", "flag": "🇧🇬"},
    "hr": {"code": "hr", "name_th": "โครเอเชีย", "name_en": "Croatian", "flag": "🇭🇷"},
    "sk": {"code": "sk", "name_th": "สโลวาเกีย", "name_en": "Slovak", "flag": "🇸🇰"},
    "sr": {"code": "sr", "name_th": "เซอร์เบีย", "name_en": "Serbian", "flag": "🇷🇸"},
    "sl": {"code": "sl", "name_th": "สโลวีเนีย", "name_en": "Slovenian", "flag": "🇸🇮"},
    "lt": {"code": "lt", "name_th": "ลิทัวเนีย", "name_en": "Lithuanian", "flag": "🇱🇹"},
    "lv": {"code": "lv", "name_th": "ลัตเวีย", "name_en": "Latvian", "flag": "🇱🇻"},
    "et": {"code": "et", "name_th": "เอสโตเนีย", "name_en": "Estonian", "flag": "🇪🇪"},
    "af": {"code": "af", "name_th": "แอฟริคานส์", "name_en": "Afrikaans", "flag": "🇿🇦"},
    "sq": {"code": "sq", "name_th": "แอลเบเนีย", "name_en": "Albanian", "flag": "🇦🇱"},
    "am": {"code": "am", "name_th": "อัมฮาริก", "name_en": "Amharic", "flag": "🇪🇹"},
    "az": {"code": "az", "name_th": "อาเซอร์ไบจาน", "name_en": "Azerbaijani", "flag": "🇦🇿"},
    "eu": {"code": "eu", "name_th": "บาสก์", "name_en": "Basque", "flag": "🇪🇸"},
    "be": {"code": "be", "name_th": "เบลารุส", "name_en": "Belarusian", "flag": "🇧🇾"},
    "bs": {"code": "bs", "name_th": "บอสเนีย", "name_en": "Bosnian", "flag": "🇧🇦"},
    "ca": {"code": "ca", "name_th": "คาตาลัน", "name_en": "Catalan", "flag": "🇪🇸"},
    "ceb": {"code": "ceb", "name_th": "เซบูอาโน", "name_en": "Cebuano", "flag": "🇵🇭"},
    "co": {"code": "co", "name_th": "คอร์ซิกา", "name_en": "Corsican", "flag": "🇫🇷"},
    "cy": {"code": "cy", "name_th": "เวลส์", "name_en": "Welsh", "flag": "🏴󠁧󠁢󠁷󠁬󠁳󠁿"},
    "eo": {"code": "eo", "name_th": "เอสเปรันโต", "name_en": "Esperanto", "flag": "🌐"},
    "gl": {"code": "gl", "name_th": "กาลิเซีย", "name_en": "Galician", "flag": "🇪🇸"},
    "ka": {"code": "ka", "name_th": "จอร์เจีย", "name_en": "Georgian", "flag": "🇬🇪"},
    "gu": {"code": "gu", "name_th": "คุชราต", "name_en": "Gujarati", "flag": "🇮🇳"},
    "ht": {"code": "ht", "name_th": "เฮติครีโอล", "name_en": "Haitian Creole", "flag": "🇭🇹"},
    "ha": {"code": "ha", "name_th": "เฮาซา", "name_en": "Hausa", "flag": "🇳🇬"},
    "haw": {"code": "haw", "name_th": "ฮาวาย", "name_en": "Hawaiian", "flag": "🌺"},
    "is": {"code": "is", "name_th": "ไอซ์แลนด์", "name_en": "Icelandic", "flag": "🇮🇸"},
    "ig": {"code": "ig", "name_th": "อิกโบ", "name_en": "Igbo", "flag": "🇳🇬"},
    "ga": {"code": "ga", "name_th": "ไอริช", "name_en": "Irish", "flag": "🇮🇪"},
    "jv": {"code": "jv", "name_th": "ชวา", "name_en": "Javanese", "flag": "🇮🇩"},
    "kn": {"code": "kn", "name_th": "กันนาดา", "name_en": "Kannada", "flag": "🇮🇳"},
    "kk": {"code": "kk", "name_th": "คาซัค", "name_en": "Kazakh", "flag": "🇰🇿"},
    "rw": {"code": "rw", "name_th": "คินยารวันดา", "name_en": "Kinyarwanda", "flag": "🇷🇼"},
    "ku": {"code": "ku", "name_th": "เคิร์ด", "name_en": "Kurdish", "flag": "🇹🇷"},
    "ky": {"code": "ky", "name_th": "คีร์กีซ", "name_en": "Kyrgyz", "flag": "🇰🇬"},
    "la": {"code": "la", "name_th": "ละติน", "name_en": "Latin", "flag": "🏛️"},
    "lb": {"code": "lb", "name_th": "ลักเซมเบิร์ก", "name_en": "Luxembourgish", "flag": "🇱🇺"},
    "mk": {"code": "mk", "name_th": "มาซิโดเนีย", "name_en": "Macedonian", "flag": "🇲🇰"},
    "mg": {"code": "mg", "name_th": "มาลากาซี", "name_en": "Malagasy", "flag": "🇲🇬"},
    "ml": {"code": "ml", "name_th": "มาลายาลัม", "name_en": "Malayalam", "flag": "🇮🇳"},
    "mt": {"code": "mt", "name_th": "มอลตา", "name_en": "Maltese", "flag": "🇲🇹"},
    "mi": {"code": "mi", "name_th": "เมารี", "name_en": "Maori", "flag": "🇳🇿"},
    "mr": {"code": "mr", "name_th": "มราฐี", "name_en": "Marathi", "flag": "🇮🇳"},
    "mn": {"code": "mn", "name_th": "มองโกเลีย", "name_en": "Mongolian", "flag": "🇲🇳"},
    "ne": {"code": "ne", "name_th": "เนปาล", "name_en": "Nepali", "flag": "🇳🇵"},
    "ps": {"code": "ps", "name_th": "พัชโต", "name_en": "Pashto", "flag": "🇦🇫"},
    "pa": {"code": "pa", "name_th": "ปัญจาบ", "name_en": "Punjabi", "flag": "🇮🇳"},
    "sm": {"code": "sm", "name_th": "ซามัว", "name_en": "Samoan", "flag": "🇼🇸"},
    "gd": {"code": "gd", "name_th": "สกอตส์เกลิก", "name_en": "Scots Gaelic", "flag": "🏴󠁧󠁢󠁳󠁣󠁴󠁿"},
    "st": {"code": "st", "name_th": "เซโซโท", "name_en": "Sesotho", "flag": "🇱🇸"},
    "sn": {"code": "sn", "name_th": "โชนา", "name_en": "Shona", "flag": "🇿🇼"},
    "sd": {"code": "sd", "name_th": "สินธี", "name_en": "Sindhi", "flag": "🇵🇰"},
    "si": {"code": "si", "name_th": "สิงหล", "name_en": "Sinhala", "flag": "🇱🇰"},
    "so": {"code": "so", "name_th": "โซมาลี", "name_en": "Somali", "flag": "🇸🇴"},
    "su": {"code": "su", "name_th": "ซุนดา", "name_en": "Sundanese", "flag": "🇮🇩"},
    "sw": {"code": "sw", "name_th": "สวาฮีลี", "name_en": "Swahili", "flag": "🇰🇪"},
    "tg": {"code": "tg", "name_th": "ทาจิก", "name_en": "Tajik", "flag": "🇹🇯"},
    "tt": {"code": "tt", "name_th": "ตาตาร์", "name_en": "Tatar", "flag": "🇷🇺"},
    "te": {"code": "te", "name_th": "เตลูกู", "name_en": "Telugu", "flag": "🇮🇳"},
    "ug": {"code": "ug", "name_th": "อุยกูร์", "name_en": "Uyghur", "flag": "🇨🇳"},
    "uz": {"code": "uz", "name_th": "อุซเบก", "name_en": "Uzbek", "flag": "🇺🇿"},
    "xh": {"code": "xh", "name_th": "โซซา", "name_en": "Xhosa", "flag": "🇿🇦"},
    "yi": {"code": "yi", "name_th": "ยิดดิช", "name_en": "Yiddish", "flag": "✡️"},
    "yo": {"code": "yo", "name_th": "โยรูบา", "name_en": "Yoruba", "flag": "🇳🇬"},
    "zu": {"code": "zu", "name_th": "ซูลู", "name_en": "Zulu", "flag": "🇿🇦"}
}

# Backward compatibility map
LANGUAGE_NAMES = {
    "auto_swap": "สลับอัตโนมัติ (ไทย ↔ อังกฤษ)",
    **{k: f"{v['flag']} {v['name_th']} ({v['name_en']})" for k, v in LANGUAGES_DB.items()}
}

POPULAR_LANG_CODES = ["th", "en", "ja", "zh-CN", "ko", "de", "fr", "es", "ru", "vi"]

# Supported Translation Engine Metadata
TRANSLATION_ENGINES = {
    "google_gtx": {
        "id": "google_gtx",
        "name": "Google Translate",
        "badge": "ฟรี • ไม่ต้องใช้ Key",
        "needs_key": False,
        "desc": "เอนจินมาตรฐานของ Google แปลรวดเร็ว แม่นยำ และฟรีตลอดชีพ"
    },
    "mymemory": {
        "id": "mymemory",
        "name": "MyMemory Translation",
        "badge": "ฟรี • Crowdsourced",
        "needs_key": False,
        "desc": "ฐานข้อมูลการแปลที่ใหญ่ที่สุดในโลก ใช้ฟรีโดยไม่ต้องลงทะเบียน"
    },
    "deepl": {
        "id": "deepl",
        "name": "DeepL API",
        "badge": "พรีเมียม • ต้องใช้ API Key",
        "needs_key": True,
        "desc": "คุณภาพการแปลเป็นภาษาพูดระดับแนวหน้าของโลก (รองรับ DeepL Free/Pro Key)"
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini AI",
        "badge": "AI Model • Google Studio Key",
        "needs_key": True,
        "desc": "แปลโดยโมเดล AI (Gemini 1.5 Flash / 2.0) สละสลวยตามบริบท"
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI / Groq / Local LLM",
        "badge": "AI Model • API Key",
        "needs_key": True,
        "desc": "แปลผ่านโมเดล GPT-4o-mini, Llama 3 หรือต่อ API ที่เข้ากันได้"
    }
}


def search_languages(query: str, limit: int = 50) -> list[dict]:
    """Search languages by Thai name, English name, or ISO code."""
    q = query.strip().lower()
    if not q:
        # Return popular first, then rest
        popular = [LANGUAGES_DB[code] for code in POPULAR_LANG_CODES if code in LANGUAGES_DB]
        rest = [v for k, v in LANGUAGES_DB.items() if k not in POPULAR_LANG_CODES]
        return (popular + rest)[:limit]

    results = []
    for code, info in LANGUAGES_DB.items():
        if (q in code.lower() or
            q in info["name_th"].lower() or
            q in info["name_en"].lower()):
            results.append(info)
            if len(results) >= limit:
                break
    return results


def get_language_display(code: str) -> str:
    """Format language code as readable text with flag."""
    if code in LANGUAGES_DB:
        info = LANGUAGES_DB[code]
        return f"{info['flag']} {info['name_th']} ({info['name_en']})"
    return code


# Script / Character Regex Detectors
RE_THAI = re.compile(r'[\u0e00-\u0e7f]')
RE_JAPANESE = re.compile(r'[\u3040-\u30ff\u31f0-\u31ff]')  # Hiragana & Katakana
RE_CHINESE = re.compile(r'[\u4e00-\u9fff]')
RE_KOREAN = re.compile(r'[\uac00-\ud7af\u1100-\u11ff]')
RE_ARABIC = re.compile(r'[\u0600-\u06ff]')
RE_CYRILLIC = re.compile(r'[\u0400-\u04ff]')
RE_LATIN = re.compile(r'[a-zA-Z]')


def contains_thai(text: str) -> bool:
    """Check if the text contains Thai characters."""
    return bool(RE_THAI.search(text))


def match_language_script(text: str, lang_code: str) -> bool:
    """Check if text contains characters characteristic of a specific language."""
    base_code = lang_code.split("-")[0].lower()
    if base_code == "th":
        return bool(RE_THAI.search(text))
    elif base_code == "ja":
        return bool(RE_JAPANESE.search(text)) or (bool(RE_CHINESE.search(text)) and bool(RE_JAPANESE.search(text)))
    elif base_code == "zh":
        # Chinese has Hanzi without Japanese kana
        return bool(RE_CHINESE.search(text)) and not bool(RE_JAPANESE.search(text))
    elif base_code == "ko":
        return bool(RE_KOREAN.search(text))
    elif base_code in ("ar", "fa", "ur"):
        return bool(RE_ARABIC.search(text))
    elif base_code in ("ru", "uk", "bg", "be", "sr", "mk"):
        return bool(RE_CYRILLIC.search(text))
    return False


def detect_languages(text: str, target_lang_setting: str = "auto_swap") -> tuple[str, str]:
    """Backward-compatible wrapper for legacy detect_languages calls."""
    if target_lang_setting == "auto_swap":
        return detect_languages_universal(text, "th", "en", "pair")
    return detect_languages_universal(text, "th", target_lang_setting, "fixed")


def detect_languages_universal(text: str, lang_a: str = "th", lang_b: str = "en", swap_mode: str = "pair") -> tuple[str, str]:
    """
    Intelligently determines (source_lang, target_lang).
    If swap_mode is 'pair':
      - If text matches Lang A -> translate to Lang B
      - If text matches Lang B -> translate to Lang A
      - If ambiguous, auto-detects via query
    """
    trimmed = text.strip()
    if not trimmed:
        return "auto", lang_b

    if swap_mode == "fixed":
        # Fixed target language: from auto to lang_b
        return "auto", lang_b

    # Pair Auto-Swap mode:
    # 1. Check distinct non-Latin scripts
    a_matches = match_language_script(trimmed, lang_a)
    b_matches = match_language_script(trimmed, lang_b)

    if a_matches and not b_matches:
        return lang_a, lang_b
    if b_matches and not a_matches:
        return lang_b, lang_a

    # 2. If Lang A is Thai and Lang B is English / Latin
    if lang_a == "th" and contains_thai(trimmed):
        return "th", lang_b
    elif lang_a == "th" and not contains_thai(trimmed):
        return lang_b, "th"

    # 3. If Lang B is Thai and Lang A is English / Latin
    if lang_b == "th" and contains_thai(trimmed):
        return "th", lang_a
    elif lang_b == "th" and not contains_thai(trimmed):
        return lang_a, "th"

    # 4. If both are non-Thai or both Latin scripts (e.g. en <-> es, de <-> fr):
    # Default source to auto, target to lang_b
    return "auto", lang_b


# =====================================================================
# Translation Engine Implementations
# =====================================================================

def translate_google_gtx(text: str, source_lang: str, target_lang: str) -> tuple[str, str, str]:
    """Google Translate GTX Web endpoint."""
    encoded_query = urllib.parse.quote(text)
    url = (
        f"https://translate.googleapis.com/translate_a/single?"
        f"client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded_query}"
    )
    data = fetch_json(url, timeout=8)

    translated_parts = []
    if data and isinstance(data, list) and len(data) > 0 and data[0]:
        for item in data[0]:
            if item and len(item) > 0 and item[0]:
                translated_parts.append(item[0])

    translated_result = "".join(translated_parts)
    detected_sl = data[2] if len(data) > 2 and isinstance(data[2], str) else source_lang
    return translated_result, detected_sl, target_lang


def translate_mymemory(text: str, source_lang: str, target_lang: str) -> tuple[str, str, str]:
    """MyMemory free crowdsourced translation API."""
    sl = "autodetect" if source_lang == "auto" else source_lang
    tl = target_lang
    encoded_query = urllib.parse.quote(text)
    url = f"https://api.mymemory.translated.net/get?q={encoded_query}&langpair={sl}|{tl}"
    data = fetch_json(url, timeout=8)
    res_data = data.get("responseData", {})
    translated_result = res_data.get("translatedText", "")
    if not translated_result:
        raise ValueError("MyMemory returned empty result")
    return translated_result, source_lang, target_lang


def translate_deepl(text: str, source_lang: str, target_lang: str, api_key: str, is_pro: bool = False) -> tuple[str, str, str]:
    """DeepL REST API."""
    if not api_key:
        raise ValueError("ไม่ได้ระบุ DeepL API Key")

    domain = "api.deepl.com" if is_pro else "api-free.deepl.com"
    url = f"https://{domain}/v2/translate"

    payload = {
        "text": [text],
        "target_lang": target_lang.upper().split("-")[0]  # DeepL target codes are uppercase
    }
    if source_lang != "auto":
        payload["source_lang"] = source_lang.upper().split("-")[0]

    headers = {"Authorization": f"DeepL-Auth-Key {api_key.strip()}"}
    res = fetch_json(url, method="POST", payload=payload, headers=headers, timeout=10)

    translations = res.get("translations", [])
    if translations and "text" in translations[0]:
        translated = translations[0]["text"]
        detected = translations[0].get("detected_source_language", source_lang).lower()
        return translated, detected, target_lang
    raise ValueError("DeepL API response format error")


def translate_gemini(text: str, source_lang: str, target_lang: str, api_key: str, model: str = "gemini-1.5-flash") -> tuple[str, str, str]:
    """Google Gemini AI Studio API translation."""
    if not api_key:
        raise ValueError("ไม่ได้ระบุ Gemini API Key")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key.strip()}"

    target_name = LANGUAGES_DB.get(target_lang, {}).get("name_en", target_lang)
    prompt = (
        f"You are a professional and natural translator. "
        f"Translate the following text into {target_name}. "
        f"Output ONLY the translated text without any explanation, markdown formatting, or quotes:\n\n{text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
    }
    res = fetch_json(url, method="POST", payload=payload, timeout=12)

    candidates = res.get("candidates", [])
    if candidates and "content" in candidates[0]:
        parts = candidates[0]["content"].get("parts", [])
        if parts and "text" in parts[0]:
            return parts[0]["text"].strip(), source_lang, target_lang
    raise ValueError("Gemini API returned empty response")


def translate_openai(text: str, source_lang: str, target_lang: str, api_key: str, model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1") -> tuple[str, str, str]:
    """OpenAI / Groq / Compatible API translation."""
    if not api_key:
        raise ValueError("ไม่ได้ระบุ OpenAI API Key")

    cleaned_url = base_url.rstrip("/") + "/chat/completions"
    target_name = LANGUAGES_DB.get(target_lang, {}).get("name_en", target_lang)

    messages = [
        {"role": "system", "content": f"You are a direct translator. Translate the user input into {target_name}. Return ONLY the direct translation."},
        {"role": "user", "content": text}
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2
    }
    headers = {"Authorization": f"Bearer {api_key.strip()}"}
    res = fetch_json(cleaned_url, method="POST", payload=payload, headers=headers,
                     timeout=12)

    choices = res.get("choices", [])
    if choices and "message" in choices[0]:
        return choices[0]["message"].get("content", "").strip(), source_lang, target_lang
    raise ValueError("OpenAI API returned empty response")


# =====================================================================
# Main Unified Translator Router with Auto-Fallback
# =====================================================================

#: Engines that need no API key, in the order they are tried when the chosen
#: engine fails. Google first because it is the better translator; MyMemory
#: second because it survives the rate limit that usually takes Google down.
FREE_FALLBACKS = ("google_gtx", "mymemory")


class EngineUnavailable(Exception):
    """An engine cannot even be attempted - normally a missing API key."""


def _call_engine(engine: str, text: str, source_lang: str, target_lang: str,
                 cfg: dict) -> tuple[str, str, str]:
    """Run exactly one engine. Raises on any failure so the caller moves on."""
    keys = cfg.get("engine_api_keys", {}) or {}
    models = cfg.get("engine_models", {}) or {}

    if engine == "mymemory":
        return translate_mymemory(text, source_lang, target_lang)
    if engine == "deepl":
        key = keys.get("deepl", "")
        if not key:
            raise EngineUnavailable("DeepL has no API key")
        return translate_deepl(text, source_lang, target_lang, key)
    if engine == "gemini":
        key = keys.get("gemini", "")
        if not key:
            raise EngineUnavailable("Gemini has no API key")
        return translate_gemini(text, source_lang, target_lang, key,
                                models.get("gemini", "gemini-1.5-flash"))
    if engine == "openai":
        key = keys.get("openai", "")
        if not key:
            raise EngineUnavailable("OpenAI has no API key")
        return translate_openai(text, source_lang, target_lang, key,
                                models.get("openai", "gpt-4o-mini"),
                                cfg.get("openai_base_url",
                                        "https://api.openai.com/v1"))
    return translate_google_gtx(text, source_lang, target_lang)


def engine_chain(engine: str) -> list:
    """The chosen engine, then the free ones to fall back to.

    The old code fell back to Google unconditionally, which achieved nothing
    when Google *was* the chosen engine - and Google is the default. A
    rate-limited GTX endpoint simply failed twice and gave up, with MyMemory
    sitting right there unused.

    Fallbacks are restricted to the key-less engines on purpose: a failure
    should never quietly spend someone's DeepL or OpenAI credit, and an engine
    the user has no key for would only fail again anyway.
    """
    chain = [engine]
    chain.extend(name for name in FREE_FALLBACKS if name != engine)
    return chain


def translate_text(text: str, config: dict = None,
                   target_lang_setting: str = "auto_swap",
                   report: dict = None) -> tuple[str, str, str]:
    """
    Translate with the configured engine, falling back to the free ones.

    Returns ``(translated_text, source_lang, target_lang)``. On total failure
    the first element carries ``TRANSLATION_ERROR_PREFIX``; use
    ``is_translation_error`` rather than matching a message.

    Pass ``report`` as a dict to find out what actually happened::

        info = {}
        translate_text(text, config=cfg, report=info)
        info["engine"]     # the engine that produced the result
        info["fell_back"]  # True when that was not the configured one
        info["errors"]     # what each failed engine said
    """
    trimmed = text.strip()
    if not trimmed:
        return "", "auto", "auto"

    cfg = config or {}
    engine = cfg.get("translation_engine", "google_gtx")
    lang_a = cfg.get("swap_lang_a", "th")
    lang_b = cfg.get("swap_lang_b", "en")
    swap_mode = cfg.get("swap_mode", "pair")

    # If legacy call without config, use target_lang_setting
    if not config and target_lang_setting != "auto_swap":
        lang_b = target_lang_setting
        swap_mode = "fixed"

    source_lang, target_lang = detect_languages_universal(trimmed, lang_a, lang_b, swap_mode)

    def note(**fields):
        if report is not None:
            report.update(fields)

    # Serve repeats from the translation memory before touching the network.
    cached = _cache_get((_cache_signature(engine, cfg), source_lang, target_lang, trimmed))
    if cached is not None:
        note(engine=engine, fell_back=False, cached=True, errors=[])
        return cached

    # An engine that failed recently goes to the back of the queue rather than
    # being dropped, so a transient blip can never leave the user with nothing.
    chain = engine_chain(engine)
    ordered = ([name for name in chain if not _engine_in_cooldown(name)]
               + [name for name in chain if _engine_in_cooldown(name)])

    errors = []
    for candidate in ordered:
        if candidate != engine:
            hit = _cache_get((_cache_signature(candidate, cfg), source_lang,
                              target_lang, trimmed))
            if hit is not None:
                note(engine=candidate, fell_back=True, cached=True, errors=errors)
                return hit
        try:
            result = _call_engine(candidate, trimmed, source_lang, target_lang, cfg)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            _mark_engine_failed(candidate)
            print(f"[Translator] Engine '{candidate}' failed: {exc}")
            continue

        _mark_engine_working(candidate)
        # Cached under the engine that actually answered, so switching engines
        # later never serves a result the new engine did not produce.
        _cache_put((_cache_signature(candidate, cfg), source_lang, target_lang,
                    trimmed), result)
        if candidate != engine:
            print(f"[Translator] Fell back to '{candidate}'")
        note(engine=candidate, fell_back=candidate != engine, cached=False,
             errors=errors)
        return result

    note(engine="", fell_back=False, cached=False, errors=errors)
    reason = errors[0].split(": ", 1)[-1] if errors else "no engine available"
    return f"{TRANSLATION_ERROR_PREFIX} {reason}", source_lang, target_lang


def test_engine_connection(engine: str, config: dict) -> tuple[bool, str, int]:
    """
    Test translation engine connection with latency measurement.
    Returns: (success: bool, message: str, latency_ms: int)
    """
    t0 = time.time()
    try:
        sample_text = "Hello"
        if engine == "google_gtx":
            res, _, _ = translate_google_gtx(sample_text, "en", "th")
        elif engine == "mymemory":
            res, _, _ = translate_mymemory(sample_text, "en", "th")
        elif engine == "deepl":
            key = config.get("engine_api_keys", {}).get("deepl", "")
            res, _, _ = translate_deepl(sample_text, "en", "th", key)
        elif engine == "gemini":
            key = config.get("engine_api_keys", {}).get("gemini", "")
            model = config.get("engine_models", {}).get("gemini", "gemini-1.5-flash")
            res, _, _ = translate_gemini(sample_text, "en", "th", key, model)
        elif engine == "openai":
            key = config.get("engine_api_keys", {}).get("openai", "")
            model = config.get("engine_models", {}).get("openai", "gpt-4o-mini")
            base_url = config.get("openai_base_url", "https://api.openai.com/v1")
            res, _, _ = translate_openai(sample_text, "en", "th", key, model, base_url)
        else:
            return False, f"ไม่รู้จักเอนจิน {engine}", 0

        latency = int((time.time() - t0) * 1000)
        return True, f"เชื่อมต่อสำเร็จ! แปลคำว่า 'Hello' => '{res}'", latency
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return False, f"การเชื่อมต่อล้มเหลว: {str(e)}", latency
