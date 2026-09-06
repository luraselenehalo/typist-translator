"""
Config guard for tests.

The test suites drive the real application, which persists to the real
config.json. This snapshots that file and puts it back afterwards, so running
tests can never quietly change the user's hotkey, language pair or theme.

    with ConfigGuard() as guard:
        ...run whatever mutates config.json...
    assert guard.unchanged()      # the file is byte-identical again

`unchanged()` is answerable after the block exits because the snapshot is held
in memory, not in a temporary file.
"""
import os

from config_manager import CONFIG_FILE as CONFIG_PATH


class ConfigGuard:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self._snapshot = None
        self._existed = False
        self._modified_during_run = False

    def __enter__(self):
        self._existed = os.path.exists(self.path)
        if self._existed:
            with open(self.path, "rb") as handle:
                self._snapshot = handle.read()
        return self

    def __exit__(self, *exc_info):
        if not self._existed:
            if os.path.exists(self.path):
                self._modified_during_run = True
                os.remove(self.path)
            return False

        try:
            with open(self.path, "rb") as handle:
                current = handle.read()
        except OSError:
            current = None

        if current != self._snapshot:
            self._modified_during_run = True
            with open(self.path, "wb") as handle:
                handle.write(self._snapshot)
        return False

    @property
    def was_modified(self) -> bool:
        """True when the run changed the file before it was restored."""
        return self._modified_during_run

    def unchanged(self) -> bool:
        """True when the live file now matches the snapshot taken on entry."""
        if not self._existed:
            return not os.path.exists(self.path)
        try:
            with open(self.path, "rb") as handle:
                return handle.read() == self._snapshot
        except OSError:
            return False
