# Changelog

## Unreleased — extras toolset, calltracking/events writes, router eval

- Opt-in toolset `extras` (not in default; default tool list and token budget unchanged): `roistat_extra_read` reads calltracking scripts, the phone pool, the events log (filters) and one client's activity feed (`GET /project/clients/detail/feed?client=`); PII redacted.
- `roistat_prepare_write` / `roistat_apply_write` add documented calltracking script create/update/delete, phone create/update/delete and events send/bulk send/add; deletes act on one object and need `confirm_delete`; same operator acceptance. Script create/delete were previously listed as unsupported by mistake. Phone purchase is not in the public API.
- Default toolsets no longer mean "all": unset `ROISTAT_TOOLSETS` = `default` (everything except opt-in `extras`).
- Router generated from intents (tool; skill; `roistat://guide/<topic>`), fallbacks `roistat://playbook` and `roistat://guide/tool-map`.
- `tests/test_routing_eval.py` + `tests/evals/routing_cases.json` (24 RU/EN requests incl. paraphrases and negative cases).

## 0.5.0

- License: LicenseRef-ZAI-ONE 2.0 (source-available). Free install and use for yourself and your organisation, including commercial work; issues and pull requests welcome; copying code into other projects, redistribution, embedding and competing hosted services need written permission. Earlier releases keep their LicenseRef-ZAI-ONE 1.0 terms (see NOTICE). README first screen: one-line scope, why this MCP, maintenance and update check.

- Agent layer: router `instructions` (≤1200 chars; describes prepare → operator accept → apply), compact template descriptions and titles on all 28 tools.
- Toolsets `meta`, `analytics`, `orders_visits`, `calls`, `settings_write` (`ROISTAT_TOOLSETS`, `ROISTAT_TOOLS`, `ROISTAT_DISABLED_TOOLS`, `ROISTAT_READ_ONLY=1`); `roistat://toolsets`. All toolsets stay enabled by default, so existing setups keep every tool.
- `format="markdown_table"` on `roistat_analytics_report` and `roistat_analytics_compare` (unknown values stay blank).
- Resources `roistat://playbook`, `roistat://guide/{metrics,dimensions,errors}`; prompts `channel_report`, `period_compare`.
- Self-contained skills `roistat-channel-roi`, `roistat-lead-audit`, `roistat-write-safe`; Claude Code plugin manifest, Cursor rule, `.agents/skills`.
- `scripts/token_budget.py` + tests gate instruction, description and SKILL.md sizes.
- Install snippets in the Claude Code plugin manifest and README pin `git+https://github.com/zai-one/roistat-mcp@v0.5.0` instead of the moving default branch.

## 0.4.0

- `roistat_health_indicators`: official project-state processes (`GET /project/health/indicator/list`), read-only.
- `roistat_list_channels` and `roistat_list_channel_costs`: advertising channels and manually entered costs
  (`/project/analytics/source/list`, `/project/analytics/source/cost/list`), bounded locally.
- `roistat_list_managers`: CRM managers (`/project/integration/manager/list`) with email and phone redacted.
- `roistat_check_update`: suggests a newer GitHub release with its notes link and update command;
  public API, 3 s timeout, 24 h cache, graceful offline, never auto-updates. A cached
  "update available" hint appears in server instructions and `roistat_health`.
  Opt out with `ROISTAT_DISABLE_UPDATE_CHECK=1`.
- Update check hardening: only plain version tags (`v1.2.3`) are accepted, from GitHub and from the
  cache; anything else is treated as no release and never reaches versions, commands or instructions.
  Every attempt is recorded: after a failure no new request for 30 minutes, `force=true` at most once
  a minute; the startup refresh follows the same rules. The clean-install gate and tests disable it.
- `roistat_health_indicators` tolerates odd provider values (unknown state instead of an error) and
  truncates names and messages to 500 characters.
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
