from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from zai_roistat.approvals import ApprovalStore
from zai_roistat.config import ServiceConfig
from zai_roistat.policy import PolicyStore
from zai_roistat.server import AdmittedHttpClient, create_server
from zai_roistat.transport import ProviderTransportError

SECRET = "synthetic-roistat-key-never-live"
PERIOD = {"from": "2026-06-01T00:00:00+0300", "to": "2026-06-02T23:59:59+0300"}
PROJECT = {"project_id": 12345}
ANALYTICS = {**PROJECT, "metrics": ["visits"], "dimensions": ["marker_level_1"]}
READ_CASES = {
    "roistat_list_projects": {},
    "roistat_capabilities": {},
    "roistat_health": PROJECT,
    "roistat_analytics_catalog": PROJECT,
    "roistat_analytics_report": {**ANALYTICS, "period": PERIOD},
    "roistat_analytics_compare": {**ANALYTICS, "current_period": PERIOD, "previous_period": PERIOD},
    "roistat_statistics_daily": {**PROJECT, "period": "2026-06-01-2026-06-02"},
    "roistat_list_orders": PROJECT,
    "roistat_get_order": {**PROJECT, "order_id": "1"},
    "roistat_list_order_statuses": PROJECT,
    "roistat_list_leads": {**PROJECT, "period": "2026-06-01-2026-06-02"},
    "roistat_get_lead": {**PROJECT, "lead_id": "1"},
    "roistat_list_lead_duplicates": {**PROJECT, "period": "2026-06-01-2026-06-02"},
    "roistat_list_calls": PROJECT,
    "roistat_calltracking_summary": {**PROJECT, "period": PERIOD},
    "roistat_list_visits": PROJECT,
    "roistat_list_clients": PROJECT,
    "roistat_funnel": {**PROJECT, "period": PERIOD, "funnel": [{"title": "New", "statuses": ["1"]}]},
    "roistat_health_indicators": PROJECT,
    "roistat_list_channels": PROJECT,
    "roistat_list_channel_costs": PROJECT,
    "roistat_list_managers": PROJECT,
}
NEW_TOOLS = {
    "roistat_dimension_values",
    "roistat_custom_metrics",
    "roistat_analytics_bundle",
    "roistat_health_indicators",
    "roistat_list_channels",
    "roistat_list_channel_costs",
    "roistat_list_managers",
    "roistat_check_update",
}
WRITE = {
    "operation": "update_order_status",
    "project_id": 12345,
    "payload": {"order_id": "1", "status_id": "2"},
}


@pytest.fixture(scope="module")
def pair():
    return RSAKeyPair.generate()


def config(path: Path, pair: RSAKeyPair, **kwargs):
    return replace(
        ServiceConfig(
            api_key=SECRET,
            state_path=path / "state.sqlite",
            public_key=pair.public_key,
            project_allowlist="12345",
        ),
        **kwargs,
    )


def token(pair, *, actor="operator", account="default", scopes=None):
    return pair.create_token(
        subject=actor,
        issuer="roistat-operator",
        audience="roistat-mcp",
        scopes=scopes if scopes is not None else ["roistat:read", "roistat:write"],
        expires_in_seconds=60,
        additional_claims={"account_id": account},
    )


@asynccontextmanager
async def connection(server, bearer):
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with (
        app.router.lifespan_context(app),
        Client(
            StreamableHttpTransport("http://fixture/mcp", auth=bearer, httpx_client_factory=factory)
        ) as client,
    ):
        yield client


class Recorder:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def factory(self, store, execution_id, actor):
        owner = self

        class Http(AdmittedHttpClient):
            async def request(self, method, url, **kwargs):
                mark = self.daily.set(url.endswith("/project/statistics/get-daily"))
                try:
                    await self._admit_attempt(1)
                finally:
                    self.daily.reset(mark)
                owner.calls.append((method, url, kwargs))
                if owner.fail:
                    raise owner.fail
                return {
                    "status": "success",
                    "data": [],
                    "total": 0,
                    "innocent": SECRET,
                    "phone": "+70000000000",
                    "email": "fixture@example.test",
                }

        return Http(store, execution_id, actor)


def approval_store(settings):
    return ApprovalStore(PolicyStore(settings.state_path, settings.account_id, 30, 30))


@pytest.mark.parametrize("name,arguments", READ_CASES.items())
async def test_all_original_read_tools_execute_real_adapter(tmp_path, pair, name, arguments):
    recorder = Recorder()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=recorder.factory)
    ) as client:
        result = (await client.call_tool(name, arguments)).data
    assert isinstance(result, dict)
    assert SECRET not in json.dumps(result)
    assert "+70000000000" not in json.dumps(result)
    assert all(call[2]["idempotent"] for call in recorder.calls)
    if name != "roistat_capabilities":
        assert recorder.calls


async def prepare(client, settings, *, actor="local-operator"):
    drafted = (await client.call_tool("roistat_prepare_write", WRITE)).data
    assert approval_store(settings).accept(
        UUID(drafted["approval_id"]), principal=actor, request_hash=drafted["request_hash"]
    )
    return {**WRITE, "approval_id": drafted["approval_id"], "idempotency_key": "change-1"}


async def test_original_contract_and_no_mcp_approval_accept(tmp_path, pair):
    contract = json.loads((Path(__file__).parents[1] / "contracts/roistat.json").read_text())["tools"]
    async with Client(create_server(config(tmp_path, pair), transport="stdio")) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == set(contract) | NEW_TOOLS
        for tool in tools:
            if tool.name not in contract:
                continue
            assert {
                "inputSchema": tool.inputSchema,
                "outputSchema": tool.outputSchema,
                "description": tool.description,
            } == contract[tool.name]
        assert all("accept" not in t.name for t in tools)


async def test_draft_is_unaccepted_and_acceptance_is_exactly_bound(tmp_path, pair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        draft = (await client.call_tool("roistat_prepare_write", WRITE)).data
        args = {**WRITE, "approval_id": draft["approval_id"], "idempotency_key": "change-1"}
        with pytest.raises(ToolError):
            await client.call_tool("roistat_apply_write", args)
        assert not recorder.calls
        store = approval_store(settings)
        identifier = UUID(draft["approval_id"])
        assert not store.accept(identifier, principal="wrong", request_hash=draft["request_hash"])
        assert not store.accept(identifier, principal="local-operator", request_hash="wrong")
        assert store.accept(identifier, principal="local-operator", request_hash=draft["request_hash"])
        assert not store.accept(identifier, principal="local-operator", request_hash=draft["request_hash"])
        result = (await client.call_tool("roistat_apply_write", args)).data
        assert result["applied"] and result["readback"] is not None
        assert SECRET not in json.dumps(result)
        assert "+70000000000" not in json.dumps(result)
        assert [x[2]["idempotent"] for x in recorder.calls] == [False, True]
    assert SECRET.encode() not in settings.state_path.read_bytes()
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2
        assert db.execute("SELECT status FROM approvals").fetchone()[0] == "consumed"
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "applied"


async def test_restart_reuses_result_but_rejects_new_key_or_payload(tmp_path, pair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        args = await prepare(client, settings)
        result = (await client.call_tool("roistat_apply_write", args)).data
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        assert (await client.call_tool("roistat_apply_write", args)).data == result
        for changed in ({"idempotency_key": "another"}, {"payload": {"order_id": "2", "status_id": "2"}}):
            with pytest.raises(ToolError):
                await client.call_tool("roistat_apply_write", {**args, **changed})
    assert len(recorder.calls) == 2


async def test_ambiguous_write_remains_pending_and_consumed_after_restart(tmp_path, pair):
    recorder = Recorder(fail=ProviderTransportError(SECRET))
    settings = config(tmp_path, pair, write_enabled=True)
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        args = await prepare(client, settings)
        with pytest.raises(ToolError) as error:
            await client.call_tool("roistat_apply_write", args)
        assert SECRET not in str(error.value)
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("roistat_apply_write", args)
    assert len(recorder.calls) == 1
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "pending"
        assert db.execute("SELECT status FROM approvals").fetchone()[0] == "consumed"


async def test_http_scopes_account_and_actor_prevent_cross_use(tmp_path, pair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    server = create_server(settings, http_factory=recorder.factory)
    async with connection(server, token(pair, scopes=["roistat:read"])) as client:
        assert len(await client.list_tools()) == 26
        with pytest.raises(ToolError):
            await client.call_tool("roistat_prepare_write", WRITE)
    async with connection(server, token(pair)) as client:
        args = await prepare(client, settings, actor="operator")
    for bearer in (token(pair, actor="another"), token(pair, account="another")):
        async with connection(server, bearer) as client:
            with pytest.raises(ToolError):
                await client.call_tool("roistat_apply_write", args)
    assert not recorder.calls


async def test_expired_approval_and_write_flag_fail_closed(tmp_path, pair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    async with Client(create_server(settings, transport="stdio", http_factory=recorder.factory)) as client:
        args = await prepare(client, settings)
        with sqlite3.connect(settings.state_path) as db:
            db.execute("UPDATE approvals SET expires=0")
        with pytest.raises(ToolError):
            await client.call_tool("roistat_apply_write", args)
    async with Client(
        create_server(
            replace(settings, write_enabled=False), transport="stdio", http_factory=recorder.factory
        )
    ) as client:
        with pytest.raises(ToolError):
            await client.call_tool("roistat_apply_write", args)
    assert not recorder.calls


@pytest.mark.parametrize("operation", ["create_ad_platform", "delete_orders_batch", "delete_crm_integration"])
async def test_unsupported_mutations_rejected_before_upstream(tmp_path, pair, operation):
    recorder = Recorder()
    async with Client(
        create_server(
            config(tmp_path, pair, write_enabled=True), transport="stdio", http_factory=recorder.factory
        )
    ) as client:
        with pytest.raises(ToolError):
            await client.call_tool("roistat_prepare_write", {**WRITE, "operation": operation})
    assert not recorder.calls


async def test_stdio_process_loads_real_service(tmp_path):
    secret = tmp_path / "synthetic.key"
    secret.write_text(SECRET)
    secret.chmod(0o600)
    async with Client(
        StdioTransport(
            command=sys.executable,
            args=["-m", "zai_roistat"],
            env={
                "ROISTAT_API_KEY_FILE": str(secret),
                "ROISTAT_STATE_PATH": str(tmp_path / "stdio.sqlite"),
                "ROISTAT_DISABLE_UPDATE_CHECK": "1",
            },
        )
    ) as client:
        assert len(await client.list_tools()) == 28
        with pytest.raises(ToolError):
            await client.call_tool("roistat_get_order", {"project_id": 0, "order_id": "x"})


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
async def test_cancelled_write_stops_upstream_before_releasing_lease(tmp_path, pair, monkeypatch, mode):
    import zai_roistat.server as module
    from zai_roistat.errors import SafeToolError

    entered, stopped = asyncio.Event(), asyncio.Event()

    class Slow(AdmittedHttpClient):
        async def request(self, method, url, **kwargs):
            await self._admit_attempt(1)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    settings = config(tmp_path, pair, write_enabled=True)
    runtime = module.Runtime(settings, "stdio", Slow)

    async def operation():
        return await runtime.write(
            "roistat",
            "update",
            {},
            "key",
            enabled=True,
            validate=lambda: None,
            apply_fn=lambda: runtime.roistat().apply_write(**WRITE),
        )

    if mode == "timeout":
        monkeypatch.setattr(module, "OPERATION_TIMEOUT_SECONDS", 0.1)
    task = asyncio.create_task(runtime.execute("roistat_apply_write", {}, operation))
    await entered.wait()
    if mode == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if mode == "cancel" else SafeToolError):
        await task
    assert stopped.is_set()
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "pending"


async def test_tool_annotations_match_side_effects(tmp_path, pair):
    async with Client(create_server(config(tmp_path, pair), transport="stdio")) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    for name, tool in tools.items():
        hints = tool.annotations
        assert hints is not None, name
        if name in {"roistat_prepare_write", "roistat_apply_write"}:
            assert hints.readOnlyHint is False, name
        else:
            assert hints.readOnlyHint is True and hints.destructiveHint is False, name
    assert tools["roistat_apply_write"].annotations.destructiveHint is True
    assert tools["roistat_prepare_write"].annotations.destructiveHint is False
