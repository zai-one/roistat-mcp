import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_adapter import RecordingHttp, _adapter
from test_server import config

from zai_roistat.server import AdmittedHttpClient, create_server
from zai_roistat.transport import ProviderError


async def test_dimension_values_use_documented_query_and_bound_output():
    http = RecordingHttp(
        {
            "status": "success",
            "values": [{"value": "seo", "title": "SEO", "email": "fixture@example.test"}, {"value": "site"}],
        }
    )
    result = await _adapter(http).analytics_dimension_values(12345, "marker_level_1", limit=1)
    assert http.calls[0][0] == "POST"
    assert http.calls[0][1].endswith("/project/analytics/dimension-values")
    assert http.calls[0][4] == {"project": "12345", "dimension": "marker_level_1"}
    assert result["truncated"] and result["returned_count"] == 1
    assert result["values"][0]["email"] != "fixture@example.test"


@pytest.mark.parametrize(
    "project,dimension,limit",
    [
        (999, "marker_level_1", 1),
        (12345, "email", 1),
        (12345, "marker_level_1", 201),
        (12345, "marker_level_1", True),
    ],
)
async def test_unauthorized_or_invalid_discovery_does_not_call_api(project, dimension, limit):
    http = RecordingHttp()
    with pytest.raises((ValueError, PermissionError)):
        await _adapter(http).analytics_dimension_values(project, dimension, limit)
    assert not http.calls


async def test_bad_provider_shape_is_not_reported_as_empty():
    with pytest.raises(ProviderError):
        await _adapter(RecordingHttp({"status": "success"})).analytics_custom_metrics(12345)


async def test_both_discovery_tools_use_admitted_http_via_mcp(tmp_path):
    calls = []

    class Http(AdmittedHttpClient):
        async def request(self, method, url, **kwargs):
            await self._admit_attempt(1)
            calls.append((method, url))
            return {"status": "success", "values": [{"value": "seo"}], "data": [{"id": 4, "title": "Chats"}]}

    server = create_server(config(tmp_path, RSAKeyPair.generate()), transport="stdio", http_factory=Http)
    async with Client(server) as client:
        values = (
            await client.call_tool(
                "roistat_dimension_values", {"project_id": 12345, "dimension": "marker_level_1"}
            )
        ).data
        metrics = (await client.call_tool("roistat_custom_metrics", {"project_id": 12345})).data
    assert values["values"] == [{"value": "seo"}]
    assert metrics["metrics"][0]["id"] == 4
    assert len(calls) == 2 and calls[1][0] == "GET"
