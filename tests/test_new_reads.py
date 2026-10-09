from __future__ import annotations

from typing import Any

import httpx
import pytest

from zai_roistat.adapter import RoistatAdapter
from zai_roistat.transport import JsonHttpClient, ProviderError, ProviderResponseError


class Http:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append((method, url, kwargs))
        return self.response


def adapter(http: Http) -> RoistatAdapter:
    return RoistatAdapter("secret-key", project_allowlist="12345", http=http)


INDICATORS = {
    "status": "success",
    "data": [
        {
            "name": "CRM",
            "indicators": [
                {
                    "id": 1,
                    "name": "Load",
                    "status": 1,
                    "messages": [{"s": 1, "m": "ok", "d": "2026-10-01 10:00:00"}] * 5,
                    "is_executable": True,
                    "is_running": False,
                },
                {"id": 8, "name": "Clients", "status": 3, "messages": [], "is_running": True},
            ],
        },
        {"name": "Counter", "indicators": [{"id": 3, "name": "Visits", "status": 2, "messages": []}]},
    ],
}


async def test_health_indicators_use_official_get_and_summarize() -> None:
    http = Http(INDICATORS)
    result = await adapter(http).health_indicators(12345, messages_per_indicator=2)
    method, url, kwargs = http.calls[0]
    assert method == "GET"
    assert url == "https://cloud.roistat.com/api/v1/project/health/indicator/list"
    assert kwargs["params"] == {"project": "12345"}
    assert kwargs["idempotent"] is True
    assert result["summary"] == {"ok": 1, "errors": 1, "not_finished": 1, "unknown": 0, "healthy": False}
    first = result["categories"][0]["indicators"][0]
    assert first["state"] == "ok" and len(first["messages"]) == 2 and first["messages_truncated"]
    assert first["messages"][0] == {"state": "ok", "message": "ok", "date": "2026-10-01 10:00:00"}


async def test_health_indicators_empty_is_unknown_and_invalid_rejected() -> None:
    result = await adapter(Http({"status": "success", "data": []})).health_indicators(12345)
    assert result["summary"]["healthy"] is None and result["completeness"] == "unknown"
    with pytest.raises(ProviderError):
        await adapter(Http({"status": "success", "data": "x"})).health_indicators(12345)
    with pytest.raises(ValueError):
        await adapter(Http(INDICATORS)).health_indicators(12345, messages_per_indicator=21)


async def test_list_channels_is_bounded() -> None:
    rows = [{"source": f"s{i}", "name": "n", "type": "custom", "level": 1, "icon": None} for i in range(5)]
    http = Http({"status": "success", "data": rows, "total": 5})
    result = await adapter(http).list_channels(12345, limit=2)
    assert http.calls[0][:2] == ("POST", "https://cloud.roistat.com/api/v1/project/analytics/source/list")
    assert result["returned_count"] == 2 and result["truncated"] and result["completeness"] == "partial"


async def test_channel_costs_accept_documented_bare_array_and_filter_locally() -> None:
    rows = [
        {"id": "1", "source": "yandex_seo", "marketing_cost": 1, "from_date": "2026-07-01"},
        {"id": "2", "source": "google", "marketing_cost": 2},
        {"id": "3", "source": "yandex_direct", "marketing_cost": 3},
    ]
    http = Http({"status": "success", "data": rows})
    result = await adapter(http).list_channel_costs(12345, limit=1, offset=1, source="yandex")
    method, url, kwargs = http.calls[0]
    assert (method, url) == ("POST", "https://cloud.roistat.com/api/v1/project/analytics/source/cost/list")
    assert kwargs["array_response"] is True
    assert result["matched"] == 2 and [row["id"] for row in result["items"]] == ["3"]
    assert result["truncated"] is False
    with pytest.raises(ValueError):
        await adapter(http).list_channel_costs(12345, source="../x")


async def test_managers_redact_pii() -> None:
    http = Http(
        {
            "status": "success",
            "data": [{"id": "1", "name": "Ivanov", "email": "a@example.test", "phone": "+70000000000"}],
            "total": 1,
        }
    )
    result = await adapter(http).list_managers(12345)
    assert http.calls[0][1].endswith("/project/integration/manager/list")
    assert result["items"] == [
        {"id": "1", "name": "Ivanov", "email": "***redacted***", "phone": "***redacted***"}
    ]


async def test_new_reads_respect_project_allowlist() -> None:
    http = Http({"status": "success", "data": []})
    for call in (
        adapter(http).health_indicators(1),
        adapter(http).list_channels(1),
        adapter(http).list_channel_costs(1),
        adapter(http).list_managers(1),
    ):
        with pytest.raises(PermissionError):
            await call
    assert http.calls == []


async def test_transport_wraps_array_only_when_requested(monkeypatch) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"id": "1"}]))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: original(*a, **{**k, "transport": transport}))
    client = JsonHttpClient(timeout=1)
    wrapped = await client.request(
        "POST", "https://cloud.roistat.com/x", array_response=True, idempotent=True
    )
    assert wrapped == {"status": "success", "data": [{"id": "1"}]}
    with pytest.raises(ProviderResponseError):
        await client.request("POST", "https://cloud.roistat.com/x", idempotent=True)
