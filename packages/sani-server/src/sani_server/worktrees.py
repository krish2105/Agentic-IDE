"""Git worktrees: isolated copies of one repo, for racing agents in parallel.

A race runs N agents at the same task and lets you keep the best answer. That
only works if they cannot see each other's edits, and `git worktree` gives
exactly that -- N working directories over one object store, cheap to create and
cheap to throw away.

The alternative, copying the tree, costs disk proportional to the repo and
loses the git history the agent needs to work sensibly. The cost is a hard
requirement: **the workspace must be a git repository**, and that is reported
plainly rather than silently degrading to something that looks like it worked.

Worktrees are created under a temp root, never inside the repo, so a failed
cleanup cannot leave junk in the user's project.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    pass


async def _git(*args: str, cwd: Path, timeout: int = 30) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        raise WorktreeError(f"git {args[0]} timed out") from exc
    return process.returncode or 0, stdout.decode("utf-8", errors="replace").strip()


async def is_git_repo(path: Path) -> bool:
    if not shutil.which("git"):
        return False
    code, output = await _git("rev-parse", "--is-inside-work-tree", cwd=path)
    return code == 0 and output.strip() == "true"


@dataclass(slots=True)
class Worktree:
    path: Path
    branch: str
    source: Path


class WorktreePool:
    """Worktrees created for one race, and the cleanup that removes them."""

    def __init__(self, source: Path) -> None:
        self.source = Path(source).resolve()
        self._root = Path(tempfile.mkdtemp(prefix="sani-race-"))
        self._worktrees: list[Worktree] = []

    @property
    def worktrees(self) -> list[Worktree]:
        return list(self._worktrees)

    async def add(self, label: str) -> Worktree:
        """One isolated checkout, on its own branch."""
        if not await is_git_repo(self.source):
            raise WorktreeError(
                f"{self.source} is not a git repository — a race needs one so each "
                "agent gets an isolated worktree"
            )

        suffix = uuid.uuid4().hex[:6]
        branch = f"sani/race-{label}-{suffix}"
        path = self._root / f"{label}-{suffix}"

        code, output = await _git(
            "worktree", "add", "--detach", "-b", branch, str(path), cwd=self.source
        )
        if code != 0:
            # `--detach` with `-b` is rejected by older gits; retry without it
            # rather than failing a race over a flag.
            code, output = await _git(
                "worktree", "add", "-b", branch, str(path), cwd=self.source
            )
        if code != 0:
            raise WorktreeError(f"could not create worktree: {output}")

        worktree = Worktree(path=path, branch=branch, source=self.source)
        self._worktrees.append(worktree)
        return worktree

    async def remove(self, worktree: Worktree) -> None:
        """Drop one worktree and its branch. Best-effort, like cleanup()."""
        try:
            await _git("worktree", "remove", "--force", str(worktree.path), cwd=self.source)
        except Exception:
            pass
        try:
            await _git("branch", "-D", worktree.branch, cwd=self.source)
        except Exception:
            pass
        self._worktrees = [w for w in self._worktrees if w.path != worktree.path]

    async def cleanup(self) -> None:
        """Remove every worktree and branch this pool created.

        Best-effort by design: a leaked temp directory is annoying, a raised
        exception during teardown loses the race results the user was about to
        read.
        """
        for worktree in self._worktrees:
            try:
                await _git("worktree", "remove", "--force", str(worktree.path), cwd=self.source)
            except Exception:
                pass
            try:
                await _git("branch", "-D", worktree.branch, cwd=self.source)
            except Exception:
                pass

        self._worktrees.clear()
        shutil.rmtree(self._root, ignore_errors=True)
