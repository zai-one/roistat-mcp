# Roistat errors

| Situation | Action |
|---|---|
| project not allowlisted | operator adds it to ROISTAT_PROJECT_ALLOWLIST |
| `completeness` partial/unknown | say so; never present as zero or total |
| rate limited | wait; `roistat_statistics_daily` is capped at 5 requests/hour |
| analytics rebuild not finished | `roistat_health_indicators`; numbers are provisional |
| write without accepted approval | operator must accept the draft; then apply with the same inputs |
| validation (period, metrics) | period {"from","to"} ISO dates; ≤12 metrics; ≤2 dimensions |
