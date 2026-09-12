"""Non-blocking process locks for workflows sharing one local SQLite database.

The operating system releases the lock on process exit, including crashes.
Lock files must never be unlinked while the database is in use.
"""

import errno
import os
from contextlib import contextmanager
from pathlib import Path

from app.core.errors import ApplicationError


@contextmanager
def diagnosis_lock(directory: Path, project_id: int, run_id: int):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{int(project_id)}-{int(run_id)}.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise ApplicationError(
                "DIAGNOSIS_ALREADY_RUNNING",
                "A diagnosis for this run is already executing. Refresh its saved status.",
                409,
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
