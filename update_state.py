"""
What the updater remembers between runs.

Kept in its own file rather than inside ``config.json`` on purpose: this record
is written by background threads and rewritten across an application restart,
and a corrupt update record must never be able to take the user's API keys down
with it.

Anything unreadable reads back as an empty record. A broken state file is a
reason to check for updates again, never a reason to fail to start.
"""
import json
import os
import threading

import paths

STATE_NAME = "update_state.json"

_lock = threading.Lock()

#: The record's shape, and the defaults for a first run.
DEFAULTS = {
    "last_check_at": 0.0,      # epoch seconds of the last successful check
    "etag": "",                # so a repeat check costs no rate-limit quota
    "latest_seen": "",         # newest version the server has offered
    "skipped_version": "",     # user pressed "later" on this one
    "pending_version": "",     # downloaded and verified, waiting to be installed
    "pending_installer": "",   # the verified file on disk
    "pending_notes": "",       # release notes, for the What's New panel
    "launched_version": "",    # what was running last time, to detect an update
    "fail_count": 0,           # consecutive failures, to back off
}


def path() -> str:
    return paths.user_data(STATE_NAME)


def read() -> dict:
    """The stored record, merged over the defaults. Never raises."""
    state = dict(DEFAULTS)
    try:
        with open(path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            state.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return state


def write(**changes) -> dict:
    """Merge ``changes`` into the record and store it atomically."""
    with _lock:
        state = read()
        state.update({k: v for k, v in changes.items() if k in DEFAULTS})
        target = path()
        temporary = target + ".tmp"
        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            print(f"[UpdateState] Could not save: {exc}")
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return state


def clear_pending():
    """Forget a downloaded update, and delete the file it points at."""
    state = read()
    installer = state.get("pending_installer") or ""
    if installer and os.path.exists(installer):
        try:
            os.remove(installer)
        except OSError:
            pass
    write(pending_version="", pending_installer="")
