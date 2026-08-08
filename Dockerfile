# Ṣāni' Studio backend.
#
# ⚠️ Built but never run: this image has not been assembled, because the
# environment it was written in has the Docker client and no daemon. Treat the
# first `docker build` as the verification step.
#
# The agent in this container executes shell commands. Always run it with
# SANI_AUTH_TOKEN set.

FROM python:3.11-slim AS base

# git: the agent's shell tool is expected to run git commands.
# curl: the healthcheck below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first, so application edits do not re-resolve the world.
COPY pyproject.toml uv.lock ./
COPY packages/sani-core/pyproject.toml packages/sani-core/
COPY packages/sani-server/pyproject.toml packages/sani-server/

# --extra all is deliberate: without it a production image silently loses Redis
# support and falls back to line-window chunking. --no-dev keeps the test-only
# packages out.
RUN uv sync --locked --no-dev --extra all --no-install-project

COPY packages/ packages/
COPY scripts/ scripts/
RUN uv sync --locked --no-dev --extra all

# Run as a non-root user. This is not isolation -- the agent can still do
# anything this user can -- but it keeps a mistake away from the image root.
RUN useradd --create-home --uid 10001 sani \
 && mkdir -p /workspaces && chown -R sani:sani /workspaces /app
USER sani

# Confine every session workspace to one mountable directory.
ENV SANI_WORKSPACE_ROOT=/workspaces \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
VOLUME ["/workspaces"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# One worker, deliberately. A session's executor, sandbox and pending-approval
# futures live in the process that created it, so a second worker could read a
# session (with Redis) but never approve or steer it. Scale with Redis and
# separate instances behind a sticky proxy, not with --workers.
CMD ["uvicorn", "sani_server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
