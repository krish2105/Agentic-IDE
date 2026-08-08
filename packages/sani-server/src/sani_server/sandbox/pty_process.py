"""PTY plumbing shared by both sandboxes.

The Docker sandbox is `docker exec` attached to a local PTY, so the terminal
mechanics are identical either way and only the argv differs.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios

from .base import SandboxError, TerminalSession

READ_CHUNK = 65536

#: How long to wait for a hung-up shell before killing its group.
CLOSE_GRACE_S = 0.5


class PtyTerminal(TerminalSession):
    def __init__(self, master_fd: int, process: asyncio.subprocess.Process) -> None:
        self._fd = master_fd
        self._process = process
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._teardown_started = False

        os.set_blocking(master_fd, False)
        self._loop.add_reader(master_fd, self._on_readable)

    def _on_readable(self) -> None:
        try:
            data = os.read(self._fd, READ_CHUNK)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            # EIO on Linux means the child closed the slave side and exited.
            data = b""

        if not data:
            self._detach()
            self._queue.put_nowait(b"")
            return
        self._queue.put_nowait(data)

    def _detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.remove_reader(self._fd)
        except (OSError, ValueError):
            pass

    async def read(self) -> bytes:
        return await self._queue.get()

    async def write(self, data: bytes) -> None:
        if self._closed:
            return
        try:
            os.write(self._fd, data)
        except OSError as exc:
            raise SandboxError(f"terminal write failed: {exc}") from exc

    def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        try:
            fcntl.ioctl(
                self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
            )
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        return not self._closed and self._process.returncode is None

    def _signal_group(self, sig: int) -> None:
        """Signal the child's whole process group.

        Signalling just the child would miss anything it spawned, and `setsid`
        can leave the shell as a grandchild -- an orphan holding the workspace
        open after the socket is long gone.
        """
        try:
            os.killpg(os.getpgid(self._process.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def close(self) -> None:
        """Tear down synchronously. Deliberately not a coroutine.

        This runs in the WebSocket handler's ``finally``, and the client cancels
        the app's task scope immediately after sending its disconnect. Anything
        awaited here can be interrupted part-way through and escape as a
        cancelled task instead of a clean close -- which is exactly the
        intermittent failure this replaced.

        So: close the fd, signal the group, and schedule the hard kill on the
        loop rather than waiting for it. The child watcher reaps the process
        whenever it actually exits.
        """
        if self._teardown_started:
            return
        self._teardown_started = True

        self._detach()
        # Closing the master first hangs up the child's tty, so it usually
        # exits on its own before the signal is even needed.
        try:
            os.close(self._fd)
        except OSError:
            pass

        if self._process.returncode is None:
            self._signal_group(signal.SIGHUP)
            self._loop.call_later(CLOSE_GRACE_S, self._force_kill)

    def _force_kill(self) -> None:
        if self._process.returncode is None:
            self._signal_group(signal.SIGKILL)


#: `setsid --ctty` does setsid + TIOCSCTTY in the child for us. Doing that via a
#: `preexec_fn` instead would run Python between fork and exec, which is
#: documented as unsafe once threads exist -- and asyncio's child watcher
#: creates them.
SETSID = "/usr/bin/setsid"


def spawn_plan(argv: list[str]) -> tuple[list[str], bool]:
    """Return the argv to exec and whether to ask Python for a new session.

    The two are mutually exclusive and the reason is subtle: `setsid` forks
    instead of exec'ing when its child is *already* a session leader. Passing
    ``start_new_session=True`` alongside it would therefore leave the shell as
    an orphaned grandchild that the tracked process object does not represent.

    Exactly one of them must always apply, because ``close()`` signals the
    child's process group -- and a child still sitting in the server's own
    group would mean signalling the server.
    """
    if os.path.exists(SETSID):
        return [SETSID, "--ctty", *argv], False
    # No setsid binary: settle for an isolated session without a controlling
    # terminal. The shell loses job control but the group stays safe to signal.
    return argv, True


async def spawn_pty(
    argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None,
    cols: int = 80, rows: int = 24,
) -> PtyTerminal:
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    exec_argv, new_session = spawn_plan(argv)
    try:
        process = await asyncio.create_subprocess_exec(
            *exec_argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=env,
            start_new_session=new_session,
        )
    except (OSError, ValueError) as exc:
        os.close(master_fd)
        os.close(slave_fd)
        raise SandboxError(f"could not start {argv[0]}: {exc}") from exc
    finally:
        # The parent must drop its copy or the master never sees EOF.
        try:
            os.close(slave_fd)
        except OSError:
            pass

    return PtyTerminal(master_fd, process)
