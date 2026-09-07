"""
Generate the winget and Scoop manifests for the current release.

    python build.py                 # produces release/ and SHA256SUMS.txt
    python tools/make_manifests.py  # turns those into package manifests

Both package managers install without the SmartScreen dialog: winget re-zones
the installer to trusted once its SHA-256 matches the manifest, and Scoop never
writes the download mark in the first place. Neither requires a code-signing
certificate, which makes them the only free way to hand somebody this app
without a blue warning box in the middle.

The hashes are read from the build output rather than typed, because a manifest
whose hash does not match the asset is rejected by winget's validation - and
worse, a stale one that happens to pass would install the wrong file.
"""
import argparse
import json
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.dont_write_bytecode = True

import about  # noqa: E402  - after sys.path, deliberately

RELEASE_DIR = os.path.join(PROJECT, "release")
OUT_DIR = os.path.join(PROJECT, "packaging")

#: winget identifies packages as Publisher.Package, and it never changes.
PACKAGE_ID = "Mrgunshi.TypistTranslator"

#: Inno Setup appends _is1 to the AppId for its uninstall registry key. winget
#: uses this to tell whether the package is already installed, so it has to
#: match packaging/installer.iss exactly.
PRODUCT_CODE = "{D5A42794-BC5C-4F17-B905-BAE69A6255EB}_is1"

SCHEMA = "https://aka.ms/winget-manifest.{kind}.1.6.0.schema.json"


def read_checksums():
    """{filename: sha256} from the SHA256SUMS.txt that build.py wrote."""
    path = os.path.join(RELEASE_DIR, "SHA256SUMS.txt")
    if not os.path.exists(path):
        raise SystemExit(
            f"[manifests] {path} is missing - run 'python build.py' first")
    sums = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            digest, _, name = line.strip().partition("  ")
            if digest and name:
                sums[name] = digest
    return sums


def asset_url(name):
    return (f"{about.github_url()}/releases/download/"
            f"v{about.VERSION}/{name}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"[manifests] {os.path.relpath(path, PROJECT)}")


def winget(sums):
    """The three files microsoft/winget-pkgs expects, under one version folder."""
    installer = f"TypistTranslator-Setup-{about.VERSION}.exe"
    if installer not in sums:
        raise SystemExit(f"[manifests] {installer} is not in SHA256SUMS.txt")

    folder = os.path.join(OUT_DIR, "winget", PACKAGE_ID, about.VERSION)

    # InstallerType: inno, not exe. Declaring it correctly is what lets winget
    # supply /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART itself; calling it a
    # generic exe means winget has no idea how to install it silently.
    write(os.path.join(folder, f"{PACKAGE_ID}.installer.yaml"), f"""\
# yaml-language-server: $schema={SCHEMA.format(kind='installer')}
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {about.VERSION}
InstallerType: inno
Scope: user
InstallModes:
  - interactive
  - silent
  - silentWithProgress
UpgradeBehavior: install
ProductCode: '{PRODUCT_CODE}'
ReleaseDate: {{RELEASE_DATE}}
Installers:
  - Architecture: x64
    InstallerUrl: {asset_url(installer)}
    InstallerSha256: {sums[installer].upper()}
ManifestType: installer
ManifestVersion: 1.6.0
""")

    write(os.path.join(folder, f"{PACKAGE_ID}.locale.en-US.yaml"), f"""\
# yaml-language-server: $schema={SCHEMA.format(kind='defaultLocale')}
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {about.VERSION}
PackageLocale: en-US
Publisher: {about.AUTHOR}
PublisherUrl: https://github.com/{about.GITHUB_USER}
PublisherSupportUrl: {about.github_url()}/issues
Author: {about.AUTHOR}
PackageName: {about.APP_NAME}
PackageUrl: {about.github_url()}
License: {about.LICENSE}
LicenseUrl: {about.github_url()}/blob/main/LICENSE
Copyright: Copyright (c) {about.COPYRIGHT_YEAR} {about.AUTHOR}
ShortDescription: Translate text in place in any Windows application with one hotkey.
Description: |-
  Type in one language, press a hotkey, and the text you typed is replaced by
  its translation - in Discord, LINE, Messenger, Word, a browser, anywhere you
  can type. Over 100 languages across five translation engines, two of which
  need no account or API key. The interface is available in English, Thai,
  Japanese and Simplified Chinese.
Moniker: typist-translator
Tags:
  - translate
  - translation
  - hotkey
  - productivity
  - thai
ReleaseNotesUrl: {about.github_url()}/releases/tag/v{about.VERSION}
ManifestType: defaultLocale
ManifestVersion: 1.6.0
""")

    write(os.path.join(folder, f"{PACKAGE_ID}.yaml"), f"""\
# yaml-language-server: $schema={SCHEMA.format(kind='version')}
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {about.VERSION}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
""")
    return folder


def scoop(sums):
    """A Scoop manifest for the portable zip.

    A Scoop bucket is a git repository of these files and nothing else - no
    review, no gatekeeper. Publish this in a repo named scoop-bucket and it can
    be installed the same day.
    """
    archive = f"TypistTranslator-{about.VERSION}-portable.zip"
    if archive not in sums:
        raise SystemExit(f"[manifests] {archive} is not in SHA256SUMS.txt")

    manifest = {
        "version": about.VERSION,
        "description": "Translate text in place in any Windows application "
                       "with one hotkey.",
        "homepage": about.github_url(),
        "license": about.LICENSE,
        "url": asset_url(archive),
        "hash": sums[archive],
        "extract_dir": f"TypistTranslator-{about.VERSION}",
        "shortcuts": [["TypistTranslator.exe", "Typist Translator"]],
        # Settings live in %APPDATA%, so nothing here needs persisting between
        # versions; Scoop can replace the whole directory on update.
        "checkver": {"github": about.github_url()},
        "autoupdate": {
            "url": (f"{about.github_url()}/releases/download/v$version/"
                    f"TypistTranslator-$version-portable.zip"),
            "extract_dir": "TypistTranslator-$version",
            # No "hash" block on purpose. Pointing it at a checksums file means
            # the release has to carry one forever; without it Scoop downloads
            # the asset and computes the hash itself, which is one less thing
            # that can fall out of step with the release.
        },
        "notes": [
            "Settings and API keys are kept in %APPDATA%\\TypistTranslator and",
            "survive an update or an uninstall.",
            "This portable build cannot update itself - Scoop updates it.",
        ],
    }
    path = os.path.join(OUT_DIR, "scoop", "typist-translator.json")
    write(path, json.dumps(manifest, indent=4, ensure_ascii=False) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-date", default="{RELEASE_DATE}",
                        help="ISO date for the winget manifest, e.g. 2026-09-07")
    args = parser.parse_args()

    sums = read_checksums()
    print(f"[manifests] {about.APP_NAME} {about.VERSION}, "
          f"{len(sums)} artifact(s)")
    folder = winget(sums)
    scoop(sums)

    if args.release_date != "{RELEASE_DATE}":
        target = os.path.join(folder, f"{PACKAGE_ID}.installer.yaml")
        with open(target, encoding="utf-8") as handle:
            text = handle.read()
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace("{RELEASE_DATE}", args.release_date))
        print(f"[manifests] release date set to {args.release_date}")
    else:
        print("[manifests] NOTE: set ReleaseDate before submitting "
              "(--release-date YYYY-MM-DD)")

    print("\nNext:")
    print(f"  winget  copy {os.path.relpath(folder, PROJECT)} into a fork of")
    print("          microsoft/winget-pkgs under manifests/m/"
          f"{PACKAGE_ID.replace('.', '/')}/{about.VERSION}")
    print("          and open a pull request")
    print("  scoop   copy packaging/scoop/typist-translator.json into "
          "bucket/ of your")
    print(f"          scoop-bucket repository")
    return 0


if __name__ == "__main__":
    sys.exit(main())
