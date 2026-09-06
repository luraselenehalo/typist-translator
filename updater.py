"""
Self-update: find a newer release, fetch it, prove it is ours, hand over.

No user interface here - this module only decides and downloads. ``main.py``
owns the notification and the restart, so the risky part can be tested without
opening a window.

This is the one feature that downloads and executes code, so the rules are
tighter than anywhere else in the project:

* Only ``about.GITHUB_USER``/``about.GITHUB_REPO`` are ever contacted, and the
  URL is built at import time from ``about.py`` - never from ``config.json``,
  which is a file an attacker who can already write to the user's profile could
  edit.
* Redirects are followed only to github.com and githubusercontent.com, over
  https, at most three hops. GitHub serves release assets from a redirect, so
  they cannot simply be refused - but an open redirect chain to an arbitrary
  host is how a download turns into someone else's payload.
* The bytes are hashed while streaming and the file is only given its real name
  once the SHA-256 matches the ``digest`` GitHub publishes for the asset. A
  partial or altered download is never left somewhere it could be executed.
* There is a size ceiling, so a hostile or broken response cannot fill the disk.

**The limit of all this, stated plainly:** the checksum arrives in the same TLS
response as the download URL, so it proves the bytes were not altered in
transit - not that they were published by the author. Anyone able to push a
release to the repository can publish a payload and a matching hash. Closing
that gap needs a code-signing certificate and a WinVerifyTrust check against a
pinned publisher; until one exists, this is the honest ceiling.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

import about
import paths
import update_state

API_URL = (f"https://api.github.com/repos/{about.GITHUB_USER}/"
           f"{about.GITHUB_REPO}/releases/latest")
RELEASES_PAGE = f"{about.github_url()}/releases/latest"

USER_AGENT = f"TypistTranslator/{about.VERSION} (+{about.github_url()})"
ALLOWED_HOSTS = ("github.com", "githubusercontent.com", "github-releases.githubusercontent.com")

#: Nothing we publish is anywhere near this. A ceiling stops a broken or
#: hostile response from filling the user's disk.
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
CHUNK = 64 * 1024

CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT = 30


class UpdateError(Exception):
    """Anything that stops an update. Always carries a reason worth showing."""


# =====================================================================
# Versions
# =====================================================================
def parse_version(text):
    """('v3.10.0') -> (3, 10, 0). None when it is not a version at all.

    Tuples, not strings: as strings "3.0.9" sorts after "3.0.10", which this
    project would hit the first time it reaches a tenth patch release.
    """
    if not text:
        return None
    match = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text).strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(candidate, current=None) -> bool:
    """Strictly newer only. Unparseable input is never an update."""
    new = parse_version(candidate)
    old = parse_version(current if current is not None else about.VERSION)
    if new is None or old is None:
        return False
    return new > old


# =====================================================================
# Network
# =====================================================================
class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's asset redirect, and nothing else."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.request.urlparse(newurl).hostname or ""
        scheme = urllib.request.urlparse(newurl).scheme
        if scheme != "https" or not any(
                host == allowed or host.endswith("." + allowed)
                for allowed in ALLOWED_HOSTS):
            raise UpdateError(f"refusing a redirect to {host or newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    # Deliberately not http_pool: that reads whole responses into memory with
    # no size cap and no redirect policy, on the same connection pool the
    # hotkey path uses.
    return urllib.request.build_opener(_SameOriginRedirects)


def fetch_latest(etag="") -> dict:
    """Ask GitHub about the newest release.

    Returns ``{}`` when nothing changed since ``etag`` - unauthenticated calls
    are rate limited per IP, and a conditional request that answers 304 does
    not count against it.
    """
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    })
    if etag:
        request.add_header("If-None-Match", etag)
    try:
        with _opener().open(request, timeout=NETWORK_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
            body["_etag"] = response.headers.get("ETag", "")
            return body
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return {}
        if exc.code == 403 and "rate limit" in str(exc.headers).lower():
            raise UpdateError("GitHub rate limit reached; will try again later")
        raise UpdateError(f"GitHub answered {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}")
    except ValueError as exc:
        raise UpdateError(f"unreadable answer from GitHub: {exc}")


def pick_asset(release: dict) -> dict:
    """The installer asset out of a release, with its published checksum."""
    for asset in release.get("assets") or []:
        name = asset.get("name", "")
        if not name.lower().endswith(".exe"):
            continue
        if "setup" not in name.lower():
            continue
        if asset.get("state") != "uploaded":
            raise UpdateError(f"{name} is still uploading")
        return {
            "name": name,
            "url": asset.get("browser_download_url", ""),
            "size": int(asset.get("size") or 0),
            # GitHub publishes this as "sha256:<hex>".
            "sha256": (asset.get("digest") or "").split(":")[-1].lower(),
        }
    raise UpdateError("that release has no installer attached")


def check(force=False) -> dict:
    """Is there something newer? Returns {} when there is not.

    On success: ``{"version", "notes", "asset", "url"}``.
    """
    state = update_state.read()
    now = time.time()
    if not force and now - float(state.get("last_check_at") or 0) < CHECK_INTERVAL_SECONDS:
        return {}

    release = fetch_latest(etag="" if force else state.get("etag", ""))
    if not release:
        update_state.write(last_check_at=now, fail_count=0)
        return {}

    if release.get("draft") or release.get("prerelease"):
        update_state.write(last_check_at=now, etag=release.get("_etag", ""),
                           fail_count=0)
        return {}

    version = (release.get("tag_name") or "").lstrip("vV")
    update_state.write(last_check_at=now, etag=release.get("_etag", ""),
                       latest_seen=version, fail_count=0)

    if not is_newer(version):
        return {}
    if version == (state.get("skipped_version") or ""):
        return {}

    return {
        "version": version,
        "notes": release.get("body") or "",
        "url": release.get("html_url") or RELEASES_PAGE,
        "asset": pick_asset(release),
    }


def download(asset: dict, on_progress=None) -> str:
    """Fetch the installer and prove it is intact. Returns its path.

    The file is written as ``.part`` and only renamed once the hash matches, so
    a partial or altered download never sits somewhere it could be run.
    """
    url = asset.get("url") or ""
    if not url.startswith("https://"):
        raise UpdateError("the download link is not https")
    expected = (asset.get("sha256") or "").lower()
    if len(expected) != 64:
        raise UpdateError("that release published no checksum to verify against")

    directory = paths.user_data("updates")
    os.makedirs(directory, exist_ok=True)
    final = os.path.join(directory, asset["name"])
    partial = final + ".part"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/octet-stream"})
    digest = hashlib.sha256()
    written = 0
    total = int(asset.get("size") or 0)
    try:
        with _opener().open(request, timeout=NETWORK_TIMEOUT) as response, \
                open(partial, "wb") as handle:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("the download is implausibly large")
                digest.update(chunk)
                handle.write(chunk)
                if on_progress:
                    on_progress(written, total)
            handle.flush()
            os.fsync(handle.fileno())
    except UpdateError:
        _discard(partial)
        raise
    except (urllib.error.URLError, OSError) as exc:
        _discard(partial)
        raise UpdateError(f"the download failed: {exc}")

    if total and written != total:
        _discard(partial)
        raise UpdateError(f"expected {total} bytes, got {written}")
    if digest.hexdigest() != expected:
        _discard(partial)
        raise UpdateError("the downloaded file does not match its checksum")

    os.replace(partial, final)
    return final


def _discard(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# =====================================================================
# Handover
# =====================================================================
def install_command(installer: str, language="en", relaunch=True):
    """The command line that installs the update and brings the app back.

    ``/RELAUNCH=1`` drives a ``[Run]`` entry in the installer that deliberately
    does not carry ``skipifsilent`` - that flag would skip it in exactly the
    mode used here, and the app would install the update and never reappear.
    """
    command = [installer, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
               "/NOCANCEL", f"/LANG={_installer_language(language)}"]
    if relaunch:
        command.append("/RELAUNCH=1")
    return command


def _installer_language(app_language):
    """i18n codes to the wizard's language names."""
    return {"th": "th", "en": "en", "ja": "ja", "zh-CN": "zh"}.get(
        app_language, "en")


def can_self_install() -> bool:
    """Only the copy the installer put there can replace itself.

    Being frozen is not enough. A portable copy - the zip, or an install folder
    someone moved - is also frozen, but running the installer against it would
    silently install a *second* copy into %LOCALAPPDATA% and leave the one the
    user is actually running untouched and out of date. So this asks the
    installer's own registry entry where it put the app, and only agrees when
    that is where we are running from.
    """
    if not paths.FROZEN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\TypistTranslator") as key:
            recorded = winreg.QueryValueEx(key, "InstallPath")[0]
    except (OSError, ImportError):
        return False
    return os.path.normcase(os.path.abspath(recorded)) == os.path.normcase(
        os.path.abspath(paths.INSTALL_DIR))
