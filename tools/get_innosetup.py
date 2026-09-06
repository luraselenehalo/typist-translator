"""
Fetch the Inno Setup compiler that build.py needs.

    python tools/get_innosetup.py

Installs it portably into ``tools/innosetup`` - no system-wide install, no
administrator rights, nothing added to PATH, and ``tools/`` is gitignored. The
downloaded installer's Authenticode signature is checked before it is run.

The Simplified Chinese wizard translation is not part of the standard set, so it
is fetched separately from the same official repository, where it lives under
Files/Languages/Unofficial.
"""
import ctypes
import os
import subprocess
import sys
import urllib.request

VERSION = "6.7.3"
TAG = "is-6_7_3"
BASE = f"https://github.com/jrsoftware/issrc/releases/download/{TAG}"
SETUP_URL = f"{BASE}/innosetup-{VERSION}.exe"
CHINESE_URL = ("https://raw.githubusercontent.com/jrsoftware/issrc/"
               f"{TAG}/Files/Languages/Unofficial/ChineseSimplified.isl")

#: The certificate the official installer is signed with. Checked so a broken
#: mirror or a hijacked link cannot hand us something else to execute.
EXPECTED_SIGNER = "Pyrsys B.V."

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "innosetup")
DOWNLOAD = os.path.join(HERE, "innosetup-setup.exe")


def say(message):
    print(f"[innosetup] {message}", flush=True)


def download(url, destination):
    say(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    with open(destination, "wb") as handle:
        handle.write(data)
    return len(data)


def signer_of(path):
    """The Authenticode subject, via PowerShell - no extra dependency."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"$s = Get-AuthenticodeSignature '{path}';"
         "if ($s.Status -ne 'Valid') { 'INVALID' } else"
         " { $s.SignerCertificate.Subject }"],
        capture_output=True, text=True)
    return result.stdout.strip()


def main():
    if sys.platform != "win32":
        raise SystemExit("[innosetup] Windows only")
    if os.path.exists(os.path.join(TARGET, "ISCC.exe")):
        say(f"already present: {TARGET}")
        return 0

    os.makedirs(HERE, exist_ok=True)
    size = download(SETUP_URL, DOWNLOAD)
    say(f"got {size / 1048576:.1f} MB")

    signer = signer_of(DOWNLOAD)
    if EXPECTED_SIGNER not in signer:
        os.remove(DOWNLOAD)
        raise SystemExit(
            f"[innosetup] refusing to run it: expected a build signed by "
            f"{EXPECTED_SIGNER!r}, got {signer!r}")
    say(f"signature verified: {signer}")

    say("installing portably")
    result = subprocess.run([DOWNLOAD, "/PORTABLE=1", "/VERYSILENT",
                             "/SUPPRESSMSGBOXES", "/NORESTART",
                             f"/DIR={TARGET}"])
    if result.returncode != 0 or not os.path.exists(
            os.path.join(TARGET, "ISCC.exe")):
        raise SystemExit("[innosetup] the portable install did not complete")
    os.remove(DOWNLOAD)

    chinese = os.path.join(TARGET, "Languages", "ChineseSimplified.isl")
    if not os.path.exists(chinese):
        download(CHINESE_URL, chinese)
        say("added the Simplified Chinese wizard translation")

    missing = [name for name in ("Default.isl", "Languages/Thai.isl",
                                 "Languages/Japanese.isl",
                                 "Languages/ChineseSimplified.isl")
               if not os.path.exists(os.path.join(TARGET, name.replace("/", os.sep)))]
    if missing:
        raise SystemExit(f"[innosetup] wizard translations missing: {missing}")

    say(f"ready: {TARGET}")
    say("all four wizard languages present (en / th / ja / zh-CN)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
