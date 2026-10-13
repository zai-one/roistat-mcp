# Roistat playbook

1. **Project** — `roistat_list_projects`; only allowlisted project IDs work.
2. **Health first** — `roistat_health_indicators` (CRM sync, counter, analytics rebuild). Data from an
   unfinished rebuild is provisional; say so.
3. **Names** — `roistat_analytics_catalog` (metrics/attributions), `roistat_dimension_values` (channel
   names on `marker_level_1..5`).
4. **Report** — `roistat_analytics_report(metrics, dimensions=["marker_level_1"], period={"from","to"},
   format="markdown_table")`; two periods: `roistat_analytics_compare`; deliverable with totals/CSV:
   `roistat_analytics_bundle`.
5. **Leads/orders/calls** — `roistat_list_leads`, `roistat_list_orders`, `roistat_get_order` (visit
   chain), `roistat_list_calls`, `roistat_calltracking_summary`, `roistat_list_visits`.
6. **Writes** — `roistat_prepare_write` → show the draft → the operator accepts it outside MCP
   (`python -m zai_roistat.approvals ... --accept`) → `roistat_apply_write` with the same inputs.

Rules: empty/partial ≠ zero (check `completeness`); PII is always redacted; money in project currency.
Skills: `roistat-channel-roi`, `roistat-lead-audit`, `roistat-write-safe`.
Opt-in `extras` toolset (`ROISTAT_TOOLSETS=default,extras`): `roistat_extra_read` — calltracking
scripts and phone pool, events log, one client's activity feed.
Guides: `roistat://guide/metrics`, `roistat://guide/dimensions`, `roistat://guide/errors`,
`roistat://guide/tool-map` (every tool and toolset).
