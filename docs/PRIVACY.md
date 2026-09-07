# Privacy

Typist Translator translates text by sending it to a translation service. That
is the feature, and it means your text leaves your computer. This page says
exactly where it goes.

There is no analytics, no telemetry and no crash reporting. Nothing is sent
anywhere that is not listed below.

---

## Where your text goes

Whichever engine is selected in **Models** is the only one contacted. Switching
engines switches the destination.

| Engine | Host that receives your text | Needs an API key |
|---|---|---|
| Google Translate | `translate.googleapis.com` | No |
| MyMemory | `api.mymemory.translated.net` | No |
| DeepL | `api-free.deepl.com` or `api.deepl.com` | Yes |
| Google Gemini | `generativelanguage.googleapis.com` | Yes |
| OpenAI-compatible | `api.openai.com`, or whatever base URL you configure | Yes |

The two free engines are unofficial or free-tier public endpoints. What those
services do with what they receive is governed by their own terms, not by this
project.

**If a translation fails**, the app retries with the free engines
(Google Translate, then MyMemory) so you are not left with nothing. That means
a failure on a paid engine can send the same text to a free one. If that
matters to you, the fallback is worth knowing about before you translate
something sensitive.

---

## What the app stores, and where

Everything lives in `%APPDATA%\TypistTranslator` on an installed copy, or
beside the source when run from a checkout.

| File | Contains |
|---|---|
| `config.json` | Your hotkey, language pair, engine choice **and any API keys you enter** |
| `update_state.json` | When updates were last checked, and which version you skipped |
| `logs\typist.log` | Start-up and error messages, so a failure to launch is not silent |

**API keys are stored in plain text** in `config.json`, readable by anything
running as your Windows user. They are sent only to the service they belong to,
and never to this project or anywhere else.

**Translation history is kept in memory only.** It holds the last 200
translations, it is visible on the Home tab, and closing the app discards it.
Nothing is written to disk.

---

## What leaves your computer without you asking

One thing: the update check.

Once a day at most, the app asks
`api.github.com/repos/luraselenehalo/typist-translator/releases/latest`
whether a newer release exists. The request carries the app version in its
User-Agent and nothing else — no identifier, no machine details, no usage data.
GitHub sees the request the same way it sees anyone visiting the releases page.

Switch it off in **Settings → section 4**.

---

## What the app can see, and what it does with it

To replace text in place it has to reach into other applications:

- **A global keyboard hook**, so the hotkey works everywhere. It watches for
  that one combination. Other keystrokes are not recorded, stored or
  transmitted.
- **Synthetic keystrokes** (Ctrl+A, Ctrl+C, Ctrl+V) to select, read and replace
  the text you translate.
- **The clipboard**, for the same reason. What you had copied is put back
  afterwards, and you can turn that off.

The text it captures is used for the translation you asked for and then held
only in the in-memory history described above.

---

## Children

This application is not directed at children and collects no personal
information from anyone.

---

## Changes

Material changes to this page will be noted in the release that contains them.

Questions: https://github.com/luraselenehalo/typist-translator/issues
