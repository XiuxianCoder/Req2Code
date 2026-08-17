from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

_lock = threading.Lock()


class ReplayGuard:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"nonces": {}}
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "nonces" not in data or not isinstance(data["nonces"], dict):
            data["nonces"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        # Atomic write: temp file + rename
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".replay_", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, str(self.path))
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def seen_or_add(self, nonce: str, now_ts: int, ttl_seconds: int) -> bool:
        """Thread-safe check-and-add. Returns True if nonce was already seen."""
        with _lock:
            data = self._load()
            nonces: dict[str, int] = {k: int(v) for k, v in data.get("nonces", {}).items()}

            # Cleanup expired nonces
            min_valid = now_ts - ttl_seconds
            nonces = {k: v for k, v in nonces.items() if v >= min_valid}

            if nonce in nonces:
                return True

            nonces[nonce] = now_ts
            data["nonces"] = nonces
            self._save(data)

        return False
