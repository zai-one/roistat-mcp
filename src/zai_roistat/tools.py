from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from zai_roistat import update_check
from zai_roistat.adapter import (
    ALLOWED_CALL_FILTER_FIELDS,
    ALLOWED_CALL_STATUSES,
    ALLOWED_CLIENT_FILTER_FIELDS,
    ALLOWED_VISIT_FILTER_FIELDS,
)
from zai_roistat.transport import ProviderError, request_hash

# MCP tool annotations are hints for clients; server-side scopes, project
# allowlists and approvals remain the actual enforcement.
READ_ONLY: dict[str, bool] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
LOCAL_READ_ONLY: dict[str, bool] = {**READ_ONLY, "openWorldHint": False}
# Drafting only records a local, unaccepted approval; nothing reaches Roistat.
PREPARE_WRITE: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
# delete_order is in the allowlist, so the apply tool is marked destructive.
APPLY_WRITE: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}


def _cell(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("title") or value.get("value") or value.get("name")
    if isinstance(value, float):
        value = f"{value:.2f}".rstrip("0").rstrip(".")
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")[:120]


def _dimension_cells(item: Mapping[str, Any], dimensions: list[str]) -> list[str]:
    dims = item.get("dimensions")
    dims = dims if isinstance(dims, Mapping) else {}
    return [_cell(dims.get(name)) for name in dimensions]


def report_markdown(result: Mapping[str, Any], dimensions: list[str]) -> dict[str, Any]:
    """Render analytics items as one Markdown table (dimensions x metric values)."""
    items = [item for item in result.get("items", []) if isinstance(item, Mapping)]
    names: list[str] = []
    for item in items:
        for row in item.get("metrics") or []:
            if isinstance(row, Mapping):
                name = str(row.get("metric_name") or row.get("metric") or "")
                if name and name not in names:
                    names.append(name)
    lines = ["| " + " | ".join([*dimensions, *names]) + " |", "|" + "---|" * (len(dimensions) + len(names))]
    for item in items:
        values = {
            str(row.get("metric_name") or row.get("metric") or ""): row.get("value")
            for row in item.get("metrics") or []
            if isinstance(row, Mapping)
        }
        lines.append(
            "| "
            + " | ".join([*_dimension_cells(item, dimensions), *(_cell(values.get(n)) for n in names)])
            + " |"
        )
    return {
        "format": "markdown_table",
        "period": result.get("period"),
        "completeness": result.get("completeness"),
        "rows": len(items),
        "markdown": "\n".join(lines),
    }


def compare_markdown(result: Mapping[str, Any], dimensions: list[str]) -> dict[str, Any]:
    """Render a period comparison as Markdown: current / previous / delta per metric; unknown stays blank."""
    items = [item for item in result.get("items", []) if isinstance(item, Mapping)]
    names: list[str] = []
    for item in items:
        for name in item.get("metrics") or {}:
            if name not in names:
                names.append(name)
    header = [*dimensions, *(f"{n} {suffix}" for n in names for suffix in ("now", "prev", "Δ"))]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for item in items:
        metrics = item.get("metrics") or {}
        cells = _dimension_cells(item, dimensions)
        for name in names:
            change = metrics.get(name) or {}
            cells += [_cell(change.get("current")), _cell(change.get("previous")), _cell(change.get("delta"))]
        lines.append("| " + " | ".join(cells) + " |")
    return {
        "format": "markdown_table",
        "current": result.get("current"),
        "previous": result.get("previous"),
        "completeness": result.get("completeness"),
        "rows": len(items),
        "markdown": "\n".join(lines),
    }


def register_tools(server: Any, runtime: Any) -> None:
    registry = runtime
    settings = runtime
    store = runtime.approvals
    ApprovalRecord = runtime.approval_record
    current_access = runtime.current_access
    require_scopes = runtime.require_scopes
    safe_provider_error = runtime.safe_error
    _provider_read = runtime.read
    _autonomous_write = runtime.write

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_dimension_values(project_id: int, dimension: str, limit: int = 100) -> dict[str, Any]:
        """Discover a bounded sample of allowed dimension values with explicit completeness."""
        adapter = registry.roistat()
        arguments = dict(project_id=project_id, dimension=dimension, limit=limit)
        return await _provider_read(
            "roistat",
            "dimension_values",
            arguments,
            lambda: adapter.analytics_dimension_values(**arguments),
            validate=lambda: adapter.validate_discovery(**arguments),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_custom_metrics(project_id: int, limit: int = 100) -> dict[str, Any]:
        """Discover custom metric definitions without changing values or report permissions."""
        adapter = registry.roistat()
        arguments = dict(project_id=project_id, limit=limit)
        return await _provider_read(
            "roistat",
            "custom_metrics",
            arguments,
            lambda: adapter.analytics_custom_metrics(**arguments),
            validate=lambda: adapter.validate_discovery(**arguments),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_projects() -> dict[str, Any]:
        """List Roistat projects visible to the server-side API key."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_projects",
            {},
            adapter.list_projects,
            validate=adapter.validate_projects,
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=LOCAL_READ_ONLY)
    async def roistat_capabilities() -> dict[str, Any]:
        """Return the fixed Roistat capability matrix without calling the API."""
        await registry.ensure_enabled("roistat")
        return registry.roistat().capabilities()

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_health(project_id: int | None = None) -> dict[str, Any]:
        """Probe Roistat auth, freshness, empty/partial state, rate-limit and drift."""
        adapter = registry.roistat()
        result = await _provider_read(
            "roistat",
            "health",
            {"project_id": project_id},
            lambda: adapter.health(project_id),
        )
        # Cache-only hint: never contacts GitHub from the health probe.
        known = update_check.cached_status(registry.update_cache_path)
        if known and known["update_available"]:
            result["update"] = {
                key: known[key]
                for key in ("current_version", "latest_version", "release_notes_url", "update_command")
            }
        return result

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_check_update(force: bool = False) -> dict[str, Any]:
        """Check whether a newer Roistat MCP release exists on GitHub. Suggests, never installs.

        Uses the public GitHub API with a short timeout and a 24h cache; set
        ROISTAT_DISABLE_UPDATE_CHECK=1 to turn it off.
        """
        return await update_check.check_for_update(registry.update_cache_path, force=force)

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_analytics_catalog(project_id: int) -> dict[str, Any]:
        """List documented analytics metrics, dimensions and attribution models."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "analytics_catalog",
            {"project_id": project_id},
            lambda: adapter.analytics_catalog(project_id),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_analytics_report(
        project_id: int,
        metrics: list[Any],
        dimensions: list[str],
        period: dict[str, Any],
        attribution: str | None = None,
        interval: str | None = None,
        format: Literal["json", "markdown_table"] = "json",
    ) -> dict[str, Any]:
        """Run a bounded Roistat analytics report with an allowlisted metric set."""
        adapter = registry.roistat()
        result = await _provider_read(
            "roistat",
            "analytics_report",
            {
                "project_id": project_id,
                "metrics": metrics,
                "dimensions": dimensions,
                "period": period,
                "attribution": attribution,
                "interval": interval,
            },
            lambda: adapter.analytics_report(project_id, metrics, dimensions, period, attribution, interval),
            validate=lambda: adapter.validate_analytics(
                project_id, metrics, dimensions, period, attribution=attribution, interval=interval
            ),
        )
        return report_markdown(result, dimensions) if format == "markdown_table" else result

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_analytics_compare(
        project_id: int,
        metrics: list[Any],
        dimensions: list[str],
        current_period: dict[str, Any],
        previous_period: dict[str, Any],
        attribution: str | None = None,
        format: Literal["json", "markdown_table"] = "json",
    ) -> dict[str, Any]:
        """Compare two analytics periods without treating missing values as zero."""
        adapter = registry.roistat()
        result = await _provider_read(
            "roistat",
            "analytics_compare",
            {
                "project_id": project_id,
                "metrics": metrics,
                "dimensions": dimensions,
                "current_period": current_period,
                "previous_period": previous_period,
                "attribution": attribution,
            },
            lambda: adapter.analytics_compare(
                project_id,
                metrics,
                dimensions,
                current_period,
                previous_period,
                attribution,
            ),
            validate=lambda: (
                adapter.validate_analytics(
                    project_id, metrics, dimensions, current_period, attribution=attribution
                ),
                adapter.validate_analytics(
                    project_id, metrics, dimensions, previous_period, attribution=attribution
                ),
            ),
        )
        return compare_markdown(result, dimensions) if format == "markdown_table" else result

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_statistics_daily(
        project_id: int,
        period: str,
        time_zone: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Read daily visit-period statistics. Official extra cap is 5 requests/hour."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "statistics_daily",
            {
                "project_id": project_id,
                "period": period,
                "time_zone": time_zone,
                "channel": channel,
            },
            lambda: adapter.statistics_daily(project_id, period, time_zone, channel),
            validate=lambda: adapter.validate_statistics(project_id, period, time_zone, channel),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_orders(
        project_id: int,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """List bounded Roistat/CRM orders. Empty pages stay unknown, not zero."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_orders",
            {"project_id": project_id, "limit": limit, "offset": offset, "filters": filters},
            lambda: adapter.list_orders(project_id, limit=limit, offset=offset, filters=filters),
            validate=lambda: adapter.validate_list(project_id, limit=limit, offset=offset, filters=filters),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_get_order(project_id: int, order_id: str) -> dict[str, Any]:
        """Read one order/deal card, including funnel status and visit chain."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "get_order",
            {"project_id": project_id, "order_id": order_id},
            lambda: adapter.get_order(project_id, order_id),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_order_statuses(project_id: int) -> dict[str, Any]:
        """List CRM funnel statuses mapped in the Roistat project."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_order_statuses",
            {"project_id": project_id},
            lambda: adapter.list_order_statuses(project_id),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_leads(
        project_id: int, period: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """List proxy leads for a bounded YYYY-MM-DD-YYYY-MM-DD period. PII is redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_leads",
            {"project_id": project_id, "period": period, "limit": limit, "offset": offset},
            lambda: adapter.list_leads(project_id, period, limit=limit, offset=offset),
            validate=lambda: adapter.validate_list(
                project_id, limit=limit, offset=offset, period=period, require_period=True
            ),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_get_lead(project_id: int, lead_id: str) -> dict[str, Any]:
        """Read one proxy lead by Roistat id. Phone and email are redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "get_lead",
            {"project_id": project_id, "lead_id": lead_id},
            lambda: adapter.get_lead(project_id, lead_id),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_lead_duplicates(
        project_id: int, period: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """List duplicate proxy leads for a bounded period."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_lead_duplicates",
            {"project_id": project_id, "period": period, "limit": limit, "offset": offset},
            lambda: adapter.list_lead_duplicates(project_id, period, limit=limit, offset=offset),
            validate=lambda: adapter.validate_list(
                project_id, limit=limit, offset=offset, period=period, require_period=True
            ),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_calls(
        project_id: int,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """List calltracking history. Caller and callee numbers are redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_calls",
            {"project_id": project_id, "limit": limit, "offset": offset, "filters": filters},
            lambda: adapter.list_calls(project_id, limit=limit, offset=offset, filters=filters),
            validate=lambda: adapter.validate_list(
                project_id,
                limit=limit,
                offset=offset,
                filters=filters,
                allowed_fields=ALLOWED_CALL_FILTER_FIELDS,
                extra_status=ALLOWED_CALL_STATUSES,
            ),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_calltracking_summary(project_id: int, period: dict[str, Any] | str) -> dict[str, Any]:
        """Read the official calltracking dashboard summary for one period."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "calltracking_summary",
            {"project_id": project_id, "period": period},
            lambda: adapter.calltracking_summary(project_id, period),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_visits(
        project_id: int,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """List site visits. Visitor IPs are redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_visits",
            {"project_id": project_id, "limit": limit, "offset": offset, "filters": filters},
            lambda: adapter.list_visits(project_id, limit=limit, offset=offset, filters=filters),
            validate=lambda: adapter.validate_list(
                project_id,
                limit=limit,
                offset=offset,
                filters=filters,
                allowed_fields=ALLOWED_VISIT_FILTER_FIELDS,
            ),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_clients(
        project_id: int,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """List CRM clients with phone and email redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_clients",
            {"project_id": project_id, "limit": limit, "offset": offset, "filters": filters},
            lambda: adapter.list_clients(project_id, limit=limit, offset=offset, filters=filters),
            validate=lambda: adapter.validate_list(
                project_id,
                limit=limit,
                offset=offset,
                filters=filters,
                allowed_fields=ALLOWED_CLIENT_FILTER_FIELDS,
            ),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_funnel(
        project_id: int, period: dict[str, Any], funnel: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Read the official status-funnel report for one project."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "funnel",
            {"project_id": project_id, "period": period, "funnel": funnel},
            lambda: adapter.funnel(project_id, period, funnel),
            validate=lambda: adapter.validate_funnel(project_id, period, funnel),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_health_indicators(project_id: int, messages_per_indicator: int = 3) -> dict[str, Any]:
        """Read the official project-state processes (CRM sync, counter, analytics rebuild).

        Read-only; never starts a process. Status: ok, errors or not_finished.
        """
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "health_indicators",
            {"project_id": project_id, "messages_per_indicator": messages_per_indicator},
            lambda: adapter.health_indicators(project_id, messages_per_indicator),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_channels(project_id: int, limit: int = 200) -> dict[str, Any]:
        """List advertising channels (system and manually marked) used in a project."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_channels",
            {"project_id": project_id, "limit": limit},
            lambda: adapter.list_channels(project_id, limit),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_channel_costs(
        project_id: int, limit: int = 50, offset: int = 0, source: str | None = None
    ) -> dict[str, Any]:
        """List manually entered channel costs. Optional source is a channel-name prefix."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_channel_costs",
            {"project_id": project_id, "limit": limit, "offset": offset, "source": source},
            lambda: adapter.list_channel_costs(project_id, limit=limit, offset=offset, source=source),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_list_managers(project_id: int, limit: int = 200) -> dict[str, Any]:
        """List CRM managers known to a project. Email and phone are redacted."""
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            "list_managers",
            {"project_id": project_id, "limit": limit},
            lambda: adapter.list_managers(project_id, limit),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:read"), annotations=READ_ONLY)
    async def roistat_extra_read(
        kind: Literal["calltracking_scripts", "calltracking_phones", "events_log", "client_feed"],
        project_id: int,
        is_deleted: bool | None = None,
        client_id: str | None = None,
        event_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Read calltracking scripts or phone pool, the site events log, or one client's activity feed.

        PII (phones, emails, names) is redacted. client_feed needs client_id from roistat_list_clients;
        events_log takes optional event_name and ISO date_from/date_to.
        """
        adapter = registry.roistat()
        return await _provider_read(
            "roistat",
            kind,
            {
                "kind": kind,
                "project_id": project_id,
                "is_deleted": is_deleted,
                "client_id": client_id,
                "event_name": event_name,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
            lambda: adapter.extra_read(
                kind,
                project_id,
                is_deleted=is_deleted,
                client_id=client_id,
                event_name=event_name,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            ),
            validate=lambda: adapter.authorize_project(project_id),
        )

    @server.tool(auth=require_scopes("roistat:write"), annotations=PREPARE_WRITE)
    async def roistat_prepare_write(
        operation: str, project_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Draft a single-object Roistat write and open an unaccepted approval."""
        access = current_access()
        adapter = registry.roistat()
        validated = adapter.validate_write(operation, project_id, payload)
        digest = request_hash(
            {
                "provider": "roistat",
                "operation": validated["operation"],
                "project_id": validated["project_id"],
                "payload": payload,
            }
        )
        approval_id = uuid4()
        await store.create_approval(
            ApprovalRecord(
                approval_id,
                access.principal_id,
                "roistat",
                validated["operation"],
                digest,
                0.0,
                0.0,
                "prepared",
                datetime.now(UTC) + timedelta(minutes=30),
                True,
            )
        )
        return {
            "approval_id": str(approval_id),
            "request_hash": digest,
            "operation": validated["operation"],
            "project_id": validated["project_id"],
            "object_id": validated["object_id"],
            "risk_tier": validated["risk_tier"],
            "write_tool_available": settings.roistat_write_enabled,
            "next_gate": (
                "accept the approval, then call roistat_apply_write with the same "
                "operation, project_id, payload, approval_id and an idempotency_key"
            ),
        }

    @server.tool(auth=require_scopes("roistat:write"), annotations=APPLY_WRITE)
    async def roistat_apply_write(
        operation: str,
        project_id: int,
        payload: dict[str, Any],
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Execute one accepted, allowlisted single-object Roistat write with readback."""
        access = current_access()
        if not settings.roistat_write_enabled:
            raise safe_provider_error("roistat", ProviderError("Roistat write runtime is not enabled"))
        adapter = registry.roistat()
        try:
            validated = adapter.validate_write(operation, project_id, payload)
            digest = request_hash(
                {
                    "provider": "roistat",
                    "operation": validated["operation"],
                    "project_id": validated["project_id"],
                    "payload": payload,
                }
            )
            try:
                identifier = UUID(approval_id)
            except ValueError as exc:
                raise PermissionError("an accepted approval matching this write is required") from exc
            approval = await store.get_approval(identifier)
            if (
                approval is None
                or approval.principal_id != access.principal_id
                or approval.provider != "roistat"
                or approval.operation != validated["operation"]
                or approval.request_hash != digest
                or approval.status not in {"accepted", "consumed"}
            ):
                raise PermissionError("an accepted approval matching this write is required")

            async def _execute() -> dict[str, Any]:
                if not await store.consume_approval(identifier):
                    raise PermissionError("approval is not accepted or was already consumed")
                return await adapter.apply_write(operation, project_id, payload)

            return cast(
                dict[str, Any],
                await _autonomous_write(
                    "roistat",
                    validated["operation"],
                    {
                        "operation": operation,
                        "project_id": project_id,
                        "payload": payload,
                    },
                    idempotency_key,
                    enabled=True,
                    validate=lambda: None,
                    apply_fn=_execute,
                    readback_fn=lambda result: adapter.readback(
                        validated["operation"],
                        validated["project_id"],
                        result.get("object_id") if isinstance(result, dict) else validated["object_id"],
                    ),
                ),
            )
        except (ProviderError, PermissionError, ValueError) as exc:
            raise safe_provider_error("roistat", exc) from None
