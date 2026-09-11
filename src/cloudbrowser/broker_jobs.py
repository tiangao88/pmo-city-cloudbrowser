"""Opt-in, single-host whole-job exclusion; no credentials or expiring leases.

Both services must mount the SAME private local-filesystem directory. Never
replace/unlink its files while either service runs; NFS and forked/background
credential work are unsupported. Kernel locks, not request deadlines, establish
that a synchronous broker job has exited. This is not a distributed lock.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import uuid


class JobsUnavailable(PermissionError):
    pass


class BrokerJobs:
    def __init__(self, directory):
        self.directory = Path(directory)
        if not self.directory.is_absolute() or not self.directory.is_dir():
            raise ValueError("broker job directory must exist and be absolute")
        self._owner = None

    @contextmanager
    def _file(self, name, lock):
        fd = os.open(self.directory / name,
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            try:
                fcntl.flock(fd, lock | fcntl.LOCK_NB)
            except BlockingIOError:
                raise JobsUnavailable("broker jobs unavailable") from None
            yield fd
        finally:
            os.close(fd)

    def claim_authority(self):
        """One desktop authority; restart invalidates admission before serving."""
        if self._owner is not None:
            raise JobsUnavailable("authority already claimed")
        fd = os.open(self.directory / "authority", os.O_RDWR | os.O_CREAT |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        claimed = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            claimed = True
            self._owner = fd
            self.change("paused")
        except Exception:
            if claimed:
                self.close()
            else:
                os.close(fd)
            raise

    def close(self):
        if self._owner is not None:
            os.close(self._owner)
            self._owner = None

    def _alive(self):
        # A shared lock succeeds only when no desktop holds the exclusive lock.
        try:
            with self._file("authority", fcntl.LOCK_SH):
                pass
        except JobsUnavailable:
            return
        raise JobsUnavailable("desktop authority unavailable")

    @staticmethod
    def _read(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            state = json.loads(os.read(fd, 512))
            if (set(state) != {"mode", "epoch"} or
                    state["mode"] not in ("paused", "agent", "human") or
                    not isinstance(state["epoch"], str) or len(state["epoch"]) != 32):
                raise ValueError()
            return state
        except (ValueError, TypeError):
            raise JobsUnavailable("job state unavailable") from None

    def change(self, mode):
        if self._owner is None or mode not in ("paused", "agent", "human"):
            raise JobsUnavailable("job authority unavailable")
        paused_written = False
        try:
            with self._file("state", fcntl.LOCK_EX) as fd:
                # Always invalidate old admission first. A crash/partial write
                # is unreadable, never interpreted as an empty agent state.
                self._write(fd, "paused")
                paused_written = True
                if mode != "paused":
                    # Never wait holding the browser interaction lock: a broker
                    # may need a callback to exit. Caller retries explicitly.
                    with self._file("jobs", fcntl.LOCK_EX):
                        self._write(fd, mode)
        except JobsUnavailable:
            if not paused_written:
                self.close()
            raise
        except OSError:
            # Even a complete write can fail at fsync. Relinquish authority so
            # a readable but uncommitted 'agent' value cannot admit new work.
            self.close()
            raise

    @staticmethod
    def _write(fd, mode):
        value = json.dumps({"mode": mode, "epoch": uuid.uuid4().hex}).encode()
        os.lseek(fd, 0, os.SEEK_SET)
        if os.write(fd, value) != len(value):
            raise OSError("short job-state write")
        os.ftruncate(fd, len(value))
        os.fsync(fd)

    def snapshot(self):
        with self._file("state", fcntl.LOCK_SH) as fd:
            self._alive()
            state = self._read(fd)
            if state["mode"] != "agent":
                raise JobsUnavailable("browser control paused")
            return state["epoch"]

    @contextmanager
    def job(self, epoch):
        # Hold the job lock before checking admission; drop the admission lock
        # for the synchronous operation (including material cleanup). All lock
        # acquisition is nonblocking, so the opposite transition order is safe.
        with self._file("jobs", fcntl.LOCK_SH):
            with self._file("state", fcntl.LOCK_SH) as fd:
                self._alive()
                state = self._read(fd)
                if state["mode"] != "agent" or state["epoch"] != epoch:
                    raise JobsUnavailable("browser control changed")
            yield
