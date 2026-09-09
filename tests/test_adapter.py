from __future__ import annotations

from typing import Any

import pytest

from zai_roistat.adapter import (
    ALLOWED_METRICS,
    WRITE_ALLOWLIST,
    RoistatAdapter,
)
from zai_roistat.transport import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderHttpError,
    ProviderNotFoundError,
    ProviderRateLimited,
    ProviderTransientHttpError,
)


class RecordingHttp:
    def __init__(self, response: dict[str, Any] | None = None, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str], Any, dict[str, Any] | None, bool]] = []
        self.response = response if response is not None else {"status": "success", "projects": []}
        self.error = error
        self.responses: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((method, url, headers or {}, payload, params, idempotent))
        if self.error is not None:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return self.response


def _adapter(
    http: RecordingHttp,
    *,
    api_key: str = "secret-key",
    allowlist: str = "12345",
    writes: str = "",
    base_url: str = "https://cloud.roistat.com/api/v1",
) -> RoistatAdapter:
    return RoistatAdapter(
        api_key,
        base_url,
        project_allowlist=allowlist,
        write_operations=writes,
        http=http,
    )


PERIOD = {"from": "2026-08-01T00:00:00+0300", "to": "2026-08-07T23:59:59+0300"}


@pytest.mark.asyncio
async def test_projects_use_official_host_api_key_header_and_http_codes() -> None:
    http = RecordingHttp(
        {
            "status": "success",
            "projects": [
                {
                    "id": 12345,
                    "name": "demo",
                    "currency": "RUB",
                    "is_owner": 1,
                    "creation_date": "2026-01-01 00:00:00",
                    "profit": "0",
                }
            ],
        }
    )
    result = await _adapter(http).list_projects()

    assert result["total"] == 1
    assert result["projects"][0]["id"] == 12345
    method, url, headers, payload, params, idempotent = http.calls[0]
    assert method == "GET"
    assert url == "https://cloud.roistat.com/api/v1/user/projects"
    assert headers["Api-key"] == "secret-key"
    assert headers["Use-Http-Code"] == "1"
    assert "key" not in (params or {})
    assert payload is None
    assert idempotent is True
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_ssrf_and_path_escape_are_rejected_before_network() -> None:
    http = RecordingHttp()
    with pytest.raises(ValueError, match="official HTTPS"):
        RoistatAdapter("secret", "http://cloud.roistat.com/api/v1", http=http)
    with pytest.raises(ValueError, match="official HTTPS"):
        RoistatAdapter("secret", "https://attacker.invalid/api/v1", http=http)
    with pytest.raises(ValueError, match="official HTTPS"):
        RoistatAdapter("secret", "https://cloud.roistat.com/api/v1/../admin", http=http)
    adapter = _adapter(http)
    with pytest.raises(ValueError, match="safe identifier"):
        await adapter.get_order(12345, "../proxy-leads")
    with pytest.raises(ValueError, match="safe identifier"):
        await adapter.get_lead(12345, "https://evil.test/x")
    assert http.calls == []


@pytest.mark.asyncio
async def test_project_allowlist_and_unbounded_inputs_fail_closed() -> None:
    http = RecordingHttp()
    adapter = _adapter(http, allowlist="12345")
    with pytest.raises(PermissionError, match="allowlist"):
        await adapter.list_orders(99999)
    with pytest.raises(ValueError, match="between 1 and 100"):
        await adapter.list_orders(12345, limit=101)
    with pytest.raises(ValueError, match="unsupported Roistat metric"):
        await adapter.analytics_report(12345, ["not_a_metric"], ["marker_level_1"], PERIOD)
    with pytest.raises(ValueError, match="unsupported Roistat dimension"):
        await adapter.analytics_report(12345, ["visits"], ["browser"], PERIOD)
    with pytest.raises(ValueError, match="at most 2"):
        await adapter.analytics_report(
            12345,
            ["visits"],
            ["marker_level_1", "marker_level_2", "marker_level_3"],
            PERIOD,
        )
    with pytest.raises(ValueError, match="at most 31 days"):
        await adapter.list_leads(12345, "2026-01-01-2026-03-15")
    assert http.calls == []
    assert "visits" in ALLOWED_METRICS


@pytest.mark.asyncio
async def test_empty_response_is_unknown_not_zero() -> None:
    http = RecordingHttp({"status": "success", "data": [], "total": 0})
    result = await _adapter(http).list_orders(12345)
    assert result["items"] == []
    assert result["completeness"] == "unknown"
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_partial_page_is_marked_partial() -> None:
    http = RecordingHttp(
        {
            "status": "success",
            "data": [{"id": "1", "status": {"id": "0", "type": "progress", "name": "open"}}],
            "total": 40,
        }
    )
    result = await _adapter(http).list_orders(12345, limit=1)
    assert result["completeness"] == "partial"


@pytest.mark.asyncio
async def test_lead_and_call_pii_is_redacted() -> None:
    http = RecordingHttp(
        {
            "status": "success",
            "ProxyLead": {
                "id": "2",
                "title": "form",
                "text": "call me",
                "name": "Alice",
                "phone": "79998887766",
                "email": "alice@example.test",
                "order_id": "9",
            },
        }
    )
    lead = await _adapter(http).get_lead(12345, "2")
    assert lead["lead"]["phone"] == "***redacted***"
    assert lead["lead"]["email"] == "***redacted***"
    assert lead["lead"]["text"] == "***redacted***"
    assert lead["lead"]["order_id"] == "9"

    http.response = {
        "status": "success",
        "data": [{"id": "8", "caller": "79991112233", "callee": "74951234567", "status": "ANSWER"}],
        "total": 1,
    }
    calls = await _adapter(http).list_calls(12345)
    assert calls["items"][0]["caller"] == "***redacted***"
    assert calls["items"][0]["callee"] == "***redacted***"
    assert calls["items"][0]["status"] == "ANSWER"


@pytest.mark.asyncio
async def test_auth_error_envelope_does_not_echo_secret() -> None:
    http = RecordingHttp({"status": "error", "error": "authentication_failed", "detail": "secret-key"})
    adapter = _adapter(http)
    with pytest.raises(ProviderAuthenticationError) as captured:
        await adapter.list_projects()
    assert "secret-key" not in str(captured.value)


@pytest.mark.asyncio
async def test_http_status_mapping_for_401_429_and_5xx() -> None:
    for error, expected in (
        (ProviderAuthenticationError(401), ProviderAuthenticationError),
        (ProviderRateLimited("provider returned HTTP 429", retry_after_seconds=12), ProviderRateLimited),
        (ProviderTransientHttpError(503), ProviderTransientHttpError),
        (ProviderHttpError(403), ProviderHttpError),
    ):
        http = RecordingHttp(error=error)
        with pytest.raises(expected):
            await _adapter(http).list_projects()


@pytest.mark.asyncio
async def test_application_rate_limit_and_not_found() -> None:
    http = RecordingHttp({"status": "error", "error": "request_limit_error"})
    with pytest.raises(ProviderRateLimited):
        await _adapter(http).list_projects()
    http.response = {"status": "error", "error": "resource_not_found"}
    with pytest.raises(ProviderNotFoundError):
        await _adapter(http).get_order(12345, "missing")


@pytest.mark.asyncio
async def test_analytics_and_compare_do_not_invent_zeros() -> None:
    current = {
        "status": "success",
        "data": [
            {
                "items": [
                    {
                        "dimensions": {"marker_level_1": {"value": "direct1", "title": "Direct"}},
                        "metrics": [{"metric_name": "visits", "value": "10"}],
                    }
                ]
            }
        ],
    }
    previous = {
        "status": "success",
        "data": [
            {
                "items": [
                    {
                        "dimensions": {"marker_level_1": {"value": "direct1", "title": "Direct"}},
                        "metrics": [{"metric_name": "leads", "value": "4"}],
                    }
                ]
            }
        ],
    }
    http = RecordingHttp()
    http.responses = [current, previous]
    result = await _adapter(http).analytics_compare(
        12345,
        ["visits", "leads"],
        ["marker_level_1"],
        PERIOD,
        {"from": "2026-07-01T00:00:00+0300", "to": "2026-07-07T23:59:59+0300"},
    )
    changes = result["items"][0]["metrics"]
    assert changes["visits"]["state"] == "unknown"
    assert changes["visits"]["delta"] is None
    assert "leads" not in changes or changes.get("leads", {}).get("state") in {"unknown", None}


@pytest.mark.asyncio
async def test_statistics_daily_uses_documented_path_and_local_hour_cap() -> None:
    http = RecordingHttp(
        {
            "status": "success",
            "StatisticsItems": [
                {"dateStart": "2026-08-01 00:00:00", "dateEnd": "2026-08-01 23:59:59", "visitCount": 3}
            ],
            "SummaryItem": {"visitCount": 3},
            "AverageItem": {"visitCount": 3},
        }
    )
    adapter = _adapter(http)
    result = await adapter.statistics_daily(12345, "2026-08-01-2026-08-02", time_zone="Europe/Moscow")
    assert result["last_available_date"] == "2026-08-01 23:59:59"
    assert http.calls[0][1].endswith("/project/statistics/get-daily")
    assert http.calls[0][3] == {"period": "2026-08-01-2026-08-02", "time_zone": "Europe/Moscow"}
    await adapter.statistics_daily(12345, "2026-08-01-2026-08-02")
    await adapter.statistics_daily(12345, "2026-08-01-2026-08-02")
    with pytest.raises(ProviderRateLimited, match="get-daily"):
        await adapter.statistics_daily(12345, "2026-08-01-2026-08-02")


@pytest.mark.asyncio
async def test_reads_are_idempotent_and_missing_key_fails_before_network() -> None:
    http = RecordingHttp()
    with pytest.raises(ProviderError, match="not configured"):
        await _adapter(http, api_key="").list_projects()
    assert http.calls == []
    await _adapter(http).list_projects()
    assert http.calls[0][5] is True


@pytest.mark.asyncio
async def test_health_empty_freshness_is_unknown() -> None:
    http = RecordingHttp()
    http.responses = [
        {"status": "success", "projects": [{"id": 12345, "name": "demo", "currency": "RUB"}]},
        {"status": "success", "StatisticsItems": [], "SummaryItem": None},
    ]
    result = await _adapter(http).health(12345)
    assert result["auth"]["authenticated"] is True
    assert result["freshness"]["state"] == "unknown"
    assert result["freshness"]["last_available_date"] is None
    second = await _adapter(http).health(12345)
    assert second["auth"]["authenticated"] is True


@pytest.mark.asyncio
async def test_write_gating_rejects_platforms_batch_delete_and_disabled_ops() -> None:
    http = RecordingHttp()
    adapter = _adapter(http, writes="update_order_status,delete_order")
    with pytest.raises(ProviderError, match="unsupported_by_official_api"):
        adapter.validate_write("create_ad_platform", 12345, {"name": "direct"})
    with pytest.raises(ProviderError, match="unsupported_by_official_api"):
        adapter.validate_write("delete_crm_integration", 12345, {"id": "1"})
    with pytest.raises(ProviderError, match="batch delete"):
        adapter.validate_write("delete_orders_batch", 12345, {"ids": ["1", "2"]})
    with pytest.raises(ProviderError, match="not enabled"):
        adapter.validate_write("import_order", 12345, {"id": "1", "date_create": "2026-01-01", "status": "0"})
    with pytest.raises(ProviderError, match="confirm_delete"):
        adapter.validate_write("delete_order", 12345, {"order_id": "1"})
    with pytest.raises(ProviderError, match="single-object"):
        adapter.validate_write(
            "delete_order",
            12345,
            {"order_id": "1", "confirm_delete": True, "ids": ["1", "2"]},
        )
    assert http.calls == []
    assert set(WRITE_ALLOWLIST) == {"update_order_status", "import_order", "import_client", "delete_order"}


@pytest.mark.asyncio
async def test_writes_require_project_allowlist() -> None:
    http = RecordingHttp()
    adapter = RoistatAdapter("secret", project_allowlist="", write_operations="delete_order", http=http)
    with pytest.raises(PermissionError, match="project allowlist"):
        adapter.validate_write("delete_order", 12345, {"order_id": "1", "confirm_delete": True})


@pytest.mark.asyncio
async def test_apply_write_is_not_coalesced_and_readback_uses_order_info() -> None:
    http = RecordingHttp({"status": "success"})
    adapter = _adapter(http, writes="update_order_status,delete_order")
    applied = await adapter.apply_write(
        "update_order_status", 12345, {"order_id": "order_1", "status_id": "2"}
    )
    assert applied["applied"] is True
    assert applied["risk_tier"] == "medium"
    method, url, _headers, payload, params, idempotent = http.calls[0]
    assert method == "POST"
    assert url.endswith("/project/integration/order/order_1/status/update")
    assert payload == {"status_id": "2"}
    assert params == {"project": "12345"}
    assert idempotent is False

    http.response = {"status": "success", "order": {"id": "order_1", "status": "progress"}}
    readback = await adapter.readback("update_order_status", 12345, "order_1")
    assert readback["order"]["id"] == "order_1"
    assert http.calls[1][1].endswith("/project/orders/order_1/info")


@pytest.mark.asyncio
async def test_delete_readback_treats_not_found_as_deleted() -> None:
    http = RecordingHttp(error=ProviderNotFoundError(404))
    adapter = _adapter(http, writes="delete_order")
    result = await adapter.readback("delete_order", 12345, "gone")
    assert result == {"deleted": True, "object_id": "gone", "completeness": "complete"}


@pytest.mark.asyncio
async def test_import_order_sends_single_array_item() -> None:
    http = RecordingHttp({"status": "success", "saved": 1})
    adapter = _adapter(http, writes="import_order")
    result = await adapter.apply_write(
        "import_order",
        12345,
        {"id": "crm-9", "date_create": "2026-08-01T00:00:00+0000", "status": "0", "price": "100"},
    )
    assert result["object_id"] == "crm-9"
    assert isinstance(http.calls[0][3], list)
    assert http.calls[0][3][0]["id"] == "crm-9"


@pytest.mark.asyncio
async def test_response_drift_on_error_status_without_secret_echo() -> None:
    http = RecordingHttp({"status": "failed", "message": "fixture-secret"})
    with pytest.raises(ProviderError, match="application error") as captured:
        await _adapter(http).list_projects()
    assert "fixture-secret" not in str(captured.value)


def test_capabilities_document_closed_platform_writes() -> None:
    caps = _adapter(RecordingHttp()).capabilities()
    assert caps["official_mcp"]["proxied"] is False
    assert "create_ad_platform" in caps["unsupported_by_official_api"]
    assert caps["limits"]["local"]["per_minute"] == 30
    assert caps["limits"]["official"]["per_minute"] == 100
