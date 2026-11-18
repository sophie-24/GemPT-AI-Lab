"""Filesystem storage for uploaded image bytes referenced by graph state."""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path


DEFAULT_UPLOAD_DIR = "/data/uploads"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_REF_PREFIX = "gempt-upload://"


def upload_dir() -> Path:
    return Path(os.environ.get("UPLOAD_DIR", DEFAULT_UPLOAD_DIR))


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, numbers, '_' or '-' (max 128 chars)")
    return run_id


def _path_for_run(run_id: str, root: Path | None = None) -> Path:
    safe_id = _validate_run_id(run_id)
    return (root or upload_dir()) / f"{safe_id}.image"


def save_image(run_id: str, image_bytes: bytes) -> str:
    """Atomically save bytes and return an opaque ref suitable for graph state."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("image_bytes must be non-empty bytes")
    target = _path_for_run(run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}.", delete=False) as tmp:
            temp_name = tmp.name
            tmp.write(image_bytes)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return f"{_REF_PREFIX}{run_id}"


def open_image(image_ref: str) -> bytes:
    """Load image bytes by an opaque ref previously returned by save_image."""
    if not isinstance(image_ref, str) or not image_ref.startswith(_REF_PREFIX):
        raise ValueError("unsupported image_ref")
    run_id = image_ref[len(_REF_PREFIX):]
    return _path_for_run(run_id).read_bytes()


def delete_image(run_id: str) -> bool:
    """Delete a run's upload. Return False when no file existed."""
    target = _path_for_run(run_id)
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False


def cleanup_expired(ttl_seconds: int, *, now: float | None = None) -> int:
    """Remove old ``*.image`` files and return the number removed.

    Only files directly inside UPLOAD_DIR with the generated suffix are
    considered. Call periodically from a maintenance task, not per request.
    """
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be non-negative")
    root = upload_dir()
    if not root.exists():
        return 0
    cutoff = (time.time() if now is None else now) - ttl_seconds
    removed = 0
    for path in root.glob("*.image"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed
