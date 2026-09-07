# Security, signing and integrity

Typist Translator is not code-signed. This page says what that means, what you
can check instead, and what it would take to change — without pretending the
situation is better than it is.

---

## Why Windows warns you

Downloading the installer and running it produces:

> **Windows protected your PC**
> Microsoft Defender SmartScreen prevented an unrecognized app from starting.
> Publisher: **Unknown publisher**

Click **More info → Run anyway**.

SmartScreen is a *reputation* check, not a malware scan. It asks two questions:
is this exact file already widely seen, and is it signed by a publisher with a
history? A brand-new release from a one-person project is neither, so the
dialog appears.

**It will keep appearing on every new version.** Microsoft is explicit that an
unsigned file starts from zero reputation each release and cannot inherit any
from the version before it. Waiting it out is not a strategy that can work:
this project ships a new file every release, and each one starts over.

### Two different systems, often confused

|                        | **SmartScreen** | **Microsoft Defender (antivirus)** |
|------------------------|-----------------|------------------------------------|
| What it is             | Reputation on the file and its publisher | Malware detection |
| What you see           | Blue *"Windows protected your PC"* box | Red *"Threat found"*, file quarantined |
| What fixes it          | An Authenticode signature, plus reputation | Reporting a false positive to Microsoft |
| Submitting to the [Microsoft submission portal](https://www.microsoft.com/wdsi/filesubmission) | **Does nothing** | This is the right channel |

If Defender ever quarantines a release, that is a false positive worth
reporting — PyInstaller bundles that install a keyboard hook are a known
heuristic trigger. It is a *separate* problem from the blue dialog, with a
separate fix, and advice for one does not apply to the other.

---

## What you can verify instead

### The checksum

Every release lists the SHA-256 of both files in its notes. Compare against
your download:

```powershell
Get-FileHash .\TypistTranslator-Setup-<version>.exe
```

This proves the file reached you unaltered. It does not prove who built it —
only a signature does that.

### The scan

Every release links a VirusTotal report for both artifacts. The address is
derived from the checksum, so you can go straight there:
`https://www.virustotal.com/gui/file/<sha256>`

### The build

```bash
git clone https://github.com/luraselenehalo/typist-translator.git
cd typist-translator
pip install -r requirements.txt
python tools/get_innosetup.py
python build.py
```

`build.py` produces the same two files that get published. `tools/get_innosetup.py`
fetches Inno Setup from its official release and refuses to install it unless
the Authenticode signature names its real publisher.

### The source

There is no obfuscation and no minified backend. The network code is small
enough to read in an afternoon: `translator_core.py` for the translation
engines, `updater.py` for updates, `http_pool.py` for the connections.

---

## Where releases come from

The only address these builds are published from is
**https://github.com/luraselenehalo/typist-translator**.

A copy of this application offered from anywhere else was not published by me,
and its checksum will not match the one published in that release's notes.

---

## What the updater guarantees, and what it does not

`updater.py` only ever contacts this repository, and the address is compiled in
from `about.py` rather than read from your settings file. It follows redirects
only to github.com and githubusercontent.com, over https, at most three hops.
It verifies every downloaded byte against the SHA-256 digest GitHub publishes
for the asset before running anything, and a file that does not match is
deleted rather than kept.

**The honest ceiling:** that digest arrives in the same TLS response as the
download link. It proves the file was not altered on its way to you. It does
*not* prove that I was the one who published it. Anyone able to push a release
to this repository could publish a payload and a matching digest. Closing that
gap needs a code-signing certificate and a signature check against a pinned
publisher — see below.

---

## Why it is not signed yet

Not for lack of trying to find a way. As of September 2026:

| Route | Status |
|---|---|
| **Azure Trusted Signing** (~USD 120/yr) | Individual accounts are restricted to the United States and Canada. The author is in Thailand, so this is closed. |
| **An EV certificate** (USD 200–400/yr) | Microsoft removed EV's instant-SmartScreen-trust behaviour in 2024. It now buys nothing that a cheaper OV certificate does not. |
| **Certum Open Source Cloud** (~USD 58/yr) | The realistic purchasable option. Still needs reputation to accumulate afterwards — it is not an instant fix. |
| **SignPath Foundation** (free for open source) | Free OV signing, but it requires a build running on a trusted CI system and is granted at their discretion to established projects. |
| **Microsoft Store (MSIX)** | Microsoft signs Store packages itself, and Store installs never show the warning. Individual developer registration became free in 2025. This is real, and it is a substantial repackaging job. |

What has been done in the meantime: `packaging/installer.iss` already carries
the signing hook, disabled. The day a certificate exists, signing the outer
installer — the file that actually carries the warning — is one environment
variable, not a redesign.

---

## Installing without the warning today

Both of these avoid the dialog by construction, because neither hands the file
to Windows the way a browser download does:

```powershell
winget install Mrgunshi.TypistTranslator
```

```powershell
scoop bucket add typist https://github.com/luraselenehalo/scoop-bucket
scoop install typist-translator
```

The portable zip is **not** a way around it: Windows Explorer, WinRAR and
WinZip all carry the download mark across to extracted files.

---

## What the app does that looks alarming

Stated plainly, because a translator that types for you has to do things that
look like the things malware does:

- **It installs a global low-level keyboard hook** so the hotkey works in any
  application. It watches for that one combination; it does not log what you
  type. See `hotkey_manager.py`.
- **It synthesises keystrokes** — Ctrl+A, Ctrl+C, Ctrl+V — to read the text you
  selected and paste the translation back. That is the whole feature.
- **It reads and writes the clipboard**, for the same reason, and puts back
  what you had copied when it is done.
- **It sends the text you translate to a translation service.** Which one
  depends on the engine you choose. See [PRIVACY.md](PRIVACY.md) for the exact
  list of hosts.
- **It does not phone home.** There is no analytics, no telemetry, no crash
  reporting. The only request the app makes that you did not trigger is the
  update check against this repository's releases, which you can switch off in
  Settings.

---

## Reporting something

Open an issue at
https://github.com/luraselenehalo/typist-translator/issues.

If you believe you have found a vulnerability rather than a bug, say so in the
title and leave out the exploit details until we have talked.
