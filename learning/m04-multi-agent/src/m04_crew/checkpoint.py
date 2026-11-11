"""Checkpointers: where LangGraph saves state after every step (a "super-step").

- `memory`              in-process; lost when the process exits (tests, notebooks)
- `path/to/file.db`     SQLite; survives a crash on one machine (default: ~/.m04/checkpoints.db)
- `postgresql://...`    Postgres; shared by many workers/pods, the production choice (lab: localhost:55432)"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path.home() / ".m04" / "checkpoints.db"


@contextmanager
def open_checkpointer(url: str | None = None) -> Iterator:
    url = url or str(DEFAULT_DB)
    if url == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
    elif url.startswith(("postgres://", "postgresql://")):
        from langgraph.checkpoint.postgres import PostgresSaver  # pip install -e ".[postgres]"

        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()  # creates the checkpoint tables once
            yield saver
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        Path(url).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(url, check_same_thread=False)
        try:
            yield SqliteSaver(conn)
        finally:
            conn.close()
