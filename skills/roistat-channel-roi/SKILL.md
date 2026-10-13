---
name: roistat-channel-roi
description: Marketing channel ROI report from Roistat - ROI, CPL, CPO, revenue by channel with period comparison. Use for "окупаемость каналов", "ROI по рекламе", "отчёт Roistat", "channel performance", "CPL/CPO".
license: LicenseRef-ZAI-ONE
compatibility: Requires roistat-mcp (toolset analytics).
metadata:
  service: roistat
---
# Channel ROI

Metric meanings: [references/metrics.md](references/metrics.md); dimensions:
[references/dimensions.md](references/dimensions.md).

## Steps
1. `roistat_list_projects` → project_id. Period: default last full month vs the one before.
2. `roistat_health_indicators` → warn if analytics rebuild/CRM sync not finished.
3. `roistat_analytics_compare(project_id, metrics=["visits","leads","sales","revenue","marketing_cost",
   "roi","cpl","cpo"], dimensions=["marker_level_1"], current_period, previous_period,
   format="markdown_table")`.
4. If the user wants campaigns: repeat for the top 2 channels with
   `dimensions=["marker_level_1","marker_level_2"]` (single period, `roistat_analytics_report`).
5. Fill [templates/channel-roi.md](templates/channel-roi.md): sort by revenue, flag ROI < 0, top movers.
6. For a client deliverable with totals/CSV use `roistat_analytics_bundle`.

## Guardrails
- Unknown ≠ 0; report completeness. Don't recompute ROI if Roistat returns it.
- Errors: [references/errors.md](references/errors.md).
