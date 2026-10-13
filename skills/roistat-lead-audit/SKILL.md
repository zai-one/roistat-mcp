---
name: roistat-lead-audit
description: Audit Roistat lead and call attribution - duplicates, untagged leads, unattributed calls, orders without visit chain, sync health. Use for "аудит заявок", "дыры в разметке", "почему заявки без источника", "lead attribution audit".
license: LicenseRef-ZAI-ONE
compatibility: Requires roistat-mcp (toolsets orders_visits, calls, analytics).
metadata:
  service: roistat
---
# Lead & attribution audit

Read-only. Dimensions background: [references/dimensions.md](references/dimensions.md).

## Steps
1. Project + period (default last 30 days). `roistat_health_indicators` → note CRM/counter problems.
2. Leads: `roistat_list_leads(period)` (count) and `roistat_list_lead_duplicates(period)` → duplicate share.
3. Channels: `roistat_analytics_report(metrics=["leads","sales"], dimensions=["marker_level_1"],
   format="markdown_table")` → share of direct/unknown/referral.
4. Calls: `roistat_calltracking_summary` + `roistat_list_calls` (sample) → unattributed share.
5. Orders: `roistat_list_orders` sample of 20 → `roistat_get_order` for 3–5 without source → visit chain.
6. Tagging: `roistat_list_visits` sample — visits with empty markers/UTM.
7. Fill [templates/lead-audit.md](templates/lead-audit.md) with concrete fixes.

## Guardrails
- PII stays redacted; never ask to un-redact. Samples are samples — label them.
- Errors: [references/errors.md](references/errors.md).
