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


class PtyTerminal(TerminalSession):
    def __init__(self, master_fd: int, process: asyncio.subprocess.Process) -> None:
        self._fd = master_fd
        self._process = process
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        self._closed = False

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

    async def close(self) -> None:
        self._detach()
        if self._process.returncode is None:
            try:
                self._process.send_signal(signal.SIGHUP)
                await asyncio.wait_for(self._process.wait(), timeout=3)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
        try:
            os.close(self._fd)
        except OSError:
            pass


async def spawn_pty(
    argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None,
    cols: int = 80, rows: int = 24,
) -> PtyTerminal:
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _become_session_leader() -> None:
        # setsid plus TIOCSCTTY makes the PTY the controlling terminal, which is
        # what gives the shell working job control rather than a bare pipe.
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=env,
            preexec_fn=_become_session_leader,
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
