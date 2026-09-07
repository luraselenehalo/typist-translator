"""
Internationalisation Module - Interface language for the application itself.

Not to be confused with translator_core, which translates the user's text. This
module translates the program's own UI.

Adding a language is one entry in UI_LANGUAGES plus one dict in CATALOG. Any
key a catalog is missing falls back to English and then to Thai, so a partial
catalog degrades gracefully instead of showing raw key names.

Usage:
    import i18n
    i18n.set_language("en")
    label.configure(text=i18n.t("nav.home"))
    label.configure(text=i18n.t("history.count", n=5))
"""

DEFAULT_LANGUAGE = "th"
FALLBACK_CHAIN = ("en", "th")

# Order here is the order shown in the Settings dropdown.
UI_LANGUAGES = {
    "th": {"code": "th", "native": "ไทย", "english": "Thai", "flag": "🇹🇭"},
    "en": {"code": "en", "native": "English", "english": "English", "flag": "🇬🇧"},
    "ja": {"code": "ja", "native": "日本語", "english": "Japanese", "flag": "🇯🇵"},
    "zh-CN": {"code": "zh-CN", "native": "简体中文", "english": "Chinese (Simplified)",
              "flag": "🇨🇳"},
}

# Which field of a LANGUAGES_DB entry reads most naturally per UI language.
# Only Thai has localised names for all 100+ languages, so everything else
# uses the English name rather than showing Thai to a non-Thai reader.
_LANGUAGE_NAME_FIELD = {"th": "name_th"}

_current = DEFAULT_LANGUAGE
_listeners = []


# =====================================================================
# Public API
# =====================================================================
def set_language(code: str) -> str:
    """Switch the interface language. Returns the code actually applied."""
    global _current
    _current = code if code in UI_LANGUAGES else DEFAULT_LANGUAGE
    return _current


def get_language() -> str:
    return _current


def available_languages():
    """[(code, native_name, flag)] in display order."""
    return [(c, m["native"], m["flag"]) for c, m in UI_LANGUAGES.items()]


def language_label(code: str) -> str:
    """'🇹🇭  ไทย' style label for the settings dropdown."""
    meta = UI_LANGUAGES.get(code)
    if not meta:
        return code
    if meta["native"] == meta["english"]:
        return f"{meta['flag']}  {meta['native']}"
    return f"{meta['flag']}  {meta['native']} ({meta['english']})"


def t(key: str, **fmt) -> str:
    """Look up a key in the active catalog, falling back through the chain."""
    for code in (_current,) + FALLBACK_CHAIN:
        catalog = CATALOG.get(code)
        if catalog and key in catalog:
            value = catalog[key]
            if fmt:
                try:
                    return value.format(**fmt)
                except (KeyError, IndexError, ValueError):
                    return value
            return value
    return key


def language_name(info: dict) -> str:
    """Display name for a LANGUAGES_DB entry, suited to the UI language.

    Popular languages carry a proper localised name in every catalog. The long
    tail falls back to the Thai name for a Thai UI and the English name
    otherwise, since only LANGUAGES_DB.name_th covers all 100+ entries.
    """
    code = info.get("code", "")
    if code:
        key = f"lang.{code}"
        localized = t(key)
        if localized != key:
            return localized
    field = _LANGUAGE_NAME_FIELD.get(_current, "name_en")
    return info.get(field) or info.get("name_en") or code


def on_change(callback):
    """Register a callback invoked after the language changes."""
    if callback not in _listeners:
        _listeners.append(callback)


def notify_change():
    for callback in list(_listeners):
        try:
            callback()
        except Exception:
            pass


def missing_keys(code: str):
    """Keys present in the Thai catalog but absent from `code` (test helper)."""
    reference = set(CATALOG[DEFAULT_LANGUAGE])
    return sorted(reference - set(CATALOG.get(code, {})))


# =====================================================================
# Catalogs
# =====================================================================
CATALOG = {}

CATALOG["th"] = {
    # -- shell ------------------------------------------------------
    "app.window_title": "Typist Translator • แปลภาษาขณะพิมพ์",
    "app.tagline": "แปลภาษาทันทีขณะพิมพ์ ทุกโปรแกรมบน Windows",
    "app.status.active": "พร้อมใช้งาน (Active)",
    "app.status.paused": "หยุดชั่วคราว (Paused)",
    "app.switch.hotkey": "เปิดคีย์ลัด",

    "nav.home": "หน้าหลัก",
    "nav.models": "เอนจินแปลภาษา",
    "nav.settings": "ตั้งค่า",
    "nav.guide": "วิธีใช้งาน",

    # -- home cards -------------------------------------------------
    "home.hotkey.title": "⌨️  คีย์ลัดหลัก",
    "home.hotkey.hint": "กดเมื่อพิมพ์เสร็จ เพื่อเลือก › แปล › แทนที่",
    "home.pair.title": "🌐  คู่ภาษาแปลด่วน",
    "home.pair.hint": "คลิกที่ภาษาเพื่อค้นหา • กด ↔ เพื่อสลับ",
    "home.engine.title": "🤖  โมเดลที่ใช้งาน",
    "home.engine.mode": "โหมด: {mode}",

    # -- sandbox ----------------------------------------------------
    "sandbox.samples": "ตัวอย่างด่วน",
    "sandbox.input": "📝  ต้นฉบับ",
    "sandbox.output": "✨  คำแปล",
    "sandbox.chars": "{n} ตัวอักษร",
    "sandbox.translate": "⚡ แปล",
    "sandbox.translating": "แปล{dots}",
    "sandbox.default_input": "สวัสดีครับ ยินดีที่ได้รู้จัก",
    "sandbox.default_output": "Hello, nice to meet you.",

    "action.copy": "📋 คัดลอก",
    "action.copied": "✓ คัดลอกแล้ว",

    "chip.greet": "👋 ทักทาย",
    "chip.work": "💼 งาน",
    "chip.meeting": "📅 ประชุม",
    "chip.thanks": "🙏 ขอบคุณ",
    "sample.greet": "สวัสดีครับ ยินดีที่ได้รู้จัก",
    "sample.work": "Please review the attached document.",
    "sample.meeting": "พรุ่งนี้สะดวกนัดประชุมกี่โมงครับ",
    "sample.thanks": "Thank you so much for your assistance!",

    # -- history ----------------------------------------------------
    "history.title": "📜  ประวัติการแปลล่าสุด",
    "history.count": "{n} รายการ",
    "history.found": "พบ {n} รายการ",
    "history.search": "🔍  ค้นหาในประวัติ...",
    "history.clear": "ล้างประวัติ",
    "history.empty": "ยังไม่มีประวัติการแปล\nข้อความที่แปลด้วยคีย์ลัดจะถูกบันทึกที่นี่อัตโนมัติ",

    # -- engines page -----------------------------------------------
    "models.head.title": "🤖  เลือกโมเดลและค่ายผู้ให้บริการแปลภาษา",
    "models.head.desc": "ใช้ Google Translate หรือ MyMemory ได้ฟรีทันที หรือเชื่อม API Key ของ DeepL, Gemini และ OpenAI เพื่อคุณภาพการแปลระดับสูงขึ้น",
    "models.section1.title": "1. เลือกผู้ให้บริการหลัก",
    "models.section1.sub": "เอนจินที่ใช้เมื่อกดคีย์ลัดและในกล่องทดลองแปล",
    "models.section2.title": "2. การตั้งค่าของเอนจินที่เลือก",
    "models.section2.sub": "ค่าที่กรอกจะถูกบันทึกอัตโนมัติทันที",
    "models.free_ready": "✓  เอนจินนี้ใช้งานได้ฟรีทันที ไม่ต้องตั้งค่า API Key",
    "models.test": "🔌  ทดสอบการเชื่อมต่อโมเดลนี้",
    "models.testing": "⏳ กำลังทดสอบการเชื่อมต่อ...",
    "models.test_ok": "✅ เชื่อมต่อสำเร็จ! ({ms} ms)",
    "models.test_fail": "❌ {msg}",
    "models.deepl.key": "DeepL API Key (Free หรือ Pro)",
    "models.deepl.placeholder": "ใส่ DeepL Authentication Key...",
    "models.gemini.key": "Google Gemini AI Studio API Key",
    "models.gemini.placeholder": "ใส่ Google AI Studio Key (AIzaSy...)",
    "models.gemini.model": "เลือกรุ่นโมเดล Gemini",
    "models.openai.key": "OpenAI / Groq API Key",
    "models.openai.model": "รุ่นโมเดล (Model)",
    "models.openai.base_url": "Custom Base URL (สำหรับ Groq หรือ Local LLM)",

    "engine.google_gtx.badge": "ฟรี • ไม่ต้องใช้ Key",
    "engine.google_gtx.desc": "เอนจินมาตรฐานของ Google แปลรวดเร็ว แม่นยำ และฟรีตลอดชีพ",
    "engine.mymemory.badge": "ฟรี • Crowdsourced",
    "engine.mymemory.desc": "ฐานข้อมูลการแปลที่ใหญ่ที่สุดในโลก ใช้ฟรีโดยไม่ต้องลงทะเบียน",
    "engine.deepl.badge": "พรีเมียม • ต้องใช้ API Key",
    "engine.deepl.desc": "คุณภาพการแปลเป็นภาษาพูดระดับแนวหน้าของโลก (รองรับ DeepL Free/Pro Key)",
    "engine.gemini.badge": "AI Model • Google Studio Key",
    "engine.gemini.desc": "แปลโดยโมเดล AI (Gemini 1.5 Flash / 2.0) สละสลวยตามบริบท",
    "engine.openai.badge": "AI Model • API Key",
    "engine.openai.desc": "แปลผ่านโมเดล GPT-4o-mini, Llama 3 หรือต่อ API ที่เข้ากันได้",

    # -- settings page ----------------------------------------------
    "settings.hotkey.title": "2. ปุ่มคีย์ลัด (Shortcut Hotkey)",
    "settings.hotkey.sub": "เลือกจากรายการ หรือพิมพ์เองในช่องด้านขวา",
    "settings.hotkey.placeholder": "เช่น ctrl+alt+t หรือ f8",
    "settings.hotkey.error": "⚠️ ไม่สามารถลงทะเบียนคีย์ลัดนี้ได้: {msg}",
    "settings.hotkey.custom": "กำหนดเอง (Custom)",
    "settings.hotkey.undo": "คีย์ลัดย้อนกลับ",
    "settings.hotkey.undo_placeholder": "เช่น ctrl+alt+z (เว้นว่าง = ปิด)",
    "settings.hotkey.undo_sub": "กดเพื่อคืนข้อความเดิมหลังแปลผิด ใช้ได้กับคำแปลล่าสุดภายใน 5 นาที "
                                "และจะไม่เขียนทับถ้าข้อความในช่องเปลี่ยนไปแล้ว",
    "settings.hotkey.undo_error": "⚠️ ใช้คีย์ลัดนี้ไม่ได้: {msg}",
    "settings.selection.title": "3. รูปแบบการเลือกข้อความ",
    "settings.selection.sub": "กำหนดว่าเมื่อกดคีย์ลัดแล้วโปรแกรมจะเลือกข้อความส่วนไหนไปแปล",
    "settings.prefs.title": "4. ตัวเลือกเพิ่มเติมและการแจ้งเตือน",
    "settings.prefs.toast": "แสดงป๊อปอัปลอย (Floating Toast HUD) พร้อมคำแปลเมื่อกดคีย์ลัด",
    "settings.prefs.overlay": "แสดงแอนิเมชัน “กำลังแปล…” ที่ข้อความ ลอยเหนือทุกหน้าต่าง",
    "settings.prefs.sound": "เล่นเสียงแจ้งเตือนสั้นๆ เมื่อแปลและวางข้อความเสร็จ",
    "settings.prefs.restore_clipboard": "คืนสิ่งที่คัดลอกไว้เดิมหลังแปลเสร็จ (ไม่ให้คำแปลไปทับของที่ก๊อปไว้)",
    "settings.output.title": "6. วิธีใส่คำแปลกลับเข้าไป",
    "settings.output.sub": "ถ้าใช้ในเกมแล้วคำแปลไม่ขึ้น ให้เปลี่ยนเป็นแบบพิมพ์ทีละตัว",
    "settings.output.paste": "วางด้วย Ctrl+V — เร็ว ใช้ได้กับโปรแกรมทั่วไป",
    "settings.output.type": "พิมพ์ทีละตัวอักษร — ช้ากว่า แต่เข้าถึงช่องแชทในเกมได้",
    "settings.prefs.tray": "ย่อลงถาดระบบ (System Tray) เมื่อกดปุ่มปิด (X) เพื่อให้คีย์ลัดทำงานต่อ",
    "settings.prefs.start_min": "เริ่มโปรแกรมแบบย่อลง System Tray ทันที (Start Minimized)",
    "settings.theme.title": "5. ธีมหน้าต่าง (Theme)",
    "settings.language.title": "1. ภาษาของโปรแกรม (Interface Language)",
    "settings.language.sub": "เปลี่ยนภาษาของหน้าต่างโปรแกรมทันที ไม่เกี่ยวกับคู่ภาษาที่ใช้แปลข้อความ",
    "settings.save": "💾  บันทึกการตั้งค่า",
    "settings.reset": "คืนค่าเริ่มต้น",
    "settings.saved": "✅ บันทึกการตั้งค่าเรียบร้อยแล้ว",

    "theme.System": "ตามระบบ (System)",
    "theme.Dark": "มืด (Dark)",
    "theme.Light": "สว่าง (Light)",

    # -- selection modes --------------------------------------------
    "selection.all.badge": "📦 ทั้งหมดในกล่อง (Ctrl+A)",
    "selection.all.desc": "แนะนำสำหรับแชท (LINE, Discord, Messenger, Slack)",
    "selection.smart.badge": "🧠 โหมดอัจฉริยะ (Smart)",
    "selection.smart.desc": "ถ้าคลุมดำใช้ตามที่คลุม / ถ้าไม่คลุมจะเลือกทั้งหมดให้",
    "selection.line.badge": "📝 ต้นบรรทัด (Shift+Home)",
    "selection.line.desc": "สำหรับเอกสารยาวๆ (Microsoft Word, Notepad)",
    "selection.selection.badge": "✂️ เฉพาะที่คลุมดำ",
    "selection.selection.desc": "แปลเฉพาะข้อความที่คุณใช้เมาส์คลุมดำไว้เท่านั้น",

    # -- guide page --------------------------------------------------
    "guide.hero.title": "📖  คู่มือการใช้งาน Typist Translator",
    "guide.hero.sub": "พิมพ์ภาษาหนึ่ง กดคีย์ลัด แล้วข้อความจะถูกแทนที่ด้วยคำแปลทันที ในทุกโปรแกรมบน Windows",
    "guide.step1.title": "เปิดโปรแกรมทิ้งไว้",
    "guide.step1.desc": "กดปุ่มปิด (X) แล้วโปรแกรมจะย่อลง System Tray มุมขวาล่าง คีย์ลัดยังทำงานต่อเนื่อง",
    "guide.step2.title": "พิมพ์ข้อความในโปรแกรมใดก็ได้",
    "guide.step2.desc": "LINE, Discord, Messenger, Slack, Microsoft Word, Notepad, Chrome, Edge และอื่นๆ",
    "guide.step3.title": "กดคีย์ลัด",
    "guide.step3.desc": "โปรแกรมจะเลือกข้อความ แปล และวางคำแปลแทนที่ให้ทันที พร้อมป๊อปอัป Toast แจ้งผล",
    "guide.step4.title": "แปลผิด? กด Ctrl + Alt + Z",
    "guide.step4.desc": "คืนข้อความเดิมกลับมาทันที ใช้ได้กับคำแปลล่าสุดภายใน 5 นาที และถ้าคุณพิมพ์อะไรเพิ่มไปแล้ว โปรแกรมจะไม่เขียนทับให้ เปลี่ยนปุ่มได้ที่ ตั้งค่า › หัวข้อ 2",
    "guide.pairs.title": "🌐  ระบบคู่ภาษาอิสระ (Custom Auto-Swap)",
    "guide.pairs.note": "ค้นหาได้มากกว่า 100+ ภาษาทั่วโลก ด้วยชื่อภาษาไทย ภาษาอังกฤษ หรือรหัสย่อ ISO",
    "guide.pair.desc": "พิมพ์{a}ได้{b} • พิมพ์{b}ได้{a}",
    "guide.engines.title": "🤖  โมเดลแปลภาษาที่รองรับ",

    "lang.th": "ไทย",
    "lang.en": "อังกฤษ",
    "lang.ja": "ญี่ปุ่น",
    "lang.zh-CN": "จีน (ตัวย่อ)",
    "lang.zh-TW": "จีน (ตัวเต็ม)",
    "lang.ko": "เกาหลี",
    "lang.de": "เยอรมัน",
    "lang.fr": "ฝรั่งเศส",
    "lang.es": "สเปน",
    "lang.ru": "รัสเซีย",
    "lang.vi": "เวียดนาม",
    "lang.zh": "จีน",

    # -- language picker ---------------------------------------------
    "picker.title_a": "เลือกภาษาหลัก (A)",
    "picker.title_b": "เลือกภาษารอง (B)",
    "picker.sub": "ค้นหาจาก 100+ ภาษาทั่วโลก ด้วยชื่อภาษาไทย ภาษาอังกฤษ หรือรหัส ISO",
    "picker.search": "🔍  ค้นหาภาษา (เช่น ไทย, อังกฤษ, ญี่ปุ่น, zh, de, ko)...",
    "picker.popular": "ภาษายอดนิยม",
    "picker.select": "เลือก",
    "picker.selected": "เลือก ✓",
    "picker.empty": "ไม่พบภาษาที่ตรงกับ “{query}”\nลองพิมพ์ชื่อภาษาหรือรหัสย่อ ISO ใหม่อีกครั้ง",

    # -- toast --------------------------------------------------------
    # -- progress overlay (floats over every window while translating) --
    # -- about tab ----------------------------------------------------
    # -- self-update ---------------------------------------------------
    "update.available.title": "มีเวอร์ชันใหม่ {version} แล้ว",
    "update.available.body": "กดอัปเดตเพื่อดาวน์โหลดและติดตั้งให้อัตโนมัติ โปรแกรมจะเปิดขึ้นใหม่เอง",
    "update.action.install": "อัปเดตเลย",
    "update.action.later": "ไว้ทีหลัง",
    "update.action.skip": "ข้ามรุ่นนี้",
    "update.action.retry": "ลองใหม่",
    "update.action.page": "เปิดหน้าดาวน์โหลด",
    "update.downloading": "กำลังดาวน์โหลด… {done} / {total} MB",
    "update.installing.title": "กำลังติดตั้ง",
    "update.installing.body": "โปรแกรมจะปิดแล้วเปิดขึ้นมาใหม่เองในอีกสักครู่",
    "update.failed.title": "อัปเดตไม่สำเร็จ",
    "update.failed.body": "ลองใหม่อีกครั้ง หรือดาวน์โหลดเองจากหน้า Releases",
    "update.check.now": "ตรวจหาเวอร์ชันใหม่",
    "update.check.checking": "กำลังตรวจสอบ…",
    "update.check.current": "ใช้เวอร์ชันล่าสุดอยู่แล้ว ({version})",
    "update.check.found": "พบเวอร์ชัน {version}",
    "update.portable_only": "ตัวนี้ไม่ได้ติดตั้งผ่านตัวติดตั้ง จึงอัปเดตเองไม่ได้ — ดาวน์โหลดรุ่นใหม่ได้จากหน้า Releases",
    "settings.prefs.autoupdate": "ตรวจหาเวอร์ชันใหม่อัตโนมัติ แล้วแจ้งเตือนที่มุมขวาล่าง",
    "whatsnew.title": "อัปเดตเป็นเวอร์ชัน {version} แล้ว",
    "whatsnew.sub": "นี่คือสิ่งที่เปลี่ยนไป",
    "whatsnew.close": "เริ่มใช้งาน",
    "whatsnew.full": "ดูรายละเอียดทั้งหมดบน GitHub",

    "nav.about": "เกี่ยวกับ",
    "about.hero.title": "{app}",
    "about.hero.sub": "แปลภาษาขณะพิมพ์ ในทุกโปรแกรมบน Windows โดยไม่ต้องสลับหน้าต่าง",
    "about.hero.by": "สร้างโดย {author}",
    "about.alias": "{author} และ {alias} คือคนเดียวกัน",
    "about.what.title": "โปรแกรมนี้ทำอะไร",
    "about.what.body": "พิมพ์ข้อความในโปรแกรมไหนก็ได้ — แชท เอกสาร เบราว์เซอร์ — แล้วกดคีย์ลัดหนึ่งครั้ง โปรแกรมจะเลือกข้อความ ส่งไปแปล แล้ววางคำแปลทับลงไปในที่เดิม คุณไม่ต้องคัดลอก ไม่ต้องเปิดแท็บใหม่ ไม่ต้องละมือจากคีย์บอร์ด",
    "about.how.title": "ทำงานอย่างไร",
    "about.how.body": "คีย์ลัด คลิปบอร์ด และไอคอนถาดระบบเป็น Python ที่คุยกับ Windows โดยตรง ส่วนหน้าตาเป็น React เรนเดอร์ด้วย WebView2 ที่ติดมากับ Windows อยู่แล้ว จึงไม่ต้องแบก Chromium มาทั้งก้อน คำแปลที่เคยแปลแล้วถูกจำไว้ในหน่วยความจำ กดซ้ำจึงตอบทันที",
    "about.privacy.title": "ข้อมูลของคุณ",
    "about.privacy.body": "ข้อความที่แปลถูกส่งไปยังเอนจินที่คุณเลือกเท่านั้น ประวัติการแปลและ API Key เก็บไว้ในเครื่องคุณ (config.json) ไม่มีการส่งไปที่อื่น และไม่มีระบบเก็บสถิติการใช้งาน",
    "about.tech.title": "สร้างด้วย",
    "about.links.title": "ช่องทางติดตามและติดต่อ",
    "about.links.empty": "ยังไม่ได้ใส่ลิงก์ — แก้ไขได้ที่ไฟล์ {file} แล้วเปิดโปรแกรมใหม่ ไม่ต้องสร้าง UI ใหม่",
    "about.link.github": "ซอร์สโค้ดบน GitHub",
    "about.link.github.sub": "อ่านโค้ด กด Star หรือ Fork ไปแก้ต่อได้",
    "about.link.issues": "แจ้งปัญหา / เสนอฟีเจอร์",
    "about.link.issues.sub": "เจอบั๊กหรืออยากได้อะไรเพิ่ม บอกได้ที่นี่",
    "about.link.releases": "ดาวน์โหลดเวอร์ชันล่าสุด",
    "about.link.releases.sub": "รายการเวอร์ชันและสิ่งที่เปลี่ยนแปลง",
    "about.link.facebook": "ติดตามบน Facebook",
    "about.link.facebook.sub": "ข่าวสารและอัปเดตของโปรแกรม",
    "about.link.email": "ส่งอีเมลหาผู้พัฒนา",
    "about.link.email.sub": "เรื่องที่อยากคุยเป็นการส่วนตัว",
    "about.open": "เปิด",
    "about.license.title": "สัญญาอนุญาต",
    "about.license.body": "เผยแพร่ภายใต้สัญญาอนุญาต {license} ใช้ แก้ไข และแจกจ่ายต่อได้ ขอเพียงคงเครดิตของผู้สร้างไว้",
    "about.version": "เวอร์ชัน {version}",

    # -- progress overlay (floats over every window while translating) --
    "overlay.reading": "กำลังอ่านข้อความ…",
    "overlay.translating": "กำลังแปล…",
    "overlay.slow": "ยังแปลอยู่ รอสักครู่…",
    "overlay.pasting": "กำลังวางคำแปล…",
    "overlay.done": "แปลเสร็จแล้ว",
    "overlay.failed": "แปลไม่สำเร็จ",
    "overlay.no_text": "ไม่พบข้อความให้แปล",
    "overlay.no_text_hint": "คลิกที่ช่องพิมพ์ก่อน แล้วกดคีย์ลัดอีกครั้ง",
    "overlay.blocked": "Windows ไม่ยอมให้พิมพ์",
    "overlay.blocked_hint": "โปรแกรมปลายทางรันด้วยสิทธิ์สูงกว่า ลองเปิด Typist แบบ Run as administrator",
    "overlay.done_fallback": "แปลเสร็จแล้ว (ใช้ {engine} แทน)",
    "overlay.undoing": "กำลังย้อนกลับ…",
    "overlay.undone": "คืนข้อความเดิมแล้ว",
    "overlay.no_undo": "ไม่มีอะไรให้ย้อนกลับ",
    "overlay.no_undo_hint": "ย้อนได้เฉพาะคำแปลล่าสุด ภายใน 5 นาที",
    "overlay.undo_changed": "ย้อนกลับไม่ได้",
    "overlay.undo_changed_hint": "ข้อความในช่องเปลี่ยนไปแล้ว จึงไม่เขียนทับให้",

    "toast.success": "แปลและแทนที่สำเร็จ",
    "toast.original": "เดิม: {text}",

    # -- tray ---------------------------------------------------------
    "tray.open": "เปิดโปรแกรม",
    "tray.enabled": "เปิดใช้งานคีย์ลัด",
    "tray.exit": "ออกจากโปรแกรม",
    "tray.tooltip": "Typist Translator — แปลภาษาขณะพิมพ์",

    # -- errors -------------------------------------------------------
    "error.translate": "แปลข้อความไม่สำเร็จ: {msg}",
}

CATALOG["en"] = {
    "app.window_title": "Typist Translator • Translate As You Type",
    "app.tagline": "Instant translation while you type, in any Windows app",
    "app.status.active": "Ready (Active)",
    "app.status.paused": "Paused",
    "app.switch.hotkey": "Hotkey on",

    "nav.home": "Home",
    "nav.models": "Engines",
    "nav.settings": "Settings",
    "nav.guide": "Guide",

    "home.hotkey.title": "⌨️  Main hotkey",
    "home.hotkey.hint": "Press it when you finish typing: select › translate › replace",
    "home.pair.title": "🌐  Quick language pair",
    "home.pair.hint": "Click a language to search • press ↔ to swap",
    "home.engine.title": "🤖  Active engine",
    "home.engine.mode": "Mode: {mode}",

    "sandbox.samples": "Quick samples",
    "sandbox.input": "📝  Source",
    "sandbox.output": "✨  Translation",
    "sandbox.chars": "{n} characters",
    "sandbox.translate": "⚡ Translate",
    "sandbox.translating": "Translating{dots}",
    "sandbox.default_input": "Hello, nice to meet you.",
    "sandbox.default_output": "สวัสดีครับ ยินดีที่ได้รู้จัก",

    "action.copy": "📋 Copy",
    "action.copied": "✓ Copied",

    "chip.greet": "👋 Greeting",
    "chip.work": "💼 Work",
    "chip.meeting": "📅 Meeting",
    "chip.thanks": "🙏 Thanks",
    "sample.greet": "Hello, nice to meet you.",
    "sample.work": "Please review the attached document.",
    "sample.meeting": "What time works for a meeting tomorrow?",
    "sample.thanks": "Thank you so much for your assistance!",

    "history.title": "📜  Recent translations",
    "history.count": "{n} items",
    "history.found": "{n} matches",
    "history.search": "🔍  Search history...",
    "history.clear": "Clear history",
    "history.empty": "No translations yet\nAnything you translate with the hotkey is saved here automatically",

    "models.head.title": "🤖  Choose a translation provider",
    "models.head.desc": "Google Translate and MyMemory are free with no setup. Connect a DeepL, Gemini or OpenAI API key for higher quality translations.",
    "models.section1.title": "1. Primary provider",
    "models.section1.sub": "Used by the hotkey and by the sandbox below",
    "models.section2.title": "2. Settings for the selected engine",
    "models.section2.sub": "Anything you enter is saved automatically",
    "models.free_ready": "✓  This engine is free and ready to use — no API key needed",
    "models.test": "🔌  Test this connection",
    "models.testing": "⏳ Testing connection...",
    "models.test_ok": "✅ Connected! ({ms} ms)",
    "models.test_fail": "❌ {msg}",
    "models.deepl.key": "DeepL API key (Free or Pro)",
    "models.deepl.placeholder": "Enter your DeepL authentication key...",
    "models.gemini.key": "Google Gemini AI Studio API key",
    "models.gemini.placeholder": "Enter your Google AI Studio key (AIzaSy...)",
    "models.gemini.model": "Gemini model",
    "models.openai.key": "OpenAI / Groq API key",
    "models.openai.model": "Model",
    "models.openai.base_url": "Custom base URL (for Groq or a local LLM)",

    "engine.google_gtx.badge": "Free • No key needed",
    "engine.google_gtx.desc": "Google's standard engine — fast, accurate and free forever",
    "engine.mymemory.badge": "Free • Crowdsourced",
    "engine.mymemory.desc": "The world's largest translation memory, free without registration",
    "engine.deepl.badge": "Premium • API key required",
    "engine.deepl.desc": "World-class natural-sounding translation (supports DeepL Free and Pro keys)",
    "engine.gemini.badge": "AI model • Google Studio key",
    "engine.gemini.desc": "Translated by an AI model (Gemini 1.5 Flash / 2.0) that follows context",
    "engine.openai.badge": "AI model • API key",
    "engine.openai.desc": "Use GPT-4o-mini, Llama 3, or any OpenAI-compatible endpoint",

    "settings.hotkey.title": "2. Shortcut hotkey",
    "settings.hotkey.sub": "Pick a preset, or type your own on the right",
    "settings.hotkey.placeholder": "e.g. ctrl+alt+t or f8",
    "settings.hotkey.error": "⚠️ Could not register that hotkey: {msg}",
    "settings.hotkey.custom": "Custom",
    "settings.hotkey.undo": "Undo hotkey",
    "settings.hotkey.undo_placeholder": "e.g. ctrl+alt+z (empty = off)",
    "settings.hotkey.undo_sub": "Puts the original text back after a bad translation. Works on the "
                                "last translation for 5 minutes, and refuses if the text has changed since.",
    "settings.hotkey.undo_error": "⚠️ Could not use that hotkey: {msg}",
    "settings.selection.title": "3. Text selection mode",
    "settings.selection.sub": "Decides which text the hotkey grabs to translate",
    "settings.prefs.title": "4. Notifications and preferences",
    "settings.prefs.toast": "Show a floating toast with the translation when the hotkey fires",
    "settings.prefs.overlay": "Show a “translating…” chip next to the text, above every window",
    "settings.prefs.sound": "Play a short sound once the translation is pasted",
    "settings.prefs.restore_clipboard": "Put back whatever you had copied, so a translation never eats your clipboard",
    "settings.output.title": "6. How the translation is written back",
    "settings.output.sub": "If nothing appears in a game, switch to typing the characters",
    "settings.output.paste": "Paste with Ctrl+V — fast, works in ordinary programs",
    "settings.output.type": "Type the characters — slower, but reaches game chat boxes",
    "settings.prefs.tray": "Minimise to the system tray on close (X) so the hotkey keeps working",
    "settings.prefs.start_min": "Start minimised to the system tray",
    "settings.theme.title": "5. Window theme",
    "settings.language.title": "1. Interface language",
    "settings.language.sub": "Changes the program's own language instantly — separate from the pair used to translate your text",
    "settings.save": "💾  Save settings",
    "settings.reset": "Reset to defaults",
    "settings.saved": "✅ Settings saved",

    "theme.System": "System",
    "theme.Dark": "Dark",
    "theme.Light": "Light",

    "selection.all.badge": "📦 Whole box (Ctrl+A)",
    "selection.all.desc": "Recommended for chat apps (LINE, Discord, Messenger, Slack)",
    "selection.smart.badge": "🧠 Smart mode",
    "selection.smart.desc": "Uses your selection if you made one, otherwise selects everything",
    "selection.line.badge": "📝 To line start (Shift+Home)",
    "selection.line.desc": "For long documents (Microsoft Word, Notepad)",
    "selection.selection.badge": "✂️ Selection only",
    "selection.selection.desc": "Translates only the text you highlighted with the mouse",

    "guide.hero.title": "📖  Typist Translator user guide",
    "guide.hero.sub": "Type in one language, press the hotkey, and the text is replaced by its translation — in any Windows app",
    "guide.step1.title": "Leave the program running",
    "guide.step1.desc": "Closing with X minimises it to the system tray, and the hotkey keeps working",
    "guide.step2.title": "Type in any application",
    "guide.step2.desc": "LINE, Discord, Messenger, Slack, Microsoft Word, Notepad, Chrome, Edge and more",
    "guide.step3.title": "Press the hotkey",
    "guide.step3.desc": "The text is selected, translated and pasted back in place, with a toast confirming the result",
    "guide.step4.title": "Bad translation? Press Ctrl + Alt + Z",
    "guide.step4.desc": "Puts your original text straight back. It works on the last translation for five minutes, and refuses if you have typed since, so it can never overwrite newer text. Change the key in Settings › section 2",
    "guide.pairs.title": "🌐  Free-form language pairing (Custom Auto-Swap)",
    "guide.pairs.note": "Search more than 100 languages by Thai name, English name, or ISO code",
    "guide.pair.desc": "Type {a}, get {b} • type {b}, get {a}",
    "guide.engines.title": "🤖  Supported translation engines",

    "lang.th": "Thai",
    "lang.en": "English",
    "lang.ja": "Japanese",
    "lang.zh-CN": "Chinese (Simplified)",
    "lang.zh-TW": "Chinese (Traditional)",
    "lang.ko": "Korean",
    "lang.de": "German",
    "lang.fr": "French",
    "lang.es": "Spanish",
    "lang.ru": "Russian",
    "lang.vi": "Vietnamese",
    "lang.zh": "Chinese",

    "picker.title_a": "Choose primary language (A)",
    "picker.title_b": "Choose secondary language (B)",
    "picker.sub": "Search 100+ world languages by Thai name, English name, or ISO code",
    "picker.search": "🔍  Search a language (e.g. Thai, English, Japanese, zh, de, ko)...",
    "picker.popular": "Popular languages",
    "picker.select": "Select",
    "picker.selected": "Selected ✓",
    "picker.empty": "No language matches “{query}”\nTry another name or an ISO code",

    "update.available.title": "Version {version} is available",
    "update.available.body": "Update now and it downloads, installs and reopens itself.",
    "update.action.install": "Update now",
    "update.action.later": "Later",
    "update.action.skip": "Skip this one",
    "update.action.retry": "Try again",
    "update.action.page": "Open the download page",
    "update.downloading": "Downloading… {done} / {total} MB",
    "update.installing.title": "Installing",
    "update.installing.body": "The app will close and reopen itself in a moment.",
    "update.failed.title": "The update failed",
    "update.failed.body": "Try again, or download it yourself from the Releases page.",
    "update.check.now": "Check for updates",
    "update.check.checking": "Checking…",
    "update.check.current": "You are on the newest version ({version})",
    "update.check.found": "Version {version} is available",
    "update.portable_only": "This copy was not installed by the installer, so it cannot update itself - download the new version from the Releases page.",
    "settings.prefs.autoupdate": "Check for updates automatically and tell me in the corner",
    "whatsnew.title": "Updated to version {version}",
    "whatsnew.sub": "Here is what changed",
    "whatsnew.close": "Get started",
    "whatsnew.full": "Read the full notes on GitHub",

    "nav.about": "About",
    "about.hero.title": "{app}",
    "about.hero.sub": "Translate as you type, in any Windows application, without leaving it",
    "about.hero.by": "Made by {author}",
    "about.alias": "{author} and {alias} are the same person",
    "about.what.title": "What it does",
    "about.what.body": "Type in any application - a chat box, a document, a browser - and press one hotkey. It selects your text, translates it, and pastes the result back over it. No copying, no extra tab, no taking your hands off the keyboard.",
    "about.how.title": "How it works",
    "about.how.body": "The hotkey, the clipboard and the tray icon are Python talking straight to Windows. The interface is React rendered by WebView2, which already ships with Windows, so there is no bundled Chromium to carry around. Anything translated once is remembered in memory, so pressing the hotkey again answers instantly.",
    "about.privacy.title": "Your data",
    "about.privacy.body": "Your text goes to the translation engine you picked, and nowhere else. History and API keys stay on your machine in config.json. There is no telemetry.",
    "about.tech.title": "Built with",
    "about.links.title": "Links and contact",
    "about.links.empty": "No links set yet - edit {file} and restart. The UI does not need rebuilding.",
    "about.link.github": "Source on GitHub",
    "about.link.github.sub": "Read the code, star it, or fork it",
    "about.link.issues": "Report a bug / request a feature",
    "about.link.issues.sub": "Anything broken or missing goes here",
    "about.link.releases": "Download the latest version",
    "about.link.releases.sub": "Every release and what changed in it",
    "about.link.facebook": "Follow on Facebook",
    "about.link.facebook.sub": "News and updates about the app",
    "about.link.email": "Email the developer",
    "about.link.email.sub": "For anything you would rather send privately",
    "about.open": "Open",
    "about.license.title": "License",
    "about.license.body": "Released under the {license} license. Use it, change it and share it - just keep the author credit.",
    "about.version": "Version {version}",

    "overlay.reading": "Reading your text…",
    "overlay.translating": "Translating…",
    "overlay.slow": "Still translating, hang on…",
    "overlay.pasting": "Pasting the translation…",
    "overlay.done": "Translated",
    "overlay.failed": "Translation failed",
    "overlay.no_text": "No text to translate",
    "overlay.no_text_hint": "Click inside the text box, then press the hotkey again",
    "overlay.blocked": "Windows refused the keystroke",
    "overlay.blocked_hint": "That program runs with higher privileges — try starting Typist as administrator",
    "overlay.done_fallback": "Translated (used {engine} instead)",
    "overlay.undoing": "Putting it back…",
    "overlay.undone": "Original text restored",
    "overlay.no_undo": "Nothing to undo",
    "overlay.no_undo_hint": "Only the last translation can be undone, within 5 minutes",
    "overlay.undo_changed": "Cannot undo",
    "overlay.undo_changed_hint": "The text has changed since, so nothing was overwritten",

    "toast.success": "Translated and replaced",
    "toast.original": "Was: {text}",

    "tray.open": "Open",
    "tray.enabled": "Hotkey enabled",
    "tray.exit": "Exit",
    "tray.tooltip": "Typist Translator — translate as you type",

    "error.translate": "Translation failed: {msg}",
}

CATALOG["ja"] = {
    "app.window_title": "Typist Translator • 入力しながら翻訳",
    "app.tagline": "Windows のどのアプリでも、入力しながら即翻訳",
    "app.status.active": "使用可能 (Active)",
    "app.status.paused": "一時停止中 (Paused)",
    "app.switch.hotkey": "ホットキー有効",

    "nav.home": "ホーム",
    "nav.models": "翻訳エンジン",
    "nav.settings": "設定",
    "nav.guide": "使い方",

    "home.hotkey.title": "⌨️  メインホットキー",
    "home.hotkey.hint": "入力し終えたら押すだけ：選択 › 翻訳 › 置換",
    "home.pair.title": "🌐  クイック言語ペア",
    "home.pair.hint": "言語をクリックして検索 • ↔ で入れ替え",
    "home.engine.title": "🤖  使用中のエンジン",
    "home.engine.mode": "モード: {mode}",

    "sandbox.samples": "サンプル",
    "sandbox.input": "📝  原文",
    "sandbox.output": "✨  訳文",
    "sandbox.chars": "{n} 文字",
    "sandbox.translate": "⚡ 翻訳",
    "sandbox.translating": "翻訳中{dots}",
    "sandbox.default_input": "はじめまして、よろしくお願いします。",
    "sandbox.default_output": "Nice to meet you.",

    "action.copy": "📋 コピー",
    "action.copied": "✓ コピーしました",

    "chip.greet": "👋 あいさつ",
    "chip.work": "💼 仕事",
    "chip.meeting": "📅 会議",
    "chip.thanks": "🙏 お礼",
    "sample.greet": "はじめまして、よろしくお願いします。",
    "sample.work": "Please review the attached document.",
    "sample.meeting": "明日の会議は何時がご都合よろしいでしょうか。",
    "sample.thanks": "Thank you so much for your assistance!",

    "history.title": "📜  最近の翻訳履歴",
    "history.count": "{n} 件",
    "history.found": "{n} 件見つかりました",
    "history.search": "🔍  履歴を検索...",
    "history.clear": "履歴を消去",
    "history.empty": "翻訳履歴はまだありません\nホットキーで翻訳した内容がここに自動保存されます",

    "models.head.title": "🤖  翻訳プロバイダーを選ぶ",
    "models.head.desc": "Google 翻訳と MyMemory は設定不要で無料です。DeepL・Gemini・OpenAI の API キーを登録すると、さらに高品質な翻訳が使えます。",
    "models.section1.title": "1. メインのプロバイダー",
    "models.section1.sub": "ホットキーと下のテスト欄で使われます",
    "models.section2.title": "2. 選択中エンジンの設定",
    "models.section2.sub": "入力内容は自動で保存されます",
    "models.free_ready": "✓  このエンジンは API キー不要ですぐに使えます",
    "models.test": "🔌  接続をテスト",
    "models.testing": "⏳ 接続をテストしています...",
    "models.test_ok": "✅ 接続成功！({ms} ms)",
    "models.test_fail": "❌ {msg}",
    "models.deepl.key": "DeepL API キー (Free / Pro)",
    "models.deepl.placeholder": "DeepL の認証キーを入力...",
    "models.gemini.key": "Google Gemini AI Studio API キー",
    "models.gemini.placeholder": "Google AI Studio のキーを入力 (AIzaSy...)",
    "models.gemini.model": "Gemini のモデル",
    "models.openai.key": "OpenAI / Groq API キー",
    "models.openai.model": "モデル",
    "models.openai.base_url": "カスタム Base URL (Groq やローカル LLM 用)",

    "engine.google_gtx.badge": "無料 • キー不要",
    "engine.google_gtx.desc": "Google の標準エンジン。高速・高精度で、ずっと無料",
    "engine.mymemory.badge": "無料 • クラウドソース",
    "engine.mymemory.desc": "世界最大の翻訳メモリ。登録不要で無料で使えます",
    "engine.deepl.badge": "プレミアム • API キー必須",
    "engine.deepl.desc": "世界トップクラスの自然な翻訳 (DeepL Free / Pro キーに対応)",
    "engine.gemini.badge": "AI モデル • Google Studio キー",
    "engine.gemini.desc": "AI モデル (Gemini 1.5 Flash / 2.0) が文脈をふまえて翻訳します",
    "engine.openai.badge": "AI モデル • API キー",
    "engine.openai.desc": "GPT-4o-mini や Llama 3、OpenAI 互換エンドポイントを利用できます",

    "settings.hotkey.title": "2. ショートカットキー",
    "settings.hotkey.sub": "一覧から選ぶか、右の欄に直接入力してください",
    "settings.hotkey.placeholder": "例: ctrl+alt+t または f8",
    "settings.hotkey.error": "⚠️ このホットキーは登録できませんでした: {msg}",
    "settings.hotkey.custom": "カスタム",
    "settings.hotkey.undo": "元に戻すキー",
    "settings.hotkey.undo_placeholder": "例: ctrl+alt+z（空欄で無効）",
    "settings.hotkey.undo_sub": "誤訳のあとに元のテキストへ戻します。直前の翻訳に対して5分間有効で、"
                                "テキストが変更されている場合は上書きしません。",
    "settings.hotkey.undo_error": "⚠️ このキーは使用できません: {msg}",
    "settings.selection.title": "3. テキストの選択方法",
    "settings.selection.sub": "ホットキーを押したとき、どの範囲を翻訳するかを決めます",
    "settings.prefs.title": "4. 通知とオプション",
    "settings.prefs.toast": "ホットキー実行時に、訳文入りのフローティング通知を表示する",
    "settings.prefs.overlay": "翻訳中は、すべてのウィンドウの上に進行状況を表示する",
    "settings.prefs.sound": "翻訳を貼り付けたときに短い通知音を鳴らす",
    "settings.prefs.restore_clipboard": "翻訳後にコピーしていた内容を元に戻す（訳文がクリップボードを奪わないように）",
    "settings.output.title": "6. 訳文の入力方法",
    "settings.output.sub": "ゲーム内で何も表示されない場合は、1文字ずつ入力する方式に切り替えてください",
    "settings.output.paste": "Ctrl+V で貼り付け — 高速。通常のアプリ向け",
    "settings.output.type": "1文字ずつ入力 — 低速だが、ゲームのチャット欄に届く",
    "settings.prefs.tray": "閉じる (X) でタスクトレイに最小化して、ホットキーを動かし続ける",
    "settings.prefs.start_min": "起動時にタスクトレイへ最小化する",
    "settings.theme.title": "5. ウィンドウのテーマ",
    "settings.language.title": "1. 表示言語 (Interface Language)",
    "settings.language.sub": "アプリ自体の表示言語をすぐに切り替えます。翻訳に使う言語ペアとは別の設定です",
    "settings.save": "💾  設定を保存",
    "settings.reset": "初期設定に戻す",
    "settings.saved": "✅ 設定を保存しました",

    "theme.System": "システムに合わせる",
    "theme.Dark": "ダーク",
    "theme.Light": "ライト",

    "selection.all.badge": "📦 入力欄すべて (Ctrl+A)",
    "selection.all.desc": "チャットアプリ向け (LINE, Discord, Messenger, Slack)",
    "selection.smart.badge": "🧠 スマートモード",
    "selection.smart.desc": "選択範囲があればそれを、なければ全体を対象にします",
    "selection.line.badge": "📝 行頭まで (Shift+Home)",
    "selection.line.desc": "長い文書向け (Microsoft Word, Notepad)",
    "selection.selection.badge": "✂️ 選択範囲のみ",
    "selection.selection.desc": "マウスで選択した部分だけを翻訳します",

    "guide.hero.title": "📖  Typist Translator の使い方",
    "guide.hero.sub": "ある言語で入力してホットキーを押すと、その場で訳文に置き換わります。Windows のどのアプリでも使えます",
    "guide.step1.title": "アプリを起動したままにする",
    "guide.step1.desc": "X で閉じるとタスクトレイに最小化され、ホットキーはそのまま使えます",
    "guide.step2.title": "どのアプリでも入力する",
    "guide.step2.desc": "LINE, Discord, Messenger, Slack, Microsoft Word, Notepad, Chrome, Edge など",
    "guide.step3.title": "ホットキーを押す",
    "guide.step3.desc": "テキストを選択して翻訳し、その場に貼り付けます。結果はトーストでお知らせします",
    "guide.step4.title": "訳がおかしいときは Ctrl + Alt + Z",
    "guide.step4.desc": "元のテキストをすぐに戻します。直前の翻訳に対して5分間有効で、その後に入力があった場合は上書きしません。キーは 設定 › 項目2 で変更できます",
    "guide.pairs.title": "🌐  自由な言語ペア (Custom Auto-Swap)",
    "guide.pairs.note": "100 以上の言語を、タイ語名・英語名・ISO コードで検索できます",
    "guide.pair.desc": "{a}で入力すると{b}に • {b}で入力すると{a}に",
    "guide.engines.title": "🤖  対応する翻訳エンジン",

    "lang.th": "タイ語",
    "lang.en": "英語",
    "lang.ja": "日本語",
    "lang.zh-CN": "中国語 (簡体字)",
    "lang.zh-TW": "中国語 (繁体字)",
    "lang.ko": "韓国語",
    "lang.de": "ドイツ語",
    "lang.fr": "フランス語",
    "lang.es": "スペイン語",
    "lang.ru": "ロシア語",
    "lang.vi": "ベトナム語",
    "lang.zh": "中国語",

    "picker.title_a": "メイン言語を選択 (A)",
    "picker.title_b": "サブ言語を選択 (B)",
    "picker.sub": "100 以上の言語を、タイ語名・英語名・ISO コードで検索できます",
    "picker.search": "🔍  言語を検索 (例: Thai, English, Japanese, zh, de, ko)...",
    "picker.popular": "よく使う言語",
    "picker.select": "選択",
    "picker.selected": "選択中 ✓",
    "picker.empty": "「{query}」に一致する言語が見つかりません\n別の名前か ISO コードでお試しください",

    "update.available.title": "バージョン {version} が利用できます",
    "update.available.body": "「今すぐ更新」を押すと、ダウンロードとインストールを行い、自動で再起動します。",
    "update.action.install": "今すぐ更新",
    "update.action.later": "あとで",
    "update.action.skip": "このバージョンをスキップ",
    "update.action.retry": "再試行",
    "update.action.page": "ダウンロードページを開く",
    "update.downloading": "ダウンロード中… {done} / {total} MB",
    "update.installing.title": "インストール中",
    "update.installing.body": "まもなくアプリを終了し、自動で再起動します。",
    "update.failed.title": "更新できませんでした",
    "update.failed.body": "もう一度お試しいただくか、Releases ページから手動でダウンロードしてください。",
    "update.check.now": "更新を確認",
    "update.check.checking": "確認中…",
    "update.check.current": "最新バージョンです ({version})",
    "update.check.found": "バージョン {version} が利用できます",
    "update.portable_only": "このコピーはインストーラー経由ではないため自動更新できません。Releases ページから新しいバージョンを入手してください。",
    "settings.prefs.autoupdate": "更新を自動で確認し、画面右下で知らせる",
    "whatsnew.title": "バージョン {version} に更新しました",
    "whatsnew.sub": "変更点はこちらです",
    "whatsnew.close": "使いはじめる",
    "whatsnew.full": "GitHub で全文を読む",

    "nav.about": "情報",
    "about.hero.title": "{app}",
    "about.hero.sub": "Windows のどのアプリでも、入力しながらその場で翻訳",
    "about.hero.by": "制作: {author}",
    "about.alias": "{author} と {alias} は同一人物です",
    "about.what.title": "できること",
    "about.what.body": "チャット、文書、ブラウザ — どのアプリで入力していても、ホットキーを一度押すだけ。文字を選択して翻訳し、その場に訳文を貼り付けます。コピーも、新しいタブも、キーボードから手を離す必要もありません。",
    "about.how.title": "しくみ",
    "about.how.body": "ホットキー、クリップボード、タスクトレイは Python が Windows と直接やり取りしています。画面は React を WebView2 で描画 — Windows に最初から入っているので、Chromium を同梱する必要がありません。一度翻訳した文はメモリに残るため、次は即座に返ります。",
    "about.privacy.title": "データの扱い",
    "about.privacy.body": "入力した文が送られるのは、あなたが選んだ翻訳エンジンだけです。履歴と API キーは config.json としてこの PC に残ります。利用状況の収集は一切ありません。",
    "about.tech.title": "使用技術",
    "about.links.title": "リンクと連絡先",
    "about.links.empty": "リンクが未設定です。{file} を編集して再起動してください。UI の再ビルドは不要です。",
    "about.link.github": "GitHub のソースコード",
    "about.link.github.sub": "コードを読む、スターを付ける、フォークする",
    "about.link.issues": "不具合の報告 / 機能の要望",
    "about.link.issues.sub": "困ったことや欲しい機能はこちらへ",
    "about.link.releases": "最新版をダウンロード",
    "about.link.releases.sub": "各バージョンと変更点の一覧",
    "about.link.facebook": "Facebook でフォロー",
    "about.link.facebook.sub": "アプリのお知らせと更新情報",
    "about.link.email": "開発者にメールする",
    "about.link.email.sub": "個別に相談したいことがあれば",
    "about.open": "開く",
    "about.license.title": "ライセンス",
    "about.license.body": "{license} ライセンスで公開しています。利用、改変、再配布は自由です。作者のクレジットだけ残してください。",
    "about.version": "バージョン {version}",

    "overlay.reading": "テキストを読み取り中…",
    "overlay.translating": "翻訳中…",
    "overlay.slow": "まだ翻訳中です。少々お待ちください…",
    "overlay.pasting": "訳文を貼り付け中…",
    "overlay.done": "翻訳完了",
    "overlay.failed": "翻訳できませんでした",
    "overlay.no_text": "翻訳するテキストがありません",
    "overlay.no_text_hint": "入力欄をクリックしてから、もう一度ホットキーを押してください",
    "overlay.blocked": "Windows がキー入力を拒否しました",
    "overlay.blocked_hint": "対象のプログラムの権限が上です。Typist を管理者として実行してみてください",
    "overlay.done_fallback": "翻訳完了（{engine} を使用）",
    "overlay.undoing": "元に戻しています…",
    "overlay.undone": "元のテキストに戻しました",
    "overlay.no_undo": "元に戻せるものがありません",
    "overlay.no_undo_hint": "直前の翻訳のみ、5分以内に限り元に戻せます",
    "overlay.undo_changed": "元に戻せません",
    "overlay.undo_changed_hint": "テキストが変更されているため、上書きしませんでした",

    "toast.success": "翻訳して置き換えました",
    "toast.original": "元の文: {text}",

    "tray.open": "開く",
    "tray.enabled": "ホットキー有効",
    "tray.exit": "終了",
    "tray.tooltip": "Typist Translator — 入力しながら翻訳",

    "error.translate": "翻訳に失敗しました: {msg}",
}

CATALOG["zh-CN"] = {
    "app.window_title": "Typist Translator • 边打字边翻译",
    "app.tagline": "在任何 Windows 程序里，边打字边即时翻译",
    "app.status.active": "运行中 (Active)",
    "app.status.paused": "已暂停 (Paused)",
    "app.switch.hotkey": "启用快捷键",

    "nav.home": "主页",
    "nav.models": "翻译引擎",
    "nav.settings": "设置",
    "nav.guide": "使用说明",

    "home.hotkey.title": "⌨️  主快捷键",
    "home.hotkey.hint": "打完字按一下：选中 › 翻译 › 替换",
    "home.pair.title": "🌐  快捷语言对",
    "home.pair.hint": "点击语言进行搜索 • 按 ↔ 互换",
    "home.engine.title": "🤖  当前引擎",
    "home.engine.mode": "模式：{mode}",

    "sandbox.samples": "快捷示例",
    "sandbox.input": "📝  原文",
    "sandbox.output": "✨  译文",
    "sandbox.chars": "{n} 个字符",
    "sandbox.translate": "⚡ 翻译",
    "sandbox.translating": "翻译中{dots}",
    "sandbox.default_input": "你好，很高兴认识你。",
    "sandbox.default_output": "Hello, nice to meet you.",

    "action.copy": "📋 复制",
    "action.copied": "✓ 已复制",

    "chip.greet": "👋 问候",
    "chip.work": "💼 工作",
    "chip.meeting": "📅 会议",
    "chip.thanks": "🙏 致谢",
    "sample.greet": "你好，很高兴认识你。",
    "sample.work": "Please review the attached document.",
    "sample.meeting": "明天几点开会比较方便？",
    "sample.thanks": "Thank you so much for your assistance!",

    "history.title": "📜  最近的翻译记录",
    "history.count": "{n} 条",
    "history.found": "找到 {n} 条",
    "history.search": "🔍  搜索记录...",
    "history.clear": "清空记录",
    "history.empty": "还没有翻译记录\n用快捷键翻译的内容会自动保存在这里",

    "models.head.title": "🤖  选择翻译服务商",
    "models.head.desc": "Google 翻译和 MyMemory 免费且无需配置。填入 DeepL、Gemini 或 OpenAI 的 API Key 可获得更高质量的翻译。",
    "models.section1.title": "1. 主要服务商",
    "models.section1.sub": "快捷键和下方试译框都会使用它",
    "models.section2.title": "2. 所选引擎的设置",
    "models.section2.sub": "填写的内容会自动保存",
    "models.free_ready": "✓  该引擎免费即用，无需配置 API Key",
    "models.test": "🔌  测试连接",
    "models.testing": "⏳ 正在测试连接...",
    "models.test_ok": "✅ 连接成功！({ms} ms)",
    "models.test_fail": "❌ {msg}",
    "models.deepl.key": "DeepL API Key（Free 或 Pro）",
    "models.deepl.placeholder": "请输入 DeepL 认证密钥...",
    "models.gemini.key": "Google Gemini AI Studio API Key",
    "models.gemini.placeholder": "请输入 Google AI Studio 密钥（AIzaSy...）",
    "models.gemini.model": "Gemini 模型",
    "models.openai.key": "OpenAI / Groq API Key",
    "models.openai.model": "模型",
    "models.openai.base_url": "自定义 Base URL（用于 Groq 或本地 LLM）",

    "engine.google_gtx.badge": "免费 • 无需密钥",
    "engine.google_gtx.desc": "Google 的标准引擎，快速准确，永久免费",
    "engine.mymemory.badge": "免费 • 众包",
    "engine.mymemory.desc": "全球最大的翻译记忆库，免注册免费使用",
    "engine.deepl.badge": "高级 • 需要 API Key",
    "engine.deepl.desc": "世界一流的自然语感翻译（支持 DeepL Free / Pro 密钥）",
    "engine.gemini.badge": "AI 模型 • Google Studio 密钥",
    "engine.gemini.desc": "由 AI 模型（Gemini 1.5 Flash / 2.0）结合上下文翻译",
    "engine.openai.badge": "AI 模型 • API Key",
    "engine.openai.desc": "可使用 GPT-4o-mini、Llama 3 或任何兼容 OpenAI 的接口",

    "settings.hotkey.title": "2. 快捷键",
    "settings.hotkey.sub": "从列表中选择，或在右侧自行输入",
    "settings.hotkey.placeholder": "例如 ctrl+alt+t 或 f8",
    "settings.hotkey.error": "⚠️ 无法注册该快捷键：{msg}",
    "settings.hotkey.custom": "自定义",
    "settings.hotkey.undo": "还原快捷键",
    "settings.hotkey.undo_placeholder": "例如 ctrl+alt+z（留空则关闭）",
    "settings.hotkey.undo_sub": "翻译不理想时把原文还原回去。仅对最近一次翻译有效，限 5 分钟内，"
                                "若文字已被更改则不会覆盖。",
    "settings.hotkey.undo_error": "⚠️ 无法使用该快捷键：{msg}",
    "settings.selection.title": "3. 文本选取方式",
    "settings.selection.sub": "决定按下快捷键时要翻译哪一段文字",
    "settings.prefs.title": "4. 通知与其他选项",
    "settings.prefs.toast": "按下快捷键时显示带译文的浮动提示",
    "settings.prefs.overlay": "翻译时在文字旁显示“正在翻译”动画，悬浮于所有窗口之上",
    "settings.prefs.sound": "译文粘贴完成后播放提示音",
    "settings.prefs.restore_clipboard": "翻译后还原你原本复制的内容（避免译文占用剪贴板）",
    "settings.output.title": "6. 译文的写回方式",
    "settings.output.sub": "如果在游戏里没有反应，请改为逐字输入",
    "settings.output.paste": "用 Ctrl+V 粘贴 — 快速，适用于普通程序",
    "settings.output.type": "逐字输入 — 较慢，但能进入游戏聊天框",
    "settings.prefs.tray": "点击关闭 (X) 时最小化到系统托盘，让快捷键继续生效",
    "settings.prefs.start_min": "启动时直接最小化到系统托盘",
    "settings.theme.title": "5. 窗口主题",
    "settings.language.title": "1. 界面语言 (Interface Language)",
    "settings.language.sub": "立即切换程序自身的显示语言，与翻译文本所用的语言对无关",
    "settings.save": "💾  保存设置",
    "settings.reset": "恢复默认",
    "settings.saved": "✅ 设置已保存",

    "theme.System": "跟随系统",
    "theme.Dark": "深色",
    "theme.Light": "浅色",

    "selection.all.badge": "📦 整个输入框 (Ctrl+A)",
    "selection.all.desc": "推荐用于聊天软件（LINE、Discord、Messenger、Slack）",
    "selection.smart.badge": "🧠 智能模式",
    "selection.smart.desc": "有选中内容就用选中的，没有就自动全选",
    "selection.line.badge": "📝 到行首 (Shift+Home)",
    "selection.line.desc": "适合长文档（Microsoft Word、Notepad）",
    "selection.selection.badge": "✂️ 仅选中内容",
    "selection.selection.desc": "只翻译你用鼠标选中的文字",

    "guide.hero.title": "📖  Typist Translator 使用指南",
    "guide.hero.sub": "用一种语言打字，按下快捷键，文字立刻被替换成译文——在任何 Windows 程序里都能用",
    "guide.step1.title": "让程序保持运行",
    "guide.step1.desc": "点击 X 关闭会最小化到系统托盘，快捷键依然有效",
    "guide.step2.title": "在任意程序中打字",
    "guide.step2.desc": "LINE、Discord、Messenger、Slack、Microsoft Word、Notepad、Chrome、Edge 等",
    "guide.step3.title": "按下快捷键",
    "guide.step3.desc": "程序会选中文字、翻译并原地粘贴，同时弹出提示告知结果",
    "guide.step4.title": "译文不满意？按 Ctrl + Alt + Z",
    "guide.step4.desc": "立刻还原你的原文。仅对最近一次翻译有效，限 5 分钟内；如果你之后又输入了内容，程序不会覆盖。可在 设置 › 第 2 项 更改按键",
    "guide.pairs.title": "🌐  自由语言配对 (Custom Auto-Swap)",
    "guide.pairs.note": "可按泰文名称、英文名称或 ISO 代码搜索 100 多种语言",
    "guide.pair.desc": "打{a}出{b} • 打{b}出{a}",
    "guide.engines.title": "🤖  支持的翻译引擎",

    "lang.th": "泰语",
    "lang.en": "英语",
    "lang.ja": "日语",
    "lang.zh-CN": "中文（简体）",
    "lang.zh-TW": "中文（繁体）",
    "lang.ko": "韩语",
    "lang.de": "德语",
    "lang.fr": "法语",
    "lang.es": "西班牙语",
    "lang.ru": "俄语",
    "lang.vi": "越南语",
    "lang.zh": "中文",

    "picker.title_a": "选择主要语言 (A)",
    "picker.title_b": "选择次要语言 (B)",
    "picker.sub": "可按泰文名称、英文名称或 ISO 代码搜索 100 多种语言",
    "picker.search": "🔍  搜索语言（例如 Thai、English、Japanese、zh、de、ko）...",
    "picker.popular": "常用语言",
    "picker.select": "选择",
    "picker.selected": "已选择 ✓",
    "picker.empty": "找不到与“{query}”匹配的语言\n请换个名称或 ISO 代码再试",

    "update.available.title": "有新版本 {version}",
    "update.available.body": "点击更新即可自动下载、安装并重新打开程序。",
    "update.action.install": "立即更新",
    "update.action.later": "稍后",
    "update.action.skip": "跳过此版本",
    "update.action.retry": "重试",
    "update.action.page": "打开下载页面",
    "update.downloading": "正在下载… {done} / {total} MB",
    "update.installing.title": "正在安装",
    "update.installing.body": "程序将关闭并在稍后自动重新打开。",
    "update.failed.title": "更新失败",
    "update.failed.body": "请重试，或从 Releases 页面手动下载。",
    "update.check.now": "检查更新",
    "update.check.checking": "正在检查…",
    "update.check.current": "已是最新版本 ({version})",
    "update.check.found": "有新版本 {version}",
    "update.portable_only": "此副本并非通过安装程序安装，无法自动更新 —— 请从 Releases 页面下载新版本。",
    "settings.prefs.autoupdate": "自动检查更新，并在右下角提示我",
    "whatsnew.title": "已更新到版本 {version}",
    "whatsnew.sub": "以下是本次的变化",
    "whatsnew.close": "开始使用",
    "whatsnew.full": "在 GitHub 上查看完整说明",

    "nav.about": "关于",
    "about.hero.title": "{app}",
    "about.hero.sub": "在 Windows 的任何程序里，边打字边翻译，无需切换窗口",
    "about.hero.by": "作者：{author}",
    "about.alias": "{author} 与 {alias} 是同一个人",
    "about.what.title": "它能做什么",
    "about.what.body": "在任何程序里输入文字 —— 聊天框、文档、浏览器 —— 按一次快捷键，它会选中文字、翻译，并把译文原地替换进去。不用复制，不用另开标签页，手也不用离开键盘。",
    "about.how.title": "工作原理",
    "about.how.body": "快捷键、剪贴板和托盘图标由 Python 直接与 Windows 交互；界面是 React，交给 Windows 自带的 WebView2 渲染，因此不必打包整个 Chromium。翻译过的内容会缓存在内存中，再按一次立即返回。",
    "about.privacy.title": "你的数据",
    "about.privacy.body": "文字只会发送到你选择的翻译引擎。历史记录和 API 密钥保存在本机的 config.json 中，不会外传，也没有任何使用统计。",
    "about.tech.title": "技术栈",
    "about.links.title": "关注与联系",
    "about.links.empty": "还没有填写链接 —— 编辑 {file} 后重启即可，无需重新构建界面。",
    "about.link.github": "GitHub 源代码",
    "about.link.github.sub": "阅读代码、点个 Star，或 Fork 后继续开发",
    "about.link.issues": "反馈问题 / 提出需求",
    "about.link.issues.sub": "遇到 Bug 或想要新功能都可以说",
    "about.link.releases": "下载最新版本",
    "about.link.releases.sub": "各版本及其更新内容",
    "about.link.facebook": "在 Facebook 关注",
    "about.link.facebook.sub": "程序的消息与更新",
    "about.link.email": "给开发者发邮件",
    "about.link.email.sub": "想单独聊的事情",
    "about.open": "打开",
    "about.license.title": "许可协议",
    "about.license.body": "以 {license} 许可协议发布。可自由使用、修改和分发，保留作者署名即可。",
    "about.version": "版本 {version}",

    "overlay.reading": "正在读取文字…",
    "overlay.translating": "正在翻译…",
    "overlay.slow": "仍在翻译，请稍候…",
    "overlay.pasting": "正在粘贴译文…",
    "overlay.done": "翻译完成",
    "overlay.failed": "翻译失败",
    "overlay.no_text": "没有可翻译的文字",
    "overlay.no_text_hint": "先点击输入框，再按一次快捷键",
    "overlay.blocked": "Windows 拒绝了按键输入",
    "overlay.blocked_hint": "目标程序的权限更高，请尝试以管理员身份运行 Typist",
    "overlay.done_fallback": "翻译完成（改用 {engine}）",
    "overlay.undoing": "正在还原…",
    "overlay.undone": "已还原原文",
    "overlay.no_undo": "没有可还原的内容",
    "overlay.no_undo_hint": "只能还原最近一次翻译，且需在 5 分钟内",
    "overlay.undo_changed": "无法还原",
    "overlay.undo_changed_hint": "文字已被更改，因此没有覆盖",

    "toast.success": "已翻译并替换",
    "toast.original": "原文：{text}",

    "tray.open": "打开",
    "tray.enabled": "启用快捷键",
    "tray.exit": "退出",
    "tray.tooltip": "Typist Translator — 边打字边翻译",

    "error.translate": "翻译失败：{msg}",
}
