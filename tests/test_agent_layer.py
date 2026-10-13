from __future__ import annotations

import json
import sys
from pathlib import Path

from fastmcp import Client

from zai_roistat.agent_layer import DESCRIPTION_LIMIT, INSTRUCTIONS_LIMIT
from zai_roistat.agent_profile import PROFILE
from zai_roistat.config import ServiceConfig
from zai_roistat.server import create_server
from zai_roistat.tools import compare_markdown, report_markdown

ROOT = Path(__file__).resolve().parents[1]
TOOLS_LIST_BUDGET = 40_000


def server(tmp_path: Path):
    config = ServiceConfig(api_key="synthetic", state_path=tmp_path / "s.sqlite", project_allowlist="12345")
    return create_server(config, transport="stdio")


async def test_token_budget_and_agent_surface(tmp_path):
    async with Client(server(tmp_path)) as client:
        assert len(client.initialize_result.instructions or "") <= INSTRUCTIONS_LIMIT
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {n for group in PROFILE.toolsets.values() for n in group}
        for tool in tools:
            assert tool.title and len(tool.description or "") <= DESCRIPTION_LIMIT, tool.name
        assert len(json.dumps([tool.model_dump(exclude_none=True) for tool in tools])) <= TOOLS_LIST_BUDGET
        uris = {str(item.uri) for item in await client.list_resources()}
        assert {"roistat://playbook", "roistat://toolsets", "roistat://guide/dimensions"} <= uris
        assert {p.name for p in await client.list_prompts()} == {"channel_report", "period_compare"}


async def test_read_only_and_toolsets(tmp_path, monkeypatch):
    monkeypatch.setenv("ROISTAT_READ_ONLY", "1")
    async with Client(server(tmp_path)) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert not names & {"roistat_prepare_write", "roistat_apply_write"}
    monkeypatch.delenv("ROISTAT_READ_ONLY")
    monkeypatch.setenv("ROISTAT_TOOLSETS", "calls")
    async with Client(server(tmp_path)) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {*PROFILE.toolsets["calls"], *PROFILE.toolsets["meta"]}


def test_markdown_tables_keep_unknown_blank():
    report = {
        "period": {"from": "2026-09-01", "to": "2026-09-30"},
        "completeness": "complete",
        "items": [
            {
                "dimensions": {"marker_level_1": {"title": "Яндекс.Директ"}},
                "metrics": [{"metric_name": "roi", "value": 12.5}, {"metric_name": "leads", "value": 4}],
            }
        ],
    }
    table = report_markdown(report, ["marker_level_1"])
    assert table["markdown"].splitlines() == [
        "| marker_level_1 | roi | leads |",
        "|---|---|---|",
        "| Яндекс.Директ | 12.5 | 4 |",
    ]
    compare = {
        "completeness": "partial",
        "items": [
            {
                "dimensions": {"marker_level_1": {"value": "seo"}},
                "metrics": {"roi": {"current": 3.0, "previous": None, "delta": None, "state": "unknown"}},
            }
        ],
    }
    lines = compare_markdown(compare, ["marker_level_1"])["markdown"].splitlines()
    assert lines[0] == "| marker_level_1 | roi now | roi prev | roi Δ |"
    assert lines[2] == "| seo | 3 |  |  |"


def test_static_budget_script_passes():
    sys.path.insert(0, str(ROOT / "scripts"))
    import token_budget

    assert token_budget.problems() == []
