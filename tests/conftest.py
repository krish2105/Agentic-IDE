from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sani_server.app import create_app
from sani_server.manager import SessionManager


@pytest.fixture
def workspace(tmp_path):
    """A throwaway repo the agent is allowed to touch."""
    (tmp_path / "README.md").write_text("# Demo project\n\nNothing here yet.\n")
    (tmp_path / "scratch.tmp").write_text("left over from a previous run\n")
    return tmp_path


@pytest.fixture
def manager():
    return SessionManager()


@pytest.fixture
def client(manager):
    """A TestClient held open as a context manager.

    This matters: entering the context starts one blocking portal that persists
    across requests, so the detached executor task created by POST /session
    survives into the next call. Without the ``with``, each request would get a
    fresh event loop and every session would die the moment it was created.
    """
    app = create_app(manager)
    with TestClient(app) as test_client:
        yield test_client
