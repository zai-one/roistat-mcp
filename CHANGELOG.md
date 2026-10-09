# Changelog

## Unreleased

- `roistat_health_indicators`: official project-state processes (`GET /project/health/indicator/list`), read-only.
- `roistat_list_channels` and `roistat_list_channel_costs`: advertising channels and manually entered costs
  (`/project/analytics/source/list`, `/project/analytics/source/cost/list`), bounded locally.
- `roistat_list_managers`: CRM managers (`/project/integration/manager/list`) with email and phone redacted.
- `roistat_check_update`: suggests a newer GitHub release with its notes link and update command;
  public API, 3 s timeout, 24 h cache, graceful offline, never auto-updates. A cached
  "update available" hint appears in server instructions and `roistat_health`.
  Opt out with `ROISTAT_DISABLE_UPDATE_CHECK=1`.
- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) on every tool.
- Capability matrix lists the indicator, channel and manager sections; their write methods stay closed.

## 0.3.0

- Analytics bundles for one or two periods: provider totals by interval, attribution, explicit missing values, request replay and response digests.
- Bounded local row slices and JSON/CSV exports, preserving project authorization and cleaning supported personal fields before export.
- Installable setup wizard and JSON/TOML client snippets that work outside the checkout.
- English and Russian agency information, integration contact and package installation guide.

## 0.2.0

- Explicit config-file startup and offline configuration doctor.
- Install/client guide, local setup wizard and clean-wheel validation.
- Discover roistat_dimension_values and roistat_custom_metrics. Samples are bounded and do not expand the report metric allowlist.
- LicenseRef-ZAI-ONE and Issues-based feedback policy.
