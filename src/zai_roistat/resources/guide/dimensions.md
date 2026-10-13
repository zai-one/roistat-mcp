# Roistat analytics dimensions

| Dimension | Meaning |
|---|---|
| `marker_level_1` | channel (e.g. Яндекс.Директ, Google Ads, SEO, direct visits) |
| `marker_level_2` | campaign / sub-source |
| `marker_level_3` | ad group |
| `marker_level_4` | ad / keyword |
| `marker_level_5` | deepest marker level |

Up to 2 dimensions per report (e.g. `["marker_level_1","marker_level_2"]`). Get exact values with
`roistat_dimension_values`; values come as titles/values — quote them exactly.
Markers come from `roistat_visit` / UTM tags; untagged traffic lands in generic channels
(direct/referral) — a large share there signals tagging gaps (see skill `roistat-lead-audit`).
