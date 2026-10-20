"""Single motion-source lock so Nav2 and a teleop node cannot both command G1."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


class MotionLockError(RuntimeError):
    pass


@dataclass
class MotionLock:
    owner: str
    path: Path
    _handle: Optional[object] = None

    @classmethod
    def acquire(cls, owner: str, path: Optional[Union[str, Path]] = None) -> "MotionLock":
        lock_path = Path(path) if path else Path(tempfile.gettempdir()) / "gdps_g1_motion.lock"
        flags = os.O_CREAT | os.O_RDWR
        if os.name == "nt":
            fd = os.open(str(lock_path), flags)
            handle = os.fdopen(fd, "r+")
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(" ")
                handle.flush()
            handle.seek(0)
            try:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                handle.close()
                raise MotionLockError(f"another motion source holds {lock_path}") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise MotionLockError(f"another motion source holds {lock_path}") from exc
        payload = {"owner": owner, "pid": os.getpid(), "acquired_unix": time.time()}
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(payload))
        handle.flush()
        return cls(owner=owner, path=lock_path, _handle=handle)

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
