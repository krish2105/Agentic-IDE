#!/usr/bin/env python
"""Manual stream viewer for a running Sani' Studio server.

The test suite drives the app in-process; this drives it over a real socket,
which is the only way to catch transport-level problems the ASGI test client
papers over.

    uv run uvicorn sani_server.app:app --port 8000
    uv run python scripts/ws_client.py --workspace /tmp/demo --approve-all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.error
import urllib.request

import websockets

COLORS = {
    "session.status": "\033[36m",
    "plan.proposed": "\033[35m",
    "approval.required": "\033[33m",
    "approval.resolved": "\033[32m",
    "diff.generated": "\033[34m",
    "session.error": "\033[31m",
    "session.complete": "\033[32m",
}
RESET = "\033[0m"


def post(url: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{url} -> {exc.code}: {exc.read().decode()}") from exc


def render(event: dict) -> None:
    event_type = event["type"]
    data = event["data"]
    color = COLORS.get(event_type, "")

    if event_type == "agent.message.delta":
        print(data["text"], end="", flush=True)
        return
    if event_type == "agent.message.done":
        print()
        return

    detail = ""
    if event_type == "session.status":
        detail = data["status"]
    elif event_type == "plan.proposed":
        steps = data["plan"]["steps"]
        detail = f"{len(steps)} steps"
        for step in steps:
            detail += f"\n         {step['index']}. [{step['tool']}] {step['description']}"
    elif event_type == "tool.proposed":
        detail = f"{data['action']['action_type']} :: {data['action']['summary']}"
    elif event_type == "approval.required":
        detail = f"{data['action']['summary']} ({data['decision']['reason']})"
    elif event_type == "approval.resolved":
        detail = "auto" if data.get("auto") else ("approved" if data["approved"] else "rejected")
    elif event_type == "tool.result":
        detail = data["result"]["summary"]
    elif event_type == "diff.generated":
        detail = f"{data['diff']['path']} ({len(data['diff']['hunks'])} hunks)"
    elif event_type == "context.usage":
        detail = f"{data['used_tokens']} tok ({data['pct']:.1%}) via {data['model']}"
    elif event_type in ("session.complete", "session.error"):
        detail = data.get("error") or data["status"]

    print(f"{color}[{event['seq']:>3}] {event_type:<22}{RESET} {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1:8000")
    parser.add_argument("--task", default="demo run")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--backend", default=None, choices=["scripted", "litellm"])
    parser.add_argument("--approve-all", action="store_true",
                        help="Approve every gated action instead of prompting.")
    args = parser.parse_args()

    body = {"task": args.task}
    if args.workspace:
        body["workspace"] = args.workspace
    if args.backend:
        body["model_backend"] = args.backend

    session = post(f"http://{args.host}/session", body)
    session_id = session["session_id"]
    print(f"session {session_id} in {session['workspace']}\n")

    async with websockets.connect(f"ws://{args.host}/session/{session_id}/stream") as ws:
        async for raw in ws:
            event = json.loads(raw)
            render(event)

            if event["type"] == "approval.required":
                action_id = event["data"]["action"]["id"]
                if args.approve_all:
                    decision = True
                else:
                    answer = await asyncio.to_thread(input, "         approve? [y/N] ")
                    decision = answer.strip().lower().startswith("y")
                endpoint = "approve" if decision else "reject"
                post(f"http://{args.host}/session/{session_id}/{endpoint}",
                     {"action_id": action_id})


if __name__ == "__main__":
    asyncio.run(main())
