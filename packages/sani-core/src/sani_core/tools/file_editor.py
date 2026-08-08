"""File editor adapter: read, write, delete inside a workspace."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..actions import ProposedAction, ToolResult
from ..diffs import apply_hunks, compute_diff
from ..permissions import ActionType
from ..plan import PlanStep
from ..workspace import resolve_in_workspace
from .base import ToolAdapter, ToolError

#: Path patterns treated as credential material. Matched against the path
#: relative to the workspace, case-insensitively.
SECRET_PATTERNS = (
    r"(^|/)\.env($|\.|/)",
    r"(^|/)\.envrc$",
    r"(^|/)secrets?($|/|\.)",
    r"(^|/)credentials?($|/|\.)",
    r"(^|/)\.aws/",
    r"(^|/)\.ssh/",
    r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$",
    r"\.pem$",
    r"\.p12$",
    r"\.pfx$",
    r"\.keystore$",
    # Unanchored: real-world names are commonly prefixed, e.g.
    # "gcp-service_account.json" or "prod-service-account-key.json".
    r"service[-_]account.*\.json$",
)

_SECRET_RE = re.compile("|".join(SECRET_PATTERNS), re.IGNORECASE)

MAX_READ_BYTES = 512_000


def looks_like_secret(relpath: str) -> bool:
    return bool(_SECRET_RE.search(relpath.replace("\\", "/")))


class FileEditorTool(ToolAdapter):
    name = "file_editor"

    def propose(self, step: PlanStep) -> ProposedAction:
        op = step.params.get("op", "read")
        raw_path = step.params.get("path")
        if not raw_path:
            raise ToolError(f"step {step.index}: file_editor requires a 'path' param")

        resolved = resolve_in_workspace(self.workspace, raw_path)
        target, outside, relpath = resolved.path, resolved.escaped, resolved.relpath

        if outside:
            action_type = ActionType.PATH_OUTSIDE_WORKSPACE
        elif looks_like_secret(relpath):
            # Spec Section 5 names writes to secrets. Reads are gated too:
            # sending a credential file into an LLM's context is exactly as
            # irreversible as writing one, and cheaper to do by accident.
            action_type = ActionType.SECRET_ACCESS
        elif op == "delete":
            action_type = ActionType.FILE_DELETE
        elif op == "write":
            action_type = ActionType.FILE_WRITE
        else:
            action_type = ActionType.FILE_READ

        payload: dict[str, Any] = {"op": op, "path": str(target), "relpath": relpath}
        preview: dict[str, Any] = {"op": op, "path": relpath, "resolved": str(target)}
        diff = None

        if op == "write":
            new_text = step.params.get("content", "")
            old_text = self._read_if_exists(target)
            payload["old_text"] = old_text
            payload["new_text"] = new_text
            diff = compute_diff(relpath, old_text, new_text)
            preview["hunks"] = len(diff.hunks)
        elif op == "delete":
            old_text = self._read_if_exists(target)
            payload["old_text"] = old_text
            diff = compute_diff(relpath, old_text, "", is_delete=True)
            preview["exists"] = target.exists()
            preview["bytes"] = len(old_text.encode())

        summary = {
            "read": f"Read {relpath}",
            "write": f"Write {relpath}",
            "delete": f"Delete {relpath}",
        }.get(op, f"{op} {relpath}")

        return ProposedAction(
            action_type=action_type,
            tool=self.name,
            summary=summary,
            step_index=step.index,
            payload=payload,
            preview=preview,
            diff=diff,
        )

    @staticmethod
    def _read_if_exists(path: Path) -> str:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    async def execute(self, action: ProposedAction, *, hunk_ids: list[str] | None = None) -> Any:
        op = action.payload["op"]
        target = Path(action.payload["path"])

        if op == "read":
            if not target.is_file():
                raise ToolError(f"{action.payload['relpath']} does not exist")
            data = target.read_bytes()[:MAX_READ_BYTES]
            return {"content": data.decode("utf-8", errors="replace")}

        if op == "write":
            old_text = action.payload["old_text"]
            new_text = action.payload["new_text"]
            applied = apply_hunks(old_text, new_text, hunk_ids)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(applied, encoding="utf-8")
            # Re-diff against what was actually written, so a partial hunk
            # accept is reflected honestly in the session's diff view.
            return {
                "written": True,
                "diff": compute_diff(action.payload["relpath"], old_text, applied),
                "partial": hunk_ids is not None,
            }

        if op == "delete":
            existed = target.is_file()
            if existed:
                target.unlink()
            return {"deleted": existed, "diff": action.diff}

        raise ToolError(f"unsupported file_editor op: {op}")

    def result(self, action: ProposedAction, raw: Any) -> ToolResult:
        op = action.payload["op"]
        relpath = action.payload["relpath"]

        if op == "read":
            content = raw["content"]
            return ToolResult(
                ok=True,
                summary=f"Read {relpath} ({len(content)} chars)",
                output=content,
                data={"path": relpath, "chars": len(content)},
            )

        if op == "write":
            diff = raw["diff"]
            suffix = " (partial: selected hunks only)" if raw["partial"] else ""
            return ToolResult(
                ok=True,
                summary=f"Wrote {relpath}{suffix}",
                data={"path": relpath, "hunks": len(diff.hunks)},
                diff=diff,
            )

        return ToolResult(
            ok=True,
            summary=f"Deleted {relpath}" if raw["deleted"] else f"{relpath} was already absent",
            data={"path": relpath, "deleted": raw["deleted"]},
            diff=raw["diff"],
        )
