import copy
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_server import PERIOD, SECRET, config, connection, token

from zai_roistat.analytics_bundle import normalize, numeric
from zai_roistat.server import AdmittedHttpClient, create_server

ARGS = dict(project_id=12345, metrics=["visits", "leads"], dimensions=["marker_level_1"], period=PERIOD)


def test_local_slice_stops_at_supported_offset_without_unusable_cursor():
    row = {"dimensions": {}, "metrics": []}
    result = normalize({"data": [{"items": [row] * 10500}]}, ["visits"], [], 10000, 250)
    assert result["selection"]["next_row_offset"] is None
    assert result["selection"]["stop_reason"] == "offset_limit"
    assert result["selection"]["all_response_rows_included"] is False
    assert len(result["rows"]) == 250


@pytest.mark.parametrize("value", ["1000000000000000.01", "-1000000000000000.01"])
def test_numeric_exact_boundary_is_not_rounded_into_range(value):
    assert numeric(value) == (None, "out_of_range")


class Provider:
    def __init__(self):
        self.calls = []
        self.response = {
            "status": "success",
            "data": [
                {
                    "dateFrom": PERIOD["from"],
                    "dateTo": PERIOD["to"],
                    "items": [
                        {
                            "dimensions": {
                                "marker_level_1": {"value": "direct", "title": "=Яндекс " + SECRET}
                            },
                            "metrics": {
                                "visits": {
                                    "metric_name": "visits",
                                    "value": 0,
                                    "attribution_model_id": "default",
                                }
                            },
                        },
                        {
                            "dimensions": {
                                "marker_level_1": {
                                    "value": {
                                        "email": "private@example.invalid",
                                        "nested": {"phone": "+70000000000"},
                                    },
                                    "title": "Второй",
                                }
                            },
                            "metrics": [
                                {
                                    "metric_name": "visits",
                                    "value": "3,5",
                                    "attribution_model_id": "first_click",
                                }
                            ],
                        },
                    ],
                    "mean": {
                        "metrics": {
                            "visits": {
                                "metric_name": "visits",
                                "value": 900,
                                "attribution_model_id": "default",
                            }
                        }
                    },
                }
            ],
        }

    def factory(self, store, execution_id, actor):
        owner = self

        class Http(AdmittedHttpClient):
            async def request(self, method, url, **kwargs):
                await self._admit_attempt(1)
                assert url.endswith("/project/analytics/data")
                owner.calls.append((method, url, kwargs))
                return copy.deepcopy(owner.response)

        return Http(store, execution_id, actor)


@pytest.fixture
def pair():
    from fastmcp.server.auth.providers.jwt import RSAKeyPair

    return RSAKeyPair.generate()


async def test_bundle_preserves_zero_missing_attribution_provider_totals_and_replay(tmp_path, pair):
    provider = Provider()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        result = (await client.call_tool("roistat_analytics_bundle", {**ARGS, "max_rows": 1})).data
    report = result["reports"][0]
    assert report["rows"][0]["metrics"]["visits"]["value"] == 0
    assert report["rows"][0]["metrics"]["visits"]["value_state"] == "present"
    assert report["rows"][0]["metrics"]["leads"]["value"] is None
    assert report["totals_by_block"][0]["metrics"]["visits"]["value"] == 900
    assert report["selection"]["rows_in_response"] == 2 and report["selection"]["next_row_offset"] == 1
    assert report["selection"]["all_response_rows_included"] is False
    assert report["selection"]["provider_completeness"] == "not_asserted"
    assert report["request"]["payload"]["metrics"][0] == {"metric": "visits", "attribution": "default"}
    assert result["replay"]["arguments"]["period"] == PERIOD and len(report["response_sha256"]) == 64
    assert len(provider.calls) == 1


async def test_csv_after_pii_and_literal_cleanup_nested_fields_and_two_periods(tmp_path, pair):
    provider = Provider()
    provider.response["data"][0]["dateFrom"] = "=untrusted_provider_date"
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        result = (
            await client.call_tool(
                "roistat_analytics_bundle", {**ARGS, "format": "csv", "comparison_period": PERIOD}
            )
        ).data
    rendered = json.dumps(result, ensure_ascii=False)
    assert (
        SECRET not in rendered
        and "private@example.invalid" not in rendered
        and "+70000000000" not in rendered
    )
    assert "'=Яндекс" in result["csv"] and "first_click" in result["csv"]
    assert "'=untrusted_provider_date" in result["csv"]
    assert len(result["reports"]) == 2 and len(provider.calls) == 2
    assert all("rows" not in report for report in result["reports"])
    assert result["reports"][0]["response_sha256"] == result["reports"][1]["response_sha256"]


async def test_local_slice_and_response_hash_detect_changed_dataset(tmp_path, pair):
    provider = Provider()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        args = {**ARGS, "row_offset": 1, "max_rows": 1}
        first = (await client.call_tool("roistat_analytics_bundle", args)).data
        provider.response["data"][0]["items"][1]["metrics"][0]["value"] = "4"
        second = (await client.call_tool("roistat_analytics_bundle", args)).data
    assert first["request_sha256"] == second["request_sha256"]
    assert first["reports"][0]["response_sha256"] != second["reports"][0]["response_sha256"]
    assert first["reports"][0]["rows"][0]["metrics"]["visits"]["value"] == 3.5
    assert first["reports"][0]["selection"]["next_row_offset"] is None


@pytest.mark.parametrize(
    "changes",
    [
        dict(project_id=999),
        dict(metrics=["visits", "visits"]),
        dict(metrics=["custom_metric"]),
        dict(dimensions=["email"]),
        dict(attribution="invented"),
        dict(comparison_period={"from": "bad", "to": "bad"}),
        dict(max_rows=251),
        dict(row_offset=-1),
    ],
)
async def test_all_request_validation_precedes_http(tmp_path, pair, changes):
    provider = Provider()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        with pytest.raises(ToolError):
            await client.call_tool("roistat_analytics_bundle", {**ARGS, **changes})
    assert not provider.calls


async def test_http_scope_and_account_cannot_bypass_export(tmp_path, pair):
    provider = Provider()
    server = create_server(config(tmp_path, pair), http_factory=provider.factory)
    for bearer in [token(pair, account="other"), token(pair, scopes=["roistat:write"])]:
        async with connection(server, bearer) as client:
            with pytest.raises(ToolError):
                await client.call_tool("roistat_analytics_bundle", {**ARGS, "format": "csv"})
    assert not provider.calls


async def test_malformed_block_duplicate_metric_and_oversized_report_fail(tmp_path, pair):
    provider = Provider()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        original = copy.deepcopy(provider.response)
        cases = [{"data": [{}]}, {"data": [original["data"][0]] * 94}]
        duplicate = copy.deepcopy(original)
        duplicate["data"][0]["items"][0]["metrics"] = [{"metric_name": "visits", "value": 1}] * 2
        cases.append(duplicate)
        large = copy.deepcopy(original)
        large["data"][0]["items"][0]["dimensions"]["marker_level_1"]["title"] = "x" * 270000
        cases.append(large)
        for response in cases:
            provider.response = response
            with pytest.raises(ToolError):
                await client.call_tool("roistat_analytics_bundle", ARGS)


@pytest.mark.parametrize("value", [None, "n/a", True, float("inf"), "1e309", "1e-1000033", 10**400])
def test_missing_invalid_overflow_and_underflow_never_become_zero(value):
    result, state = numeric(value)
    assert result is None and state != "present"


async def test_blocks_keep_separate_provider_totals(tmp_path, pair):
    provider = Provider()
    second = copy.deepcopy(provider.response["data"][0])
    second["dateFrom"] = "2026-06-02T00:00:00+0300"
    provider.response["data"].append(second)
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=provider.factory)
    ) as client:
        result = (await client.call_tool("roistat_analytics_bundle", {**ARGS, "interval": "1d"})).data
    assert len(result["reports"][0]["totals_by_block"]) == 2
    assert result["reports"][0]["rows"][2]["block_index"] == 1
