"""Opt-out, read-only update checker.

Compares the installed package version with the latest GitHub release (or tag)
of the public repository. It never installs anything: it only reports the
current and latest versions, the release notes link and the update command.

* Public GitHub API, no credentials, short timeout.
* Results are cached for 24 hours in a small JSON file.
* Every fetch attempt is recorded. After a failed fetch no new fetch is made for
  30 minutes, and ``force=True`` is honoured at most once a minute.
* Any network or parsing failure degrades to ``status="unknown"``.
* Only plain version tags (``v1.2.3``) are accepted; anything else counts as no release.
* ``ROISTAT_DISABLE_UPDATE_CHECK=1`` disables all network access.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from zai_roistat import __version__

REPOSITORY = "zai-one/roistat-mcp"
DIST_NAME = "zai-roistat-mcp"
WHEEL_NAME = "zai_roistat_mcp-{version}-py3-none-any.whl"
DISABLE_ENV = "ROISTAT_DISABLE_UPDATE_CHECK"
API_ROOT = "https://api.github.com"
CACHE_TTL_SECONDS = 24 * 3600
FAILURE_BACKOFF_SECONDS = 30 * 60
FORCE_MIN_INTERVAL_SECONDS = 60
TIMEOUT_SECONDS = 3.0
MAX_RESPONSE_BYTES = 512_000
MAX_TAG_LENGTH = 32
# ASCII digits only: ``\d`` would also accept other Unicode digits.
_VERSION = re.compile(r"v?([0-9]+(?:\.[0-9]+){0,3})")
_NOTES_URL = re.compile(
    re.escape(f"https://github.com/{REPOSITORY}/releases") + r"(?:/tag/v?[0-9]+(?:\.[0-9]+){0,3})?"
)
_TRUE = {"1", "true", "yes", "on"}
# Last attempt per cache path, so throttling still works when the cache file cannot be written.
_MEMORY: dict[str, dict[str, Any]] = {}


def disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in _TRUE


def parse_version(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str) or len(value) > MAX_TAG_LENGTH:
        return None
    match = _VERSION.fullmatch(value)
    if match is None:
        return None
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (3 - len(parts)) if len(parts) < 3 else parts


def _plain_version(value: object) -> str | None:
    """The version part of a plain tag (``v1.2.3`` -> ``1.2.3``); None for anything else."""
    if parse_version(value) is None:
        return None
    return str(value).removeprefix("v")


def _notes_url(value: object) -> str | None:
    return value if isinstance(value, str) and _NOTES_URL.fullmatch(value) else None


def _is_checkout() -> bool:
    return (Path(__file__).resolve().parents[2] / ".git").exists()


def update_commands(latest: str | None) -> dict[str, str]:
    version = _plain_version(latest)
    commands = {
        "git_checkout": "git pull --ff-only && uv sync --frozen",
    }
    if version:
        wheel = WHEEL_NAME.format(version=version)
        commands["release_package"] = (
            f'uv tool install --force "{DIST_NAME} @ https://github.com/{REPOSITORY}'
            f'/releases/download/v{version}/{wheel}"'
        )
    return commands


def _result(latest: str | None, notes_url: str | None, *, status: str, source: str, **extra: Any):
    version = _plain_version(latest)
    current = parse_version(__version__)
    newest = parse_version(version)
    available = bool(current and newest and newest > current)
    commands = update_commands(version if available else None)
    method = "git_checkout" if _is_checkout() else "release_package"
    payload: dict[str, Any] = {
        "current_version": __version__,
        "latest_version": version,
        "update_available": available,
        "status": status,
        "source": source,
        "release_notes_url": _notes_url(notes_url) if version else None,
        "install_method": method,
        "update_command": commands.get(method) if available else None,
        "update_commands": commands if available else {},
        "auto_update": False,
        "disable_with": f"{DISABLE_ENV}=1",
    }
    payload.update(extra)
    return payload


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _read_state(path: Path | None) -> dict[str, Any]:
    """Validated cache state; unknown or malformed fields are dropped, never trusted."""
    data: Any = None
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
    if not isinstance(data, dict) or data.get("repository") != REPOSITORY:
        data = _MEMORY.get(str(path), {})
    state: dict[str, Any] = {}
    checked = _number(data.get("checked_at"))
    if checked is not None and parse_version(data.get("latest")) is not None:
        state.update(
            latest=data["latest"],
            release_notes_url=_notes_url(data.get("release_notes_url")),
            checked_at=checked,
        )
    attempts = [value for value in (_number(data.get("attempted_at")), checked) if value is not None]
    if attempts:
        state["attempted_at"] = max(attempts)
    failed = _number(data.get("failed_at"))
    if failed is not None and failed >= state.get("checked_at", float("-inf")):
        state["failed_at"] = failed
    return state


def _write_state(path: Path | None, state: dict[str, Any]) -> None:
    record = {"repository": REPOSITORY, **state}
    _MEMORY[str(path)] = record
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(record), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return


def _decode(response: httpx.Response) -> Any:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    return response.json()


async def _fetch_latest(client: httpx.AsyncClient) -> tuple[str, str | None]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{DIST_NAME}/{__version__}"}
    response = await client.get(f"{API_ROOT}/repos/{REPOSITORY}/releases/latest", headers=headers)
    if response.status_code == 200:
        data = _decode(response)
        tag = data.get("tag_name") if isinstance(data, dict) else None
        if parse_version(tag) is None:
            raise ValueError("release without a plain version tag")
        notes = _notes_url(data.get("html_url"))
        return str(tag), notes or f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
    if response.status_code != 404:
        raise ValueError(f"GitHub API returned HTTP {response.status_code}")
    response = await client.get(f"{API_ROOT}/repos/{REPOSITORY}/tags?per_page=100", headers=headers)
    if response.status_code != 200:
        raise ValueError(f"GitHub API returned HTTP {response.status_code}")
    data = _decode(response)
    names = [item.get("name") for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    versions = [(parse_version(name), name) for name in names if parse_version(name) is not None]
    if not versions:
        raise ValueError("no version tags")
    tag = max(versions)[1]
    return str(tag), f"https://github.com/{REPOSITORY}/releases/tag/{tag}"


def _open_client() -> httpx.AsyncClient:
    """The only place a real network client is created; tests replace it."""
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False)


def _cached_result(state: dict[str, Any], *, status: str, source: str, **extra: Any) -> dict[str, Any]:
    if "checked_at" not in state:
        return _result(None, None, status=status, source="none", **extra)
    return _result(
        state["latest"],
        state["release_notes_url"],
        status=status,
        source=source,
        checked_at=int(state["checked_at"]),
        **extra,
    )


def cached_status(cache_path: Path | None) -> dict[str, Any] | None:
    """Return the last known result without any network access."""
    if disabled():
        return None
    state = _read_state(cache_path)
    if "checked_at" not in state:
        return None
    return _cached_result(state, status="ok", source="cache")


async def check_for_update(
    cache_path: Path | None,
    *,
    force: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if disabled():
        return _result(None, None, status="disabled", source="none")
    now = time.time()
    state = _read_state(cache_path)
    fresh = "checked_at" in state and now - state["checked_at"] < CACHE_TTL_SECONDS
    if fresh and not force:
        return _cached_result(state, status="ok", source="cache")
    since_attempt = now - state.get("attempted_at", float("-inf"))
    since_failure = now - state.get("failed_at", float("-inf"))
    wait = 0.0
    if force:
        wait = FORCE_MIN_INTERVAL_SECONDS - since_attempt
    elif since_failure < FAILURE_BACKOFF_SECONDS:
        wait = FAILURE_BACKOFF_SECONDS - since_failure
    if wait > 0:
        # Throttled: no request. Report the last good result, if any.
        throttle = {"throttled": True, "retry_after_seconds": int(wait) + 1}
        if "failed_at" in state:
            return _cached_result(
                state, status="unknown", source="stale_cache", error="recent_failure", **throttle
            )
        return _cached_result(state, status="ok", source="cache", **throttle)
    try:
        if client is None:
            async with _open_client() as owned:
                latest, notes = await _fetch_latest(owned)
        else:
            latest, notes = await _fetch_latest(client)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        attempt = time.time()
        _write_state(cache_path, {**state, "attempted_at": attempt, "failed_at": attempt})
        return _cached_result(state, status="unknown", source="stale_cache", error=type(exc).__name__)
    attempt = time.time()
    _write_state(
        cache_path,
        {"latest": latest, "release_notes_url": notes, "checked_at": attempt, "attempted_at": attempt},
    )
    return _result(latest, notes, status="ok", source="github")


def startup_hint(cache_path: Path | None) -> str:
    """One short sentence for server instructions; empty unless an update is known."""
    status = cached_status(cache_path)
    if not status or not status["update_available"]:
        return ""
    details = f" Details: {status['release_notes_url']}" if status["release_notes_url"] else ""
    return (
        f"Update available: {DIST_NAME} {status['latest_version']} "
        f"(installed {status['current_version']}). Tell the user once; do not update automatically." + details
    )


def refresh_in_background(cache_path: Path | None) -> None:
    """Best-effort cache refresh on a daemon thread; never blocks or raises.

    Uses the same cache, failure back-off and validation as ``check_for_update``.
    """
    if disabled():
        return
    import asyncio
    import threading

    def run() -> None:
        try:
            asyncio.run(check_for_update(cache_path))
        except Exception:  # noqa: BLE001 - background hint must never crash the server
            return

    threading.Thread(target=run, name="update-check", daemon=True).start()
