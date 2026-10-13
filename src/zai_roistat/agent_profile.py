"""Roistat agent profile: router, compact descriptions, toolsets and prompts."""

from __future__ import annotations

from zai_roistat.agent_layer import Profile, Prompt

ROUTER = """Roistat MCP: end-to-end marketing analytics (channels, ROI/CPL/CPO, leads, orders, calls, visits).
Toolsets: meta, analytics, orders_visits, calls, settings_write (see roistat://toolsets); \
ROISTAT_READ_ONLY=1 removes writes.
Start: roistat_list_projects (allowlisted IDs only) -> roistat_analytics_catalog for metric/dimension names.
Reports: roistat_analytics_report / roistat_analytics_compare (format="markdown_table" for compact output), \
roistat_analytics_bundle for provider totals + CSV. Dimensions are marker_level_1..5 (channel levels).
Empty or partial results are not zero: report completeness. PII is redacted by design.
Writes: roistat_prepare_write -> show the draft -> operator accepts it outside MCP -> roistat_apply_write.
Playbooks: skills roistat-channel-roi, roistat-lead-audit, roistat-write-safe; or roistat://playbook, \
roistat://guide/{metrics,dimensions,errors}.
Errors: retry only when retryable; statistics_daily is capped at 5 requests/hour."""

DESCRIPTIONS = {
    "roistat_list_projects": "List Roistat projects visible to the key. Use first for project_id. "
    "Cost: free.",
    "roistat_capabilities": "Return the fixed capability matrix (what is readable/writable). Use when unsure "
    "a task is supported. Cost: free, no API call.",
    "roistat_health": "Probe auth, data freshness, partial state, rate limits. Use when numbers look wrong; "
    "for counter/CRM sync use `roistat_health_indicators`. Cost: 1 API call.",
    "roistat_health_indicators": "Read project processes state (CRM sync, counter, analytics rebuild). Use "
    "before trusting fresh data. Read-only.",
    "roistat_analytics_catalog": "List metrics, dimensions and attribution models. Use before any analytics "
    "report; details in roistat://guide/metrics. Cost: free.",
    "roistat_analytics_report": "Run one analytics report: metrics x marker_level dimensions for a period. "
    "Use for channel ROI; for two periods use `roistat_analytics_compare`. "
    'format="markdown_table" is compact.',
    "roistat_analytics_compare": "Compare two periods; missing values stay unknown, never zero. Use for "
    'week/month over week/month; format="markdown_table" gives now/prev/delta columns.',
    "roistat_analytics_bundle": "Bundle one or two reports with provider totals, attribution and JSON/CSV. "
    "Use for client deliverables; for quick answers use `roistat_analytics_report`.",
    "roistat_statistics_daily": "Read daily visit statistics for a period. Use for day-by-day trends. "
    "Cost: provider cap 5 requests/hour.",
    "roistat_dimension_values": "Sample allowed dimension values (channel names) with completeness. Use to "
    "find exact channel names before filtering.",
    "roistat_custom_metrics": "List custom metric definitions. Use when the user mentions a custom KPI.",
    "roistat_list_channels": "List advertising channels used in a project. Use to map sources; for costs use "
    "`roistat_list_channel_costs`.",
    "roistat_list_channel_costs": "List manually entered channel costs (optional source prefix). Use to "
    "audit manual budgets.",
    "roistat_funnel": "Read the status-funnel report. Use for lead-to-sale conversion by stage; statuses via "
    "`roistat_list_order_statuses`.",
    "roistat_list_orders": "List CRM orders (bounded pages; empty = unknown). Use for deal lists; one card "
    "via `roistat_get_order`.",
    "roistat_get_order": "Read one order card with funnel status and visit chain. Use for attribution of a "
    "specific deal.",
    "roistat_list_order_statuses": "List CRM funnel statuses mapped in the project. Use before status "
    "updates or funnel analysis.",
    "roistat_list_leads": "List proxy leads (forms/requests) for a period; PII redacted. "
    "Use for lead audits; "
    "duplicates via `roistat_list_lead_duplicates`.",
    "roistat_get_lead": "Read one proxy lead by id; phone/email redacted.",
    "roistat_list_lead_duplicates": "List duplicate proxy leads for a period. Use in lead-quality audits.",
    "roistat_list_visits": "List site visits with source markers; IPs redacted. Use to check tagging (UTM) "
    "gaps.",
    "roistat_list_clients": "List CRM clients; phone/email redacted.",
    "roistat_list_managers": "List CRM managers of a project; contacts redacted.",
    "roistat_list_calls": "List calltracking calls; numbers redacted. Use for call attribution; totals via "
    "`roistat_calltracking_summary`.",
    "roistat_calltracking_summary": "Read the calltracking dashboard summary for a period. Use for call "
    "volume/quality KPIs.",
    "roistat_prepare_write": "Draft one allowlisted write (order status, order/client import, delete order) "
    "and open an unaccepted approval. Writes: nothing is sent; operator must accept.",
    "roistat_apply_write": "Execute one accepted write with readback. Use only after the operator accepted "
    "the approval from `roistat_prepare_write`. Writes: changes Roistat data.",
    "roistat_check_update": "Check for a newer server release; never installs. Cost: free, 24h cache.",
}

TOOLSETS = {
    "meta": (
        "roistat_check_update",
        "roistat_list_projects",
        "roistat_capabilities",
        "roistat_health",
        "roistat_health_indicators",
    ),
    "analytics": (
        "roistat_analytics_catalog",
        "roistat_analytics_report",
        "roistat_analytics_compare",
        "roistat_analytics_bundle",
        "roistat_statistics_daily",
        "roistat_dimension_values",
        "roistat_custom_metrics",
        "roistat_list_channels",
        "roistat_list_channel_costs",
        "roistat_funnel",
    ),
    "orders_visits": (
        "roistat_list_orders",
        "roistat_get_order",
        "roistat_list_order_statuses",
        "roistat_list_leads",
        "roistat_get_lead",
        "roistat_list_lead_duplicates",
        "roistat_list_visits",
        "roistat_list_clients",
        "roistat_list_managers",
    ),
    "calls": ("roistat_list_calls", "roistat_calltracking_summary"),
    "settings_write": ("roistat_prepare_write", "roistat_apply_write"),
}

PROMPTS = (
    Prompt(
        "channel_report",
        "Channel ROI report for one project and period (markdown table).",
        ("project_id", "period_from", "period_to"),
        "Build a Roistat channel ROI report for project {project_id}, {period_from}..{period_to}. "
        "Follow skill "
        "roistat-channel-roi: analytics_report with visits, leads, sales, revenue, marketing_cost, roi, cpl, "
        "cpo by marker_level_1, format=markdown_table; flag partial data.",
    ),
    Prompt(
        "period_compare",
        "Compare two periods by channel: what grew, what dropped and why.",
        ("project_id", "current", "previous"),
        "Compare Roistat project {project_id} for {current} vs {previous} with roistat_analytics_compare "
        "(format=markdown_table) by marker_level_1; explain top 3 changes; unknown values stay unknown.",
    ),
)

PROFILE = Profile(
    service="roistat",
    package="zai_roistat",
    router=ROUTER,
    descriptions=DESCRIPTIONS,
    toolsets=TOOLSETS,
    prompts=PROMPTS,
)
