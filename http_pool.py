"""
HTTP Connection Pool

Every translation used to go through urllib.request.urlopen, which opens a
fresh TCP connection and performs a full TLS handshake per call. On a typical
connection that handshake is 150-350 ms - often more than the translation
itself. This module keeps keep-alive connections per host so the second and
later requests skip both, which is exactly the pattern this app has: the same
endpoint hit over and over as the user presses the hotkey.

Thread-safe: the hotkey workflow and the GUI sandbox both translate from
background threads.
"""
import json
import threading
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# A keep-alive socket that has been idle longer than this is assumed dead.
IDLE_TTL_SECONDS = 45.0
MAX_IDLE_PER_HOST = 2


class HttpError(Exception):
    """Raised for HTTP status codes >= 400, carrying the response body."""

    def __init__(self, status, reason, body):
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(f"HTTP {status} {reason}: {body[:200]}")


class _ConnectionPool:
    def __init__(self):
        self._idle = {}
        self._lock = threading.Lock()

    def _key(self, parts):
        return (parts.scheme, parts.hostname, parts.port)

    def _acquire(self, key, timeout):
        scheme, host, port = key
        now = time.monotonic()
        with self._lock:
            bucket = self._idle.get(key) or []
            while bucket:
                conn, stored_at = bucket.pop()
                if now - stored_at < IDLE_TTL_SECONDS:
                    self._idle[key] = bucket
                    try:
                        if conn.sock is not None:
                            conn.sock.settimeout(timeout)
                    except Exception:
                        pass
                    return conn, True
                _close(conn)
            self._idle[key] = []

        factory = HTTPSConnection if scheme == "https" else HTTPConnection
        return factory(host, port, timeout=timeout), False

    def _release(self, key, conn):
        with self._lock:
            bucket = self._idle.setdefault(key, [])
            if len(bucket) >= MAX_IDLE_PER_HOST:
                _close(conn)
                return
            bucket.append((conn, time.monotonic()))

    def request(self, method, url, body=None, headers=None, timeout=10):
        """Perform a request, returning (status, reason, body_bytes)."""
        parts = urlsplit(url)
        key = self._key(parts)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"

        request_headers = {"User-Agent": DEFAULT_USER_AGENT,
                           "Accept": "*/*",
                           "Connection": "keep-alive"}
        if headers:
            request_headers.update(headers)

        last_error = None
        # Two attempts: a pooled socket may have been closed by the server
        # between requests. A freshly opened connection is never retried, so a
        # request that actually reached the server is not repeated.
        for _ in range(2):
            conn, reused = self._acquire(key, timeout)
            try:
                conn.request(method, path, body=body, headers=request_headers)
                response = conn.getresponse()
                payload = response.read()
                status, reason = response.status, response.reason

                if response.will_close or status >= 500:
                    _close(conn)
                else:
                    self._release(key, conn)
                return status, reason, payload
            except Exception as exc:
                _close(conn)
                last_error = exc
                if not reused:
                    raise
        raise last_error

    def close_all(self):
        with self._lock:
            for bucket in self._idle.values():
                for conn, _ in bucket:
                    _close(conn)
            self._idle.clear()


def _close(conn):
    try:
        conn.close()
    except Exception:
        pass


_POOL = _ConnectionPool()


def fetch_json(url, method="GET", payload=None, headers=None, timeout=10):
    """Request a URL over a pooled connection and decode the JSON response."""
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
        request_headers["Content-Length"] = str(len(body))

    status, reason, raw = _POOL.request(method, url, body=body,
                                        headers=request_headers, timeout=timeout)
    text = raw.decode("utf-8", errors="replace")
    if status >= 400:
        raise HttpError(status, reason, text)
    return json.loads(text)


def close_all():
    _POOL.close_all()
