"""Very small feature-flag engine.

Resolution order for a flag (first match wins):
1. Runtime override set through the admin API (``set_runtime``)
2. Environment variable ``FF_<FLAG_NAME>`` (true/false, on/off, 1/0)
3. ``config/flags.json`` (hot-reloaded when the file changes)

Flags in the JSON file can define ``rollout_percentage`` for a gradual
(canary style) rollout. Users are bucketed deterministically with SHA-256 so
the same user always gets the same experience.
"""

import hashlib
import json
import os
import threading

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class FeatureFlags:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._flags = {}
        self._runtime = {}
        self._mtime = None
        self.reload()

    # ------------------------------------------------------------------ #
    def reload(self):
        """Reload the flag file if it changed on disk."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return  # keep the last good configuration
        with self._lock:
            self._flags = data.get("flags", {})
            self._mtime = mtime

    def names(self):
        self.reload()
        with self._lock:
            return sorted(self._flags)

    def set_runtime(self, name, enabled):
        with self._lock:
            self._runtime[name] = bool(enabled)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _env_override(name):
        raw = os.getenv(f"FF_{name.upper()}")
        if raw is None:
            return None
        value = raw.strip().lower()
        if value in TRUE_VALUES:
            return True
        if value in FALSE_VALUES:
            return False
        return None

    def _override(self, name):
        with self._lock:
            if name in self._runtime:
                return self._runtime[name]
        return self._env_override(name)

    def _config(self, name):
        with self._lock:
            return dict(self._flags.get(name, {}))

    @staticmethod
    def bucket(name, user_id):
        digest = hashlib.sha256(f"{name}:{user_id}".encode("utf-8")).hexdigest()
        return int(digest, 16) % 100

    def is_enabled(self, name, user_id=None):
        self.reload()
        override = self._override(name)
        if override is not None:
            return override

        flag = self._config(name)
        if not flag.get("enabled", False):
            return False
        rollout = int(flag.get("rollout_percentage", 100))
        if rollout >= 100:
            return True
        if rollout <= 0 or user_id is None:
            return False
        return self.bucket(name, user_id) < rollout

    def all(self, user_id=None):
        result = {}
        for name in self.names():
            flag = self._config(name)
            result[name] = {
                "enabled": self.is_enabled(name, user_id),
                "description": flag.get("description", ""),
                "rollout_percentage": int(flag.get("rollout_percentage", 100)),
            }
        return result

    def summary(self):
        """Global (user independent) state, exported as Prometheus metrics."""
        result = {}
        for name in self.names():
            flag = self._config(name)
            override = self._override(name)
            enabled = override if override is not None else bool(flag.get("enabled", False))
            rollout = 100 if override is not None else int(flag.get("rollout_percentage", 100))
            result[name] = {"enabled": enabled, "rollout_percentage": rollout}
        return result
