"""SQLite checkpointer lifecycle helpers for synchronous LangGraph runs.

Each API run should open its own saver/connection and close it after
``graph.invoke``. ``thread_id`` is the run ID; project score IDs are unrelated.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CHECKPOINT_DB = "/data/langgraph.sqlite"


def checkpoint_db_path() -> Path:
    """Return the configured checkpoint database path."""
    return Path(os.environ.get("LANGGRAPH_CHECKPOINT_DB", DEFAULT_CHECKPOINT_DB))


@dataclass
class CheckpointHandle:
    """A synchronous saver and the SQLite connection whose lifetime it owns."""

    checkpointer: Any
    connection: sqlite3.Connection

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CheckpointHandle":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def open_checkpointer(db_path: str | os.PathLike[str] | None = None) -> CheckpointHandle:
    """Create and initialize one synchronous SQLite checkpointer.

    Import is deferred so API code that does not enable graph persistence can
    still import this module without LangGraph checkpoint packages installed.
    The caller must close the returned handle, preferably with ``with``.
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError(
            "SQLite checkpoint support requires langgraph-checkpoint-sqlite"
        ) from exc

    path = Path(db_path) if db_path is not None else checkpoint_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(path),
        timeout=30.0,
        check_same_thread=False,
    )
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        checkpointer = SqliteSaver(connection)
        checkpointer.setup()
        return CheckpointHandle(checkpointer=checkpointer, connection=connection)
    except Exception:
        connection.close()
        raise


def close_checkpointer(handle: CheckpointHandle) -> None:
    """Explicit close API for callers that do not use the context manager."""
    handle.close()


def checkpoint_config(run_id: str) -> dict[str, dict[str, str]]:
    """Build LangGraph config with an isolated thread ID for one run."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    return {"configurable": {"thread_id": run_id}}
