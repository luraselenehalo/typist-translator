"""
Translation History Store

In the Tk build the history lived inside the window, so it was lost whenever
the UI was rebuilt and could only be written from the main thread. Here it is
plain data owned by the backend: the hotkey worker appends from its own thread,
the UI reads it over the bridge, and it survives anything the front end does.
"""
import itertools
import threading
import time

MAX_ENTRIES = 200


class HistoryStore:
    # pywebview walks public attributes of the js_api object to build the JS
    # bridge; this keeps the store (and its mutating methods) off that surface.
    _serializable = False

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries = []
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._max = max_entries

    def add(self, original, translated, source_lang, target_lang):
        """Append an entry and return it (newest first ordering on read)."""
        entry = {
            "id": next(self._ids),
            "original": original,
            "translated": translated,
            "source": source_lang,
            "target": target_lang,
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max:
                del self._entries[:-self._max]
        return entry

    def list(self):
        """Newest first."""
        with self._lock:
            return list(reversed(self._entries))

    def delete(self, entry_id):
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            return len(self._entries) != before

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        with self._lock:
            return len(self._entries)
