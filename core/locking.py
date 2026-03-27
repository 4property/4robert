from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _normalise_lock_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "_"
        for character in value.strip()
    ) or "value"


def property_job_lock_path(workspace_dir: str | Path, *, site_id: str, property_id: int | None) -> Path:
    base_dir = Path(workspace_dir).expanduser().resolve()
    safe_site_id = _normalise_lock_name(site_id)
    safe_property_id = "unknown" if property_id is None else str(property_id)
    return base_dir / ".runtime_locks" / safe_site_id / f"{safe_property_id}.lock"


@contextmanager
def exclusive_file_lock(lock_path: str | Path):
    resolved_lock_path = Path(lock_path).expanduser().resolve()
    resolved_lock_path.parent.mkdir(parents=True, exist_ok=True)

    with resolved_lock_path.open("a+b") as lock_handle:
        lock_handle.seek(0)
        if lock_handle.tell() == 0:
            lock_handle.write(b"0")
            lock_handle.flush()
        lock_handle.seek(0)

        _acquire_lock(lock_handle)
        try:
            yield resolved_lock_path
        finally:
            _release_lock(lock_handle)


def _acquire_lock(lock_handle) -> None:
    if os.name == "nt":
        while True:
            try:
                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    else:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)


def _release_lock(lock_handle) -> None:
    if os.name == "nt":
        lock_handle.seek(0)
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "exclusive_file_lock",
    "property_job_lock_path",
]
