"""
Build the Windows release: a frozen application, then an installer around it.

    python build.py            # app + installer
    python build.py --app      # just the frozen app, for testing
    python build.py --ui       # rebuild the React bundle first

Everything version-shaped is read from about.py, so the number is typed once and
flows into the executable's file properties, the installer's AppVersion, the
setup filename and the registry entry.

The whole build is staged into an ASCII-only temporary directory first. The
project lives under a Thai path; PyInstaller handles that, but ISCC and the
Windows resource compiler are far less exercised against non-ASCII paths, and a
staging copy costs a couple of seconds against a class of failure that is
miserable to diagnose.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

import about  # noqa: E402  - after sys.path, deliberately

APP_EXE_NAME = "TypistTranslator"
RELEASE_DIR = os.path.join(PROJECT, "release")
ISCC = os.path.join(PROJECT, "tools", "innosetup", "ISCC.exe")

#: Read-only files that must travel with the executable. Source path -> the
#: folder it lands in, relative to the bundle root.
BUNDLED = [
    (os.path.join("ui", "dist", "index.html"), os.path.join("ui", "dist")),
    (os.path.join("ui", "dist", "icon.png"), os.path.join("ui", "dist")),
    ("icon.ico", "."),
    ("icon_alpha.png", "."),
]

VERSION_RESOURCE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', {publisher!r}),
         StringStruct('FileDescription', {description!r}),
         StringStruct('FileVersion', {version!r}),
         StringStruct('InternalName', {exe!r}),
         StringStruct('LegalCopyright', {copyright!r}),
         StringStruct('OriginalFilename', {exe!r} + '.exe'),
         StringStruct('ProductName', {product!r}),
         StringStruct('ProductVersion', {version!r})])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def say(message):
    print(f"[build] {message}", flush=True)


def run(command, **kwargs):
    result = subprocess.run(command, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"[build] FAILED: {' '.join(map(str, command))}")
    return result


def version_parts():
    """(major, minor, patch) from about.VERSION, tolerating a short version."""
    numbers = [int(part) for part in about.VERSION.split(".")[:3]
               if part.isdigit()]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers


def build_ui():
    say("rebuilding the React bundle")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("[build] npm is not on PATH")
    run([npm, "run", "build"], cwd=os.path.join(PROJECT, "ui"))


def write_version_resource(directory):
    major, minor, patch = version_parts()
    path = os.path.join(directory, "version_info.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(VERSION_RESOURCE.format(
            v0=major, v1=minor, v2=patch,
            publisher=about.AUTHOR,
            description=f"{about.APP_NAME} - translate as you type",
            version=about.VERSION,
            exe=APP_EXE_NAME,
            copyright=f"(c) {about.COPYRIGHT_YEAR} {about.AUTHOR} - "
                      f"{about.LICENSE} licence",
            product=about.APP_NAME))
    return path


def freeze(stage):
    """Run PyInstaller. onedir, never onefile.

    onefile re-extracts the whole 40 MB bundle into %TEMP% on every launch,
    which would undo the ~1 second startup the app is built around, and it is a
    stronger antivirus heuristic. onedir is also what lets the installer replace
    individual files instead of one opaque blob.
    """
    say(f"freezing {about.APP_NAME} {about.VERSION}")
    work = os.path.join(stage, "work")
    dist = os.path.join(stage, "dist")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--log-level", "WARN",
        "--name", APP_EXE_NAME,
        "--noconsole",
        "--distpath", dist, "--workpath", work, "--specpath", work,
        "--icon", os.path.join(PROJECT, "icon.ico"),
        "--version-file", write_version_resource(stage),
        # UPX shrinks the build but is a well-known antivirus heuristic, and
        # this app already looks suspicious enough: it installs a keyboard hook
        # and synthesises keystrokes.
        "--noupx",
    ]
    for source, target in BUNDLED:
        command += ["--add-data", f"{os.path.join(PROJECT, source)};{target}"]
    command.append(os.path.join(PROJECT, "main.py"))
    run(command)
    return os.path.join(dist, APP_EXE_NAME)


def compile_installer(payload, stage):
    if not os.path.exists(ISCC):
        raise SystemExit(
            "[build] Inno Setup is missing. Run:  python tools/get_innosetup.py")
    say("compiling the installer")
    script = os.path.join(stage, "installer.iss")
    shutil.copy2(os.path.join(PROJECT, "packaging", "installer.iss"), script)
    shutil.copy2(os.path.join(PROJECT, "icon.ico"), os.path.join(stage, "icon.ico"))
    os.makedirs(RELEASE_DIR, exist_ok=True)
    run([ISCC,
         f"/DAppVersion={about.VERSION}",
         f"/DSourceDir={payload}",
         f"/DOutputDir={RELEASE_DIR}",
         f"/DAssetsDir={stage}",
         script])
    return os.path.join(
        RELEASE_DIR, f"TypistTranslator-Setup-{about.VERSION}.exe")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", action="store_true",
                        help="stop after the frozen app; skip the installer")
    parser.add_argument("--ui", action="store_true",
                        help="rebuild the React bundle first")
    parser.add_argument("--keep", action="store_true",
                        help="leave the staging directory for inspection")
    args = parser.parse_args()

    if args.ui:
        build_ui()
    if not os.path.exists(os.path.join(PROJECT, "ui", "dist", "index.html")):
        raise SystemExit("[build] ui/dist/index.html is missing - run with --ui")

    started = time.perf_counter()
    stage = tempfile.mkdtemp(prefix="typist-build-")
    say(f"staging in {stage}")
    try:
        payload = freeze(stage)
        size = sum(os.path.getsize(os.path.join(root, name))
                   for root, _, files in os.walk(payload) for name in files)
        say(f"app: {payload}  ({size / 1048576:.0f} MB)")

        if args.app:
            target = os.path.join(PROJECT, "dist", APP_EXE_NAME)
            shutil.rmtree(target, ignore_errors=True)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copytree(payload, target)
            say(f"copied to {target}")
            return 0

        setup = compile_installer(payload, stage)
        say(f"installer: {setup}  "
            f"({os.path.getsize(setup) / 1048576:.1f} MB)")
    finally:
        if args.keep:
            say(f"staging kept at {stage}")
        else:
            shutil.rmtree(stage, ignore_errors=True)

    say(f"done in {time.perf_counter() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
